import base64
import csv
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from urllib.parse import quote

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import models, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, ProtectedError, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt

from accounts.utils import sanitize_csv_cell
from .forms import InvoiceCreateForm, InvoiceReportFilterForm
from .models import (
    Customer,
    Invoice,
    InvoiceItem,
    InvoicePayment,
    Product,
    Quotation,
    QuotationItem,
    StockMovement,
)
from .utils import (
    amount_to_indian_words,
    build_hsn_tax_summary,
    decode_qr_image,
    generate_invoice_pdf_bytes,
    render_to_pdf,
)


GSTIN_REGEX = re.compile(r"^[0-9A-Z]{15}$")
VALID_PAYMENT_MODES = {"Unpaid", "Cash", "UPI", "Bank Transfer", "Card", "Cheque"}
PAID_PAYMENT_MODES = {"Cash", "UPI", "Bank Transfer", "Card", "Cheque"}
ALLOWED_QR_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _validate_uploaded_qr_file(uploaded_file):
    """Validate uploaded QR image extension and MIME type before decoding."""
    import os
    filename = (getattr(uploaded_file, "name", "") or "").strip()
    if filename:
        _, ext = os.path.splitext(filename.lower())
        if ext and ext not in ALLOWED_QR_IMAGE_EXTENSIONS:
            return "Unsupported file format. Please upload a PNG, JPG, JPEG, WEBP, BMP, or GIF image."
    ctype = (getattr(uploaded_file, "content_type", "") or "").strip().lower()
    if ctype and ctype != "application/octet-stream" and not ctype.startswith("image/"):
        return "Unsupported file type. Only valid image files are accepted for QR decoding."
    return None


def _authenticate_api_user(request):
    """
    Authenticate API caller strictly via active Django session OR valid HTTP Basic Auth.
    Never trusts unauthenticated distributor_id / username parameters.
    """
    if request.user.is_authenticated:
        return request.user

    auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Basic "):
        try:
            auth_decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            username, password = auth_decoded.split(":", 1)
            user = authenticate(request, username=username, password=password)
            if user and user.is_active:
                return user
        except Exception:
            return None
    return None


@login_required
def customer_list(request):
    """
    Customer Dashboard / List View with real-time statistics,
    search filtering, role-based isolation (Admin views all, Distributor views own),
    and pagination (Task 84 & Task 85).
    """
    search_query = request.GET.get("q", "").strip()

    if request.user.is_staff or request.user.is_superuser:
        customers_qs = Customer.objects.all().select_related("distributor")
    else:
        customers_qs = Customer.objects.filter(distributor=request.user)

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)

    stats = customers_qs.aggregate(
        total_customers=Count("id"),
        active_customers=Count("id", filter=Q(is_active=True)),
        recently_added=Count("id", filter=Q(created_at__gte=seven_days_ago)),
        this_month=Count("id", filter=Q(created_at__year=now.year, created_at__month=now.month)),
    )

    if search_query:
        customers_qs = customers_qs.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(gstin__icontains=search_query) |
            Q(city__icontains=search_query) |
            Q(state__icontains=search_query)
        )

    customers_qs = customers_qs.order_by("-created_at", "-id")

    paginator = Paginator(customers_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Annotate current page customers with live Udhar (balance due) from invoices
    page_customer_ids = [c.id for c in page_obj]
    cust_due_map = {}
    if page_customer_ids:
        cust_invoices = Invoice.objects.filter(
            customer_id__in=page_customer_ids
        ).exclude(status__iexact="Cancelled").only(
            "customer_id", "total_amount", "amount_paid", "status"
        )
        for inv in cust_invoices:
            cust_due_map[inv.customer_id] = cust_due_map.get(inv.customer_id, Decimal("0.00")) + inv.balance_due

    for cust in page_obj:
        cust.balance_due = cust_due_map.get(cust.id, Decimal("0.00"))

    context = {
        "customers": page_obj,
        "page_obj": page_obj,
        "paginator": paginator,
        "search_query": search_query,
        "total_customers": stats["total_customers"],
        "active_customers": stats["active_customers"],
        "recently_added": stats["recently_added"],
        "this_month": stats["this_month"],
    }
    return render(request, "billing/customer_list.html", context)


@login_required
def customer_register_view(request):
    """
    Front-end view for registering a new customer.
    Task 81: Admin can add for any distributor or all; Distributor adds only their own.
    """
    errors = {}
    form_data = {}
    distributors = User.objects.filter(is_staff=False).order_by("username") if (request.user.is_staff or request.user.is_superuser) else []

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        gstin = request.POST.get("gstin", "").strip().upper()
        address = request.POST.get("address", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        is_active = request.POST.get("is_active") in ["on", "true", True, "1"]
        distributor_id = request.POST.get("distributor_id")

        form_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "gstin": gstin,
            "address": address,
            "city": city,
            "state": state,
            "pincode": pincode,
            "is_active": is_active,
            "distributor_id": distributor_id,
        }

        if not name:
            errors["name"] = "Full Name is required."
        elif len(name) < 3:
            errors["name"] = "Name must contain at least 3 characters."
        elif len(name) > 100:
            errors["name"] = "Name cannot exceed 100 characters."

        if not phone:
            errors["phone"] = "Phone number is required."
        elif not phone.isdigit() or len(phone) != 10:
            errors["phone"] = "Please enter a valid 10-digit phone number."

        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors["email"] = "Please enter a valid email address."

        if gstin and not GSTIN_REGEX.match(gstin):
            errors["gstin"] = "Please enter a valid 15-character alphanumeric GSTIN."

        if not city:
            errors["city"] = "City is required."
        elif len(city) > 50:
            errors["city"] = "City cannot exceed 50 characters."

        if not state:
            errors["state"] = "State is required."
        elif len(state) > 50:
            errors["state"] = "State cannot exceed 50 characters."

        if not pincode:
            errors["pincode"] = "Pincode is required."
        elif not pincode.isdigit() or len(pincode) < 5 or len(pincode) > 6:
            errors["pincode"] = "Please enter a valid 6-digit postal pincode."

        target_distributor = request.user
        if (request.user.is_staff or request.user.is_superuser) and distributor_id:
            assigned_dist = User.objects.filter(pk=distributor_id).first()
            if assigned_dist:
                target_distributor = assigned_dist

        if not errors:
            customer = Customer.objects.create(
                distributor=target_distributor,
                name=name,
                email=email if email else None,
                phone=phone,
                gstin=gstin,
                address=address if address else None,
                city=city,
                state=state,
                pincode=pincode,
                is_active=is_active,
            )
            messages.success(request, f"Customer '{customer.name}' registered successfully.")
            return redirect("customer_list")

    return render(
        request,
        "billing/customer_register.html",
        {
            "is_edit": False,
            "errors": errors,
            "form_data": form_data,
            "distributors": distributors,
        }
    )


# Alias for backward-compatibility
customer_add = customer_register_view


@login_required
def customer_edit(request, pk):
    """
    Edit existing customer with user ownership checks (Task 83).
    Admin can edit any customer; Distributor can only edit their own.
    """
    if request.user.is_staff or request.user.is_superuser:
        customer = get_object_or_404(Customer, pk=pk)
    else:
        customer = get_object_or_404(Customer, pk=pk, distributor=request.user)

    distributors = User.objects.filter(is_staff=False).order_by("username") if (request.user.is_staff or request.user.is_superuser) else []
    errors = {}
    form_data = {
        "name": customer.name,
        "email": customer.email or "",
        "phone": customer.phone,
        "gstin": customer.gstin or "",
        "address": customer.address or "",
        "city": customer.city,
        "state": customer.state,
        "pincode": customer.pincode,
        "is_active": customer.is_active,
        "distributor_id": customer.distributor_id,
    }

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        gstin = request.POST.get("gstin", customer.gstin or "").strip().upper()
        address = request.POST.get("address", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        is_active = request.POST.get("is_active") == "on"
        distributor_id = request.POST.get("distributor_id")

        form_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "gstin": gstin,
            "address": address,
            "city": city,
            "state": state,
            "pincode": pincode,
            "is_active": is_active,
            "distributor_id": distributor_id or customer.distributor_id,
        }

        if not name:
            errors["name"] = "Full Name is required."
        elif len(name) < 3:
            errors["name"] = "Name must contain at least 3 characters."
        elif len(name) > 100:
            errors["name"] = "Name cannot exceed 100 characters."

        if not phone:
            errors["phone"] = "Phone number is required."
        elif not phone.isdigit() or len(phone) != 10:
            errors["phone"] = "Please enter a valid 10-digit phone number."

        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors["email"] = "Please enter a valid email address."

        if gstin and not GSTIN_REGEX.match(gstin):
            errors["gstin"] = "Please enter a valid 15-character alphanumeric GSTIN."

        if not city:
            errors["city"] = "City is required."
        elif len(city) > 50:
            errors["city"] = "City cannot exceed 50 characters."

        if not state:
            errors["state"] = "State is required."
        elif len(state) > 50:
            errors["state"] = "State cannot exceed 50 characters."

        if not pincode:
            errors["pincode"] = "Pincode is required."
        elif not pincode.isdigit() or len(pincode) < 5 or len(pincode) > 6:
            errors["pincode"] = "Please enter a valid 6-digit postal pincode."

        if not errors:
            customer.name = name
            customer.email = email if email else None
            customer.phone = phone
            customer.gstin = gstin
            customer.address = address
            customer.city = city
            customer.state = state
            customer.pincode = pincode
            customer.is_active = is_active
            if (request.user.is_staff or request.user.is_superuser) and distributor_id:
                reassigned_dist = User.objects.filter(pk=distributor_id).first()
                if reassigned_dist:
                    customer.distributor = reassigned_dist
            customer.save()

            messages.success(request, "Customer updated successfully.")
            return redirect("customer_list")

    return render(
        request,
        "billing/customer_form.html",
        {
            "is_edit": True,
            "customer": customer,
            "errors": errors,
            "form_data": form_data,
            "distributors": distributors,
        }
    )


@login_required
def customer_delete(request, pk):
    """
    Safely delete customer via POST with user ownership check and ProtectedError handling.
    Admin can delete any customer; Distributor can only delete their own.
    """
    if request.user.is_staff or request.user.is_superuser:
        customer = get_object_or_404(Customer, pk=pk)
    else:
        customer = get_object_or_404(Customer, pk=pk, distributor=request.user)

    if request.method == "POST":
        customer_name = customer.name
        try:
            customer.delete()
            messages.success(request, f'Customer "{customer_name}" deleted successfully.')
        except ProtectedError:
            messages.error(
                request,
                f'Cannot delete customer "{customer_name}" because existing invoices are linked to this customer. You may mark them inactive instead.'
            )
        return redirect("customer_list")

    messages.error(request, "Invalid request method for delete.")
    return redirect("customer_list")


@login_required
def product_add(request):
    """
    Task 82: Create forms and views to add new products (same role-based logic as customers).
    Uses Decimal precision for price and GST rate.
    """
    distributors = User.objects.filter(is_staff=False).order_by("username") if (request.user.is_staff or request.user.is_superuser) else []

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        sku = request.POST.get("sku", "").strip()
        hsn_code = request.POST.get("hsn_code", "").strip()
        category = request.POST.get("category", "").strip()
        price = request.POST.get("price", "").strip()
        stock = request.POST.get("stock", "").strip()
        gst_rate = request.POST.get("gst_rate", "").strip()
        description = request.POST.get("description", "").strip()
        distributor_id = request.POST.get("distributor_id")

        context = {
            "name": name,
            "sku": sku,
            "hsn_code": hsn_code,
            "category": category,
            "price": price,
            "stock": stock,
            "gst_rate": gst_rate,
            "description": description,
            "distributors": distributors,
            "selected_distributor_id": distributor_id,
        }

        if not all([name, category, price, stock, gst_rate]):
            context["error"] = "Please fill in all required fields."
            return render(request, "billing/product_add.html", context)

        if len(name) < 2:
            context["error"] = "Product name must contain at least 2 characters."
            return render(request, "billing/product_add.html", context)

        try:
            price_value = Decimal(price)
            if price_value <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            context["error"] = "Please enter a valid price greater than 0."
            return render(request, "billing/product_add.html", context)

        try:
            stock_value = int(stock)
            if stock_value < 0:
                raise ValueError
        except ValueError:
            context["error"] = "Stock must be a valid non-negative number."
            return render(request, "billing/product_add.html", context)

        try:
            gst_value = Decimal(gst_rate)
            if gst_value < 0 or gst_value > 100:
                raise ValueError
        except (InvalidOperation, ValueError):
            context["error"] = "GST rate must be between 0 and 100."
            return render(request, "billing/product_add.html", context)

        target_distributor = request.user
        if (request.user.is_staff or request.user.is_superuser) and distributor_id:
            assigned_dist = User.objects.filter(pk=distributor_id).first()
            if assigned_dist:
                target_distributor = assigned_dist

        created_product = Product.objects.create(
            distributor=target_distributor,
            name=name,
            sku=sku,
            hsn_code=hsn_code,
            category=category,
            price=price_value,
            stock=stock_value,
            gst_rate=gst_value,
            description=description,
        )
        if stock_value > 0:
            StockMovement.objects.create(
                product=created_product,
                distributor=target_distributor,
                movement_type="OPENING",
                quantity_change=stock_value,
                stock_before=0,
                stock_after=stock_value,
                reference="Opening Stock",
                notes="Initial inventory on product creation",
            )

        messages.success(request, "Product added successfully.")
        return redirect("product_list")

    return render(
        request,
        "billing/product_add.html",
        {"distributors": distributors}
    )


@login_required
def product_list(request):
    """
    Product Management Dashboard & List View with live inventory KPI metrics (SQL aggregated),
    search filtering, pagination, and multi-tenant isolation (Task 84 & Task 85).
    """
    query = request.GET.get("q", "").strip()

    if request.user.is_staff or request.user.is_superuser:
        base_qs = Product.objects.all().select_related("distributor")
    else:
        base_qs = Product.objects.filter(distributor=request.user)

    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=16, decimal_places=2))
    inv_val_expr = ExpressionWrapper(
        F("price") * F("stock"),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )
    stats = base_qs.aggregate(
        total_products=Count("id"),
        low_stock_count=Count("id", filter=Q(stock__gt=0, stock__lte=10)),
        out_of_stock_count=Count("id", filter=Q(stock=0)),
        in_stock_count=Count("id", filter=Q(stock__gt=10)),
        total_inventory_value=Coalesce(Sum(inv_val_expr), zero_dec),
    )

    products = base_qs.order_by("-created_at")

    if query:
        products = products.filter(
            models.Q(name__icontains=query) |
            models.Q(sku__icontains=query) |
            models.Q(hsn_code__icontains=query) |
            models.Q(category__icontains=query) |
            models.Q(description__icontains=query)
        )

    paginator = Paginator(products, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "billing/product_list.html",
        {
            "products": page_obj,
            "page_obj": page_obj,
            "query": query,
            "search_query": query,
            "total_products": stats["total_products"],
            "low_stock_count": stats["low_stock_count"],
            "out_of_stock_count": stats["out_of_stock_count"],
            "in_stock_count": stats["in_stock_count"],
            "total_inventory_value": stats["total_inventory_value"],
        }
    )


@login_required
def product_edit(request, pk):
    """
    Edit existing product with user ownership verification (Task 83).
    Admin can edit any product; Distributor can only edit their own.
    """
    if request.user.is_staff or request.user.is_superuser:
        product = get_object_or_404(Product, pk=pk)
    else:
        product = get_object_or_404(Product, pk=pk, distributor=request.user)

    distributors = User.objects.filter(is_staff=False).order_by("username") if (request.user.is_staff or request.user.is_superuser) else []

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        sku = request.POST.get("sku", product.sku or "").strip()
        hsn_code = request.POST.get("hsn_code", product.hsn_code or "").strip()
        category = request.POST.get("category", "").strip()
        price = request.POST.get("price", "").strip()
        stock = request.POST.get("stock", "").strip()
        gst_rate = request.POST.get("gst_rate", "").strip()
        description = request.POST.get("description", "").strip()
        distributor_id = request.POST.get("distributor_id")

        if not name or not category or not price or not stock or not gst_rate:
            return render(
                request,
                "billing/product_edit.html",
                {
                    "product": product,
                    "error": "Please fill in all required fields.",
                    "distributors": distributors,
                }
            )

        if len(name) < 2:
            return render(
                request,
                "billing/product_edit.html",
                {
                    "product": product,
                    "error": "Product name must contain at least 2 characters.",
                    "distributors": distributors,
                }
            )

        try:
            price_value = Decimal(price)
            if price_value <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return render(
                request,
                "billing/product_edit.html",
                {
                    "product": product,
                    "error": "Price must be greater than 0.",
                    "distributors": distributors,
                }
            )

        try:
            stock_value = int(stock)
            if stock_value < 0:
                raise ValueError
        except ValueError:
            return render(
                request,
                "billing/product_edit.html",
                {
                    "product": product,
                    "error": "Stock cannot be negative.",
                    "distributors": distributors,
                }
            )

        try:
            gst_value = Decimal(gst_rate)
            if gst_value < 0 or gst_value > 100:
                raise ValueError
        except (InvalidOperation, ValueError):
            return render(
                request,
                "billing/product_edit.html",
                {
                    "product": product,
                    "error": "GST rate must be between 0 and 100.",
                    "distributors": distributors,
                }
            )

        old_stock = product.stock
        product.name = name
        product.sku = sku
        product.hsn_code = hsn_code
        product.category = category
        product.price = price_value
        product.stock = stock_value
        product.gst_rate = gst_value
        product.description = description
        if (request.user.is_staff or request.user.is_superuser) and distributor_id:
            reassigned_dist = User.objects.filter(pk=distributor_id).first()
            if reassigned_dist:
                product.distributor = reassigned_dist

        product.save()
        if stock_value != old_stock:
            StockMovement.objects.create(
                product=product,
                distributor=product.distributor,
                movement_type="ADJUSTMENT",
                quantity_change=stock_value - old_stock,
                stock_before=old_stock,
                stock_after=stock_value,
                reference="Product Edit",
                notes="Stock updated via product edit form",
            )

        messages.success(request, f"Product '{product.name}' updated successfully.")
        return redirect("product_list")

    return render(
        request,
        "billing/product_edit.html",
        {
            "product": product,
            "distributors": distributors,
        }
    )


@login_required
def product_delete(request, pk):
    """
    Safely delete product with user ownership check and ProtectedError handling.
    Admin can delete any product; Distributor can only delete their own.
    """
    if request.user.is_staff or request.user.is_superuser:
        product = get_object_or_404(Product, pk=pk)
    else:
        product = get_object_or_404(Product, pk=pk, distributor=request.user)

    if request.method == "POST":
        product_name = product.name
        try:
            product.delete()
            messages.success(request, f"Product '{product_name}' deleted successfully.")
        except ProtectedError:
            messages.error(
                request,
                f"Cannot delete product '{product_name}' because it is referenced in existing invoices. Set its stock to 0 instead."
            )
        return redirect("product_list")

    messages.error(request, "Invalid request for product deletion.")
    return redirect("product_list")


@login_required
def product_detail(request, pk):
    """
    Read / View single product details with user ownership verification.
    Admin can view any product; Distributor can only view their own.
    """
    if request.user.is_staff or request.user.is_superuser:
        product = get_object_or_404(Product, pk=pk)
    else:
        product = get_object_or_404(Product, pk=pk, distributor=request.user)
    recent_movements = product.stock_movements.all()[:15]
    return render(
        request,
        "billing/product_detail.html",
        {
            "product": product,
            "recent_movements": recent_movements,
        }
    )


def generate_invoice_number(user):
    """
    Generate a globally unique, collision-safe sequential invoice number:
    INV-YYYYMMDD-0001 (checks globally across all distributors so two
    distributors creating invoices on the same day never hit IntegrityError).
    """
    today_str = timezone.localtime(timezone.now()).strftime("%Y%m%d")
    prefix = f"INV-{today_str}-"
    existing_numbers = Invoice.objects.filter(
        invoice_number__startswith=prefix
    ).values_list("invoice_number", flat=True)

    max_seq = 0
    for inv_num in existing_numbers:
        suffix = inv_num[len(prefix):]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))

    next_seq = max_seq + 1
    candidate = f"{prefix}{next_seq:04d}"
    while Invoice.objects.filter(invoice_number=candidate).exists():
        next_seq += 1
        candidate = f"{prefix}{next_seq:04d}"
    return candidate


def _compute_tax_split(distributor, customer, total_gst):
    """
    Compute CGST/SGST (intra-state) vs IGST (inter-state) split based on
    distributor profile state and customer state.
    """
    dist_profile = getattr(distributor, "distributor_profile", None)
    dist_state = (dist_profile.state or "").strip().lower() if dist_profile else ""
    cust_state = (customer.state or "").strip().lower() if customer else ""

    if dist_state and cust_state and dist_state != cust_state:
        return True, Decimal("0.00"), Decimal("0.00"), total_gst

    cgst = (total_gst / Decimal("2")).quantize(Decimal("0.01"))
    sgst = (total_gst - cgst).quantize(Decimal("0.01"))
    return False, cgst, sgst, Decimal("0.00")


@login_required
def invoice_create(request):
    """
    Create Invoice with dynamic customer & product dropdowns, strict server-side
    bounds validation, atomic stock verification & deduction + StockMovement log,
    discount persistence, CGST/SGST vs IGST split, due dates, optional round-off,
    and immediate full/partial payment recording.
    """
    distributor = request.user
    form = InvoiceCreateForm(distributor=distributor)
    products = Product.objects.filter(distributor=distributor).order_by("name")
    dist_profile = getattr(distributor, "distributor_profile", None)
    distributor_state = (dist_profile.state or "").strip() if dist_profile else ""
    customer_states = {
        str(c.id): (c.state or "").strip()
        for c in form.fields["customer"].queryset
    }
    base_ctx = {
        "form": form,
        "products": products,
        "distributor_state": distributor_state,
        "customer_states_json": json.dumps(customer_states),
        "today_iso": timezone.localdate().isoformat(),
    }

    if request.method == "POST":
        form = InvoiceCreateForm(request.POST, distributor=distributor)
        base_ctx["form"] = form
        product_ids = request.POST.getlist("product[]")
        quantities = request.POST.getlist("quantity[]")
        unit_prices = request.POST.getlist("unit_price[]")
        gst_rates = request.POST.getlist("gst_rate[]")
        discounts = request.POST.getlist("discount[]")

        if form.is_valid():
            customer = form.cleaned_data["customer"]

            valid_rows = [i for i in range(len(product_ids)) if product_ids[i].strip()]

            if not valid_rows:
                messages.error(request, "Please add at least one product to the invoice.")
                return render(request, "billing/invoice_create.html", base_ctx)

            # Parse optional due date
            raw_due_date = (request.POST.get("due_date") or "").strip()
            due_date_val = None
            if raw_due_date:
                try:
                    due_date_val = date.fromisoformat(raw_due_date)
                except ValueError:
                    messages.error(request, "Invalid due date format. Please pick a valid date.")
                    return render(request, "billing/invoice_create.html", base_ctx)

            notes_val = (request.POST.get("notes") or "").strip()[:1000]
            payment_ref = (request.POST.get("payment_reference") or "").strip()[:100]
            apply_round_off = request.POST.get("apply_round_off") in ("1", "on", "true")

            raw_initial_paid = (request.POST.get("initial_paid") or "").strip()
            initial_paid_val = Decimal("0.00")
            if raw_initial_paid:
                try:
                    initial_paid_val = Decimal(raw_initial_paid).quantize(Decimal("0.01"))
                    if initial_paid_val < Decimal("0.00"):
                        raise ValueError("Initial paid amount cannot be negative.")
                except (InvalidOperation, ValueError):
                    messages.error(request, "Initial paid amount must be a valid non-negative number.")
                    return render(request, "billing/invoice_create.html", base_ctx)

            try:
                with transaction.atomic():
                    total_subtotal = Decimal("0.00")
                    total_discount = Decimal("0.00")
                    total_gst = Decimal("0.00")
                    items_to_create = []
                    stock_logs_to_create = []
                    locked_products = {}

                    for idx in valid_rows:
                        p_id = int(product_ids[idx])
                        if p_id not in locked_products:
                            product = get_object_or_404(
                                Product.objects.select_for_update(),
                                pk=p_id,
                                distributor=distributor,
                            )
                            locked_products[p_id] = product
                        else:
                            product = locked_products[p_id]

                        qty = int(quantities[idx]) if idx < len(quantities) and quantities[idx] else 1
                        if qty <= 0:
                            raise ValueError(f"Quantity for product '{product.name}' must be at least 1.")

                        if product.stock < qty:
                            raise ValueError(
                                f"Insufficient stock for '{product.name}' (Available: {product.stock}, Requested: {qty})."
                            )

                        price = Decimal(str(unit_prices[idx])) if idx < len(unit_prices) and unit_prices[idx] else product.price
                        if price <= Decimal("0.00"):
                            raise ValueError(f"Unit price for '{product.name}' must be greater than 0.")

                        gst_rate = Decimal(str(gst_rates[idx])) if idx < len(gst_rates) and gst_rates[idx] else product.gst_rate
                        if gst_rate < Decimal("0.00") or gst_rate > Decimal("100.00"):
                            raise ValueError(f"GST rate for '{product.name}' must be between 0 and 100.")

                        disc_pct = Decimal(str(discounts[idx])) if idx < len(discounts) and discounts[idx] else Decimal("0.00")
                        if disc_pct < Decimal("0.00") or disc_pct > Decimal("100.00"):
                            raise ValueError(f"Discount for '{product.name}' must be between 0% and 100%.")

                        # Deduct from locked product stock & capture before/after for StockMovement
                        stock_before = product.stock
                        product.stock -= qty
                        stock_after = product.stock
                        stock_logs_to_create.append({
                            "product": product,
                            "qty": qty,
                            "stock_before": stock_before,
                            "stock_after": stock_after,
                        })

                        # Line Calculations
                        line_base = (Decimal(qty) * price).quantize(Decimal("0.01"))
                        disc_amount = (line_base * (disc_pct / Decimal("100"))).quantize(Decimal("0.01"))
                        line_subtotal = (line_base - disc_amount).quantize(Decimal("0.01"))
                        line_gst = (line_subtotal * (gst_rate / Decimal("100"))).quantize(Decimal("0.01"))
                        line_total = (line_subtotal + line_gst).quantize(Decimal("0.01"))

                        total_subtotal += line_subtotal
                        total_discount += disc_amount
                        total_gst += line_gst

                        items_to_create.append({
                            "product": product,
                            "quantity": qty,
                            "unit_price": price,
                            "discount_percent": disc_pct,
                            "discount_amount": disc_amount,
                            "gst_rate": gst_rate,
                            "subtotal": line_subtotal,
                            "total": line_total,
                        })

                    # Persist updated stock values atomically
                    for prod in locked_products.values():
                        prod.save(update_fields=["stock", "updated_at"])

                    inv_number = generate_invoice_number(distributor)
                    raw_grand_total = (total_subtotal + total_gst).quantize(Decimal("0.01"))
                    round_off_val = Decimal("0.00")
                    grand_total = raw_grand_total
                    if apply_round_off:
                        rounded_total = raw_grand_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP).quantize(Decimal("0.01"))
                        round_off_val = (rounded_total - raw_grand_total).quantize(Decimal("0.01"))
                        grand_total = rounded_total

                    if initial_paid_val > grand_total:
                        raise ValueError(
                            f"Initial paid amount (Rs. {initial_paid_val}) cannot exceed invoice total (Rs. {grand_total})."
                        )

                    payment_status = request.POST.get("status", "Pending").strip()
                    if payment_status not in ("Paid", "Pending", "Partial"):
                        payment_status = "Pending"

                    payment_mode = request.POST.get("payment_mode", "").strip()
                    if payment_mode not in VALID_PAYMENT_MODES:
                        payment_mode = "Cash" if payment_status in ("Paid", "Partial") else "Unpaid"

                    if payment_status == "Paid":
                        amount_paid_val = grand_total
                        if payment_mode == "Unpaid":
                            payment_mode = "Cash"
                    elif initial_paid_val >= grand_total and grand_total > Decimal("0.00"):
                        payment_status = "Paid"
                        amount_paid_val = grand_total
                        if payment_mode == "Unpaid":
                            payment_mode = "Cash"
                    elif initial_paid_val > Decimal("0.00"):
                        payment_status = "Partial"
                        amount_paid_val = initial_paid_val
                        if payment_mode == "Unpaid":
                            payment_mode = "Cash"
                    else:
                        payment_status = "Pending"
                        amount_paid_val = Decimal("0.00")
                        payment_mode = "Unpaid"

                    paid_at = timezone.now() if payment_status == "Paid" else None
                    is_interstate, cgst_amount, sgst_amount, igst_amount = _compute_tax_split(
                        distributor, customer, total_gst
                    )

                    invoice = Invoice.objects.create(
                        invoice_number=inv_number,
                        customer=customer,
                        distributor=distributor,
                        subtotal=total_subtotal,
                        discount_total=total_discount,
                        gst_amount=total_gst,
                        cgst_amount=cgst_amount,
                        sgst_amount=sgst_amount,
                        igst_amount=igst_amount,
                        is_interstate=is_interstate,
                        round_off=round_off_val,
                        total_amount=grand_total,
                        amount_paid=amount_paid_val,
                        due_date=due_date_val,
                        notes=notes_val,
                        status=payment_status,
                        payment_mode=payment_mode,
                        paid_at=paid_at,
                    )

                    for item_data in items_to_create:
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            product=item_data["product"],
                            quantity=item_data["quantity"],
                            unit_price=item_data["unit_price"],
                            discount_percent=item_data["discount_percent"],
                            discount_amount=item_data["discount_amount"],
                            gst_rate=item_data["gst_rate"],
                            subtotal=item_data["subtotal"],
                            total=item_data["total"],
                        )

                    for sl in stock_logs_to_create:
                        StockMovement.objects.create(
                            product=sl["product"],
                            distributor=distributor,
                            movement_type="SALE",
                            quantity_change=-sl["qty"],
                            stock_before=sl["stock_before"],
                            stock_after=sl["stock_after"],
                            reference=inv_number,
                            notes=f"Sold to {customer.name}",
                        )

                    if amount_paid_val > Decimal("0.00"):
                        InvoicePayment.objects.create(
                            invoice=invoice,
                            distributor=distributor,
                            amount=amount_paid_val,
                            payment_mode=payment_mode if payment_mode in PAID_PAYMENT_MODES else "Cash",
                            reference_number=payment_ref,
                            payment_date=timezone.localdate(),
                            notes="Paid at invoice creation" if payment_status == "Paid" else "Initial partial payment",
                        )

                    # Refresh QR code on invoice save after items are attached (Task 60)
                    invoice.save()

                    messages.success(request, f"Invoice {inv_number} generated successfully.")
                    return redirect("invoice_detail", pk=invoice.pk)

            except (ValueError, InvalidOperation) as e:
                messages.error(request, str(e))
                return render(request, "billing/invoice_create.html", base_ctx)
        else:
            messages.error(request, "Please select a valid customer.")

    return render(request, "billing/invoice_create.html", base_ctx)


@login_required
def invoice_list(request):
    """
    Invoice directory listing with search, customer filter, status filter,
    date range filtering, SQL-aggregated KPI totals, and pagination.
    """
    search_query = request.GET.get("q", "").strip()
    selected_customer = request.GET.get("customer", "").strip()
    selected_status = request.GET.get("status", "").strip()
    start_date_str = request.GET.get("start_date", "").strip()
    end_date_str = request.GET.get("end_date", "").strip()

    is_admin = request.user.is_staff or request.user.is_superuser
    if is_admin:
        invoices_qs = (
            Invoice.objects.all()
            .select_related("customer", "distributor")
            .prefetch_related("items__product")
            .order_by("-created_at", "-id")
        )
        customers_filter_qs = Customer.objects.all().order_by("name")
    else:
        invoices_qs = (
            Invoice.objects.filter(distributor=request.user)
            .select_related("customer")
            .prefetch_related("items__product")
            .order_by("-created_at", "-id")
        )
        customers_filter_qs = Customer.objects.filter(distributor=request.user).order_by("name")

    if search_query:
        invoices_qs = invoices_qs.filter(
            Q(invoice_number__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(customer__phone__icontains=search_query)
        )
    if selected_customer.isdigit():
        invoices_qs = invoices_qs.filter(customer_id=int(selected_customer))
    if selected_status:
        invoices_qs = invoices_qs.filter(status__iexact=selected_status)
    if start_date_str:
        try:
            invoices_qs = invoices_qs.filter(invoice_date__date__gte=date.fromisoformat(start_date_str))
        except ValueError:
            pass
    if end_date_str:
        try:
            invoices_qs = invoices_qs.filter(invoice_date__date__lte=date.fromisoformat(end_date_str))
        except ValueError:
            pass

    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
    totals = invoices_qs.aggregate(
        total_invoices=Count("id"),
        total_billed=Coalesce(Sum("total_amount", filter=~Q(status__iexact="Cancelled")), zero_dec),
    )

    paginator = Paginator(invoices_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Format only the current page's items
    for inv in page_obj:
        item_list = list(inv.items.all())
        inv.product_count = len(item_list)
        inv.product_summary = ", ".join(f"{item.product.name} (x{item.quantity})" for item in item_list)
        inv.product_names = [item.product.name for item in item_list]
        inv.qr_code_base64 = inv.qr_code_data or inv.generate_qr_code_base64()

    filter_params = request.GET.copy()
    filter_params.pop("page", None)
    filter_querystring = filter_params.urlencode()

    return render(request, "billing/invoice_list.html", {
        "invoices": page_obj,
        "page_obj": page_obj,
        "search_query": search_query,
        "customers_filter": customers_filter_qs,
        "selected_customer": selected_customer,
        "selected_status": selected_status,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "filter_querystring": filter_querystring,
        "total_invoices": totals["total_invoices"],
        "total_billed": totals["total_billed"],
    })


@login_required
def invoice_report(request):
    """
    Task 43: Report generation view for filtering invoices by date range.
    Supports multi-tenant isolation for Distributors and full visibility for Admins.
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    distributor = request.user
    form = InvoiceReportFilterForm(request.GET or None, distributor=distributor, is_admin=is_admin)

    if is_admin:
        invoices_qs = (
            Invoice.objects.all()
            .select_related("customer", "distributor")
            .prefetch_related("items__product")
            .order_by("-invoice_date")
        )
    else:
        invoices_qs = (
            Invoice.objects.filter(distributor=distributor)
            .select_related("customer")
            .prefetch_related("items__product")
            .order_by("-invoice_date")
        )

    start_date = None
    end_date = None
    selected_status = ""
    selected_customer = None

    if form.is_valid():
        start_date = form.cleaned_data.get("start_date")
        end_date = form.cleaned_data.get("end_date")
        selected_status = form.cleaned_data.get("status")
        selected_customer = form.cleaned_data.get("customer")

        if start_date:
            invoices_qs = invoices_qs.filter(invoice_date__date__gte=start_date)
        if end_date:
            invoices_qs = invoices_qs.filter(invoice_date__date__lte=end_date)
        if selected_status:
            invoices_qs = invoices_qs.filter(status__iexact=selected_status)
        if selected_customer:
            invoices_qs = invoices_qs.filter(customer=selected_customer)

    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
    not_cancelled = ~Q(status__iexact="Cancelled")
    agg = invoices_qs.aggregate(
        total_invoices_count=Count("id"),
        total_amount_collected=Coalesce(Sum("total_amount", filter=not_cancelled), zero_dec),
        total_tax_collected=Coalesce(Sum("gst_amount", filter=not_cancelled), zero_dec),
        total_subtotal_amount=Coalesce(Sum("subtotal", filter=not_cancelled), zero_dec),
        paid_count=Count("id", filter=Q(status__iexact="Paid")),
        partial_count=Count("id", filter=Q(status__iexact="Partial")),
        pending_count=Count("id", filter=Q(status__iexact="Pending")),
        cancelled_count=Count("id", filter=Q(status__iexact="Cancelled")),
    )

    # Compute true collected payments vs pending receivables & customer-wise + monthly analytics
    active_filtered = list(
        invoices_qs.exclude(status__iexact="Cancelled")
        .select_related(None)
        .select_related("customer")
        .only("id", "invoice_date", "total_amount", "gst_amount", "amount_paid", "status", "customer_id", "customer__name", "customer__phone")
    )
    true_paid_amount = Decimal("0.00")
    true_pending_amount = Decimal("0.00")
    customer_buckets = {}
    for inv in active_filtered:
        inv_paid = inv.effective_amount_paid
        inv_due = inv.balance_due
        true_paid_amount += inv_paid
        true_pending_amount += inv_due

        cid = inv.customer_id
        if cid not in customer_buckets:
            customer_buckets[cid] = {
                "customer_id": cid,
                "customer_name": inv.customer.name,
                "customer_phone": inv.customer.phone,
                "invoice_count": 0,
                "total_billed": Decimal("0.00"),
                "total_paid": Decimal("0.00"),
                "balance_due": Decimal("0.00"),
            }
        cb = customer_buckets[cid]
        cb["invoice_count"] += 1
        cb["total_billed"] += inv.total_amount or Decimal("0.00")
        cb["total_paid"] += inv_paid
        cb["balance_due"] += inv_due

    customer_sales_report = sorted(
        customer_buckets.values(),
        key=lambda r: r["total_billed"],
        reverse=True,
    )[:15]

    # Monthly Revenue Chart (last 6 months of filtered invoices)
    now_local = timezone.localtime(timezone.now())
    monthly_revenue_chart = []
    for m_offset in range(5, -1, -1):
        b_y, b_m = divmod(now_local.year * 12 + (now_local.month - 1) - m_offset, 12)
        b_m += 1
        b_date = now_local.date().replace(year=b_y, month=b_m, day=1)
        m_invs = [
            inv for inv in active_filtered
            if inv.invoice_date and timezone.localtime(inv.invoice_date).year == b_y
            and timezone.localtime(inv.invoice_date).month == b_m
        ]
        m_rev = sum((inv.total_amount for inv in m_invs), Decimal("0.00"))
        m_paid = sum((inv.effective_amount_paid for inv in m_invs), Decimal("0.00"))
        monthly_revenue_chart.append({
            "label": b_date.strftime("%b %Y"),
            "revenue": float(m_rev),
            "collected": float(m_paid),
            "count": len(m_invs),
        })
    max_month_rev = max((pt["revenue"] for pt in monthly_revenue_chart), default=0.0)
    for pt in monthly_revenue_chart:
        pt["rev_pct"] = round((pt["revenue"] / max_month_rev) * 100, 1) if max_month_rev > 0 else 0
        pt["col_pct"] = round((pt["collected"] / max_month_rev) * 100, 1) if max_month_rev > 0 else 0

    paginator = Paginator(invoices_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    for inv in page_obj:
        item_list = list(inv.items.all())
        inv.product_count = len(item_list)
        inv.product_summary = ", ".join(f"{item.product.name} (x{item.quantity})" for item in item_list)

    context = {
        "form": form,
        "invoices": page_obj,
        "page_obj": page_obj,
        "start_date": start_date,
        "end_date": end_date,
        "selected_status": selected_status,
        "selected_customer": selected_customer,
        "total_invoices_count": agg["total_invoices_count"],
        "total_amount_collected": agg["total_amount_collected"],
        "total_tax_collected": agg["total_tax_collected"],
        "total_subtotal_amount": agg["total_subtotal_amount"],
        "paid_count": agg["paid_count"],
        "partial_count": agg["partial_count"],
        "pending_count": agg["pending_count"],
        "cancelled_count": agg["cancelled_count"],
        "paid_amount": true_paid_amount,
        "pending_amount": true_pending_amount,
        "monthly_revenue_chart": monthly_revenue_chart,
        "customer_sales_report": customer_sales_report,
    }
    return render(request, "billing/invoice_report.html", context)


@login_required
def invoice_report_pdf(request):
    """
    Task 45: Provide an option to download report as a PDF using xhtml2pdf.
    Supports both Admin (all invoices) and Distributor (own invoices).
    """
    is_admin = request.user.is_staff or request.user.is_superuser
    distributor = request.user
    form = InvoiceReportFilterForm(request.GET or None, distributor=distributor, is_admin=is_admin)

    if is_admin:
        invoices_qs = (
            Invoice.objects.all()
            .select_related("customer", "distributor")
            .prefetch_related("items__product")
            .order_by("-invoice_date")
        )
    else:
        invoices_qs = (
            Invoice.objects.filter(distributor=distributor)
            .select_related("customer")
            .prefetch_related("items__product")
            .order_by("-invoice_date")
        )

    start_date = None
    end_date = None
    selected_status = ""
    selected_customer = None

    if request.GET and not form.is_valid():
        error_msg = form.non_field_errors()[0] if form.non_field_errors() else "Invalid date filter selection."
        messages.error(request, error_msg)
        return redirect("invoice_report")

    if form.is_valid():
        start_date = form.cleaned_data.get("start_date")
        end_date = form.cleaned_data.get("end_date")
        selected_status = form.cleaned_data.get("status")
        selected_customer = form.cleaned_data.get("customer")

        if start_date:
            invoices_qs = invoices_qs.filter(invoice_date__date__gte=start_date)
        if end_date:
            invoices_qs = invoices_qs.filter(invoice_date__date__lte=end_date)
        if selected_status:
            invoices_qs = invoices_qs.filter(status__iexact=selected_status)
        if selected_customer:
            invoices_qs = invoices_qs.filter(customer=selected_customer)

    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
    not_cancelled = ~Q(status__iexact="Cancelled")
    agg = invoices_qs.aggregate(
        total_invoices_count=Count("id"),
        total_amount_collected=Coalesce(Sum("total_amount", filter=not_cancelled), zero_dec),
        total_tax_collected=Coalesce(Sum("gst_amount", filter=not_cancelled), zero_dec),
        total_subtotal_amount=Coalesce(Sum("subtotal", filter=not_cancelled), zero_dec),
        paid_count=Count("id", filter=Q(status__iexact="Paid")),
        pending_count=Count("id", filter=Q(status__iexact="Pending")),
        cancelled_count=Count("id", filter=Q(status__iexact="Cancelled")),
    )

    invoices_list = list(invoices_qs)
    true_paid_pdf = Decimal("0.00")
    true_pending_pdf = Decimal("0.00")
    for inv in invoices_list:
        item_list = list(inv.items.all())
        inv.product_count = len(item_list)
        inv.product_summary = ", ".join(f"{item.product.name} (x{item.quantity})" for item in item_list)
        if (inv.status or "").lower() != "cancelled":
            true_paid_pdf += inv.effective_amount_paid
            true_pending_pdf += inv.balance_due

    context = {
        "distributor": distributor,
        "invoices": invoices_list,
        "start_date": start_date,
        "end_date": end_date,
        "selected_status": selected_status,
        "selected_customer": selected_customer,
        "total_invoices_count": agg["total_invoices_count"],
        "total_amount_collected": agg["total_amount_collected"],
        "total_tax_collected": agg["total_tax_collected"],
        "total_subtotal_amount": agg["total_subtotal_amount"],
        "paid_count": agg["paid_count"],
        "pending_count": agg["pending_count"],
        "cancelled_count": agg["cancelled_count"],
        "paid_amount": true_paid_pdf,
        "pending_amount": true_pending_pdf,
        "generated_at": timezone.now(),
    }

    pdf = render_to_pdf("billing/invoice_report_pdf.html", context)
    if pdf is None:
        messages.error(request, "Failed to generate report PDF. Please try again.")
        return redirect("invoice_report")

    filename = f"Invoice_Report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf["Content-Disposition"] = f'attachment; filename="{filename}"'
    return pdf


def get_invoice_qr_payload(invoice):
    """
    Task 58: Fetch invoice data from the saved Invoice model in the database
    (invoice ID, invoice number, customer name, total amount, and date)
    and build the structured QR payload string.
    """
    saved_inv = (
        Invoice.objects.select_related("customer").filter(pk=invoice.pk).first()
        if getattr(invoice, "pk", None)
        else None
    ) or invoice

    summary = saved_inv.get_invoice_summary_data()
    product_count = saved_inv.items.count() if getattr(saved_inv, "pk", None) else 0

    return (
        f"Invoice ID: {summary['invoice_id']}\n"
        f"Invoice: {summary['invoice_number']}\n"
        f"Customer: {summary['customer_name']}\n"
        f"Products: {product_count}\n"
        f"Total: ₹{summary['total_amount']}\n"
        f"Date: {summary['date']}"
    )


def generate_invoice_qr(invoice):
    """
    Task 58: Fetch saved invoice data from the model and generate a QR code
    encoding invoice ID, customer name, total amount, and date.
    """
    qr_data = get_invoice_qr_payload(invoice)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )

    qr.add_data(qr_data)
    qr.make(fit=True)

    qr_image = qr.make_image(
        fill_color="black",
        back_color="white"
    ).convert("RGB")

    buffer = BytesIO()
    qr_image.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")

    return qr_base64


def generate_upi_qr(invoice):
    """
    Generate dynamic UPI Payment QR code (Scan & Pay) compatible with
    Google Pay, PhonePe, Paytm, BHIM, and any UPI application.
    Uses configured DistributorProfile.upi_id if set; otherwise falls back to phone@upi.
    """
    distributor = invoice.distributor
    dist_profile = getattr(distributor, "distributor_profile", None)
    configured_upi = (dist_profile.upi_id or "").strip() if dist_profile else ""
    phone = dist_profile.phone if dist_profile and dist_profile.phone else "9876543210"

    upi_id = configured_upi if configured_upi else f"{phone}@upi"
    payee_name = (
        (dist_profile.business_name or "").strip() if dist_profile else ""
    ) or distributor.get_full_name() or distributor.username
    note = f"Bill {invoice.invoice_number}"
    payable_amt = (
        invoice.balance_due
        if (invoice.status or "").lower() == "partial" and invoice.balance_due > Decimal("0.00")
        else invoice.total_amount
    )
    amount = f"{payable_amt:.2f}"

    upi_uri = (
        f"upi://pay?pa={quote(upi_id, safe='@._-')}"
        f"&pn={quote(payee_name)}"
        f"&am={amount}"
        f"&cu=INR"
        f"&tn={quote(note)}"
    )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(upi_uri)
    qr.make(fit=True)

    qr_image = qr.make_image(
        fill_color="#0f766e",
        back_color="white"
    )

    buffer = BytesIO()
    qr_image.save(buffer, format="PNG")
    upi_qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return upi_qr_base64, upi_uri, upi_id


def fetch_complete_invoice_details(pk, distributor=None):
    """
    Task 63: Fetch complete invoice details (ID, customer name, total, date, tax split,
    discount, line items, QR codes, and WhatsApp share URL) for preview and PDF export.
    """
    qs = Invoice.objects.select_related(
        "customer",
        "distributor",
        "distributor__distributor_profile"
    ).prefetch_related("items__product", "payments")

    if distributor is not None:
        invoice = get_object_or_404(qs, pk=pk, distributor=distributor)
    else:
        invoice = get_object_or_404(qs, pk=pk)

    items = list(invoice.items.all())
    payments = list(invoice.payments.all())
    summary = invoice.get_invoice_summary_data()
    qr_code = generate_invoice_qr(invoice)
    qr_payload = get_invoice_qr_payload(invoice)
    upi_qr_code, upi_uri, upi_id = generate_upi_qr(invoice)

    dist_profile = getattr(invoice.distributor, "distributor_profile", None)

    # Compute tax split dynamically if legacy invoice has zeroed split columns
    cgst_amount = invoice.cgst_amount
    sgst_amount = invoice.sgst_amount
    igst_amount = invoice.igst_amount
    is_interstate = invoice.is_interstate
    if invoice.gst_amount > 0 and cgst_amount == 0 and sgst_amount == 0 and igst_amount == 0:
        is_interstate, cgst_amount, sgst_amount, igst_amount = _compute_tax_split(
            invoice.distributor, invoice.customer, invoice.gst_amount
        )

    # Build WhatsApp Share & Payment Reminder URLs
    seller_name = (
        (dist_profile.business_name or "").strip() if dist_profile else ""
    ) or invoice.distributor.get_full_name() or invoice.distributor.username
    place_of_supply = (
        (invoice.customer.state or "").strip()
        or ((dist_profile.state or "").strip() if dist_profile else "")
        or "N/A"
    )
    amount_paid = invoice.effective_amount_paid
    balance_due = invoice.balance_due
    amount_in_words = amount_to_indian_words(invoice.total_amount)
    hsn_summary = build_hsn_tax_summary(items, is_interstate=is_interstate)

    wa_text = (
        f"Hello {invoice.customer.name},\n"
        f"Invoice *{invoice.invoice_number}* from *{seller_name}*:\n"
        f"Date: {summary['date']}\n"
        f"Total Amount: Rs. {invoice.total_amount:.2f}\n"
        f"Paid: Rs. {amount_paid:.2f} | Balance Due: Rs. {balance_due:.2f}\n"
        f"Status: {invoice.status}\n"
        f"UPI ID: {upi_id}"
    )
    due_line = f"Due Date: {invoice.due_date.strftime('%d %b %Y')}\n" if invoice.due_date else ""
    wa_reminder_text = (
        f"Namaste {invoice.customer.name},\n"
        f"Gentle payment reminder from *{seller_name}*:\n"
        f"Invoice: *{invoice.invoice_number}* (Date: {summary['date']})\n"
        f"{due_line}"
        f"Pending Balance: *Rs. {balance_due:.2f}*\n"
        f"Pay easily via UPI ID: {upi_id}\n"
        f"Thank you!"
    )
    clean_phone = re.sub(r"\D", "", invoice.customer.phone or "")
    wa_phone = f"91{clean_phone}" if len(clean_phone) == 10 else clean_phone
    whatsapp_share_url = f"https://wa.me/{wa_phone}?text={quote(wa_text)}"
    whatsapp_reminder_url = f"https://wa.me/{wa_phone}?text={quote(wa_reminder_text)}"

    return {
        "invoice": invoice,
        "invoice_id": summary["invoice_id"],
        "invoice_number": summary["invoice_number"],
        "customer_name": summary["customer_name"],
        "total_amount": summary["total_amount"],
        "invoice_date": summary["date"],
        "items": items,
        "payments": payments,
        "amount_paid": amount_paid,
        "balance_due": balance_due,
        "is_overdue": invoice.is_overdue,
        "seller_name": seller_name,
        "place_of_supply": place_of_supply,
        "amount_in_words": amount_in_words,
        "hsn_summary": hsn_summary,
        "today_iso": timezone.localdate().isoformat(),
        "qr_code": qr_code,
        "qr_payload": qr_payload,
        "upi_qr_code": upi_qr_code,
        "upi_uri": upi_uri,
        "upi_id": upi_id,
        "distributor_profile": dist_profile,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "igst_amount": igst_amount,
        "is_interstate": is_interstate,
        "whatsapp_share_url": whatsapp_share_url,
        "whatsapp_reminder_url": whatsapp_reminder_url,
    }


@login_required
def invoice_detail(request, pk):
    """
    Task 61: Detailed / Preview Invoice page for each invoice that includes
    complete invoice details and dynamically generated verification & UPI payment QR codes.
    """
    dist_filter = None if (request.user.is_staff or request.user.is_superuser) else request.user
    context = fetch_complete_invoice_details(pk, distributor=dist_filter)
    context["is_preview"] = True
    return render(
        request,
        "billing/invoice_detail.html",
        context
    )


@login_required
def invoice_preview(request, pk):
    """
    Task 61: Dedicated 'Preview Invoice' page endpoint (/invoices/<pk>/preview/)
    displaying full invoice details and QR code.
    """
    return invoice_detail(request, pk)


@login_required
def invoice_toggle_status(request, pk):
    """
    Toggle or update invoice payment status ('Paid' <-> 'Pending') via POST.
    Prevents toggling Cancelled invoices and protects against Open Redirects.
    """
    if request.user.is_staff or request.user.is_superuser:
        invoice = get_object_or_404(Invoice, pk=pk)
    else:
        invoice = get_object_or_404(Invoice, pk=pk, distributor=request.user)

    if request.method == "POST":
        if (invoice.status or "").lower() == "cancelled":
            messages.error(request, f"Invoice {invoice.invoice_number} is cancelled and its payment status cannot be changed.")
            return redirect("invoice_detail", pk=invoice.pk)

        requested_status = request.POST.get("status", "").strip()
        if requested_status in ("Paid", "Pending"):
            invoice.status = requested_status
        else:
            invoice.status = "Paid" if (invoice.status or "").lower() != "paid" else "Pending"

        requested_mode = request.POST.get("payment_mode", "").strip()
        with transaction.atomic():
            if invoice.status == "Paid":
                invoice.paid_at = timezone.now()
                if requested_mode in PAID_PAYMENT_MODES:
                    invoice.payment_mode = requested_mode
                elif invoice.payment_mode not in PAID_PAYMENT_MODES:
                    invoice.payment_mode = "Cash"
                remaining = invoice.balance_due
                if remaining > Decimal("0.00"):
                    InvoicePayment.objects.create(
                        invoice=invoice,
                        distributor=invoice.distributor,
                        amount=remaining,
                        payment_mode=invoice.payment_mode,
                        payment_date=timezone.localdate(),
                        notes="Marked fully paid",
                    )
                invoice.amount_paid = invoice.total_amount
            else:
                invoice.payments.all().delete()
                invoice.paid_at = None
                invoice.payment_mode = "Unpaid"
                invoice.amount_paid = Decimal("0.00")

            invoice.save(update_fields=["status", "payment_mode", "paid_at", "amount_paid", "updated_at"])
        messages.success(request, f"Invoice {invoice.invoice_number} marked as {invoice.status}.")

        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)

    return redirect("invoice_detail", pk=invoice.pk)


@login_required
def invoice_cancel(request, pk):
    """
    Cancel an invoice via POST and atomically restore all billed product stock.
    """
    if request.user.is_staff or request.user.is_superuser:
        invoice = get_object_or_404(Invoice, pk=pk)
    else:
        invoice = get_object_or_404(Invoice, pk=pk, distributor=request.user)

    if request.method != "POST":
        messages.error(request, "Invalid request method for cancelling an invoice.")
        return redirect("invoice_detail", pk=invoice.pk)

    if (invoice.status or "").lower() == "cancelled":
        messages.info(request, f"Invoice {invoice.invoice_number} is already cancelled.")
        return redirect("invoice_detail", pk=invoice.pk)

    with transaction.atomic():
        items = list(invoice.items.select_related("product").all())
        for item in items:
            product = Product.objects.select_for_update().get(pk=item.product_id)
            old_stock = product.stock
            product.stock += item.quantity
            product.save(update_fields=["stock", "updated_at"])
            StockMovement.objects.create(
                product=product,
                distributor=invoice.distributor,
                movement_type="CANCEL_RESTORE",
                quantity_change=item.quantity,
                stock_before=old_stock,
                stock_after=product.stock,
                reference=invoice.invoice_number,
                notes="Stock restored on invoice cancellation",
            )

        invoice.status = "Cancelled"
        invoice.payment_mode = "Unpaid"
        invoice.paid_at = None
        invoice.cancelled_at = timezone.now()
        invoice.save(update_fields=["status", "payment_mode", "paid_at", "cancelled_at", "updated_at"])

    messages.success(request, f"Invoice {invoice.invoice_number} cancelled and product stock restored.")
    return redirect("invoice_detail", pk=invoice.pk)


@login_required
def invoice_send_email(request, pk):
    """
    Email the invoice PDF attachment directly to the customer (or specified recipient).
    """
    dist_filter = None if (request.user.is_staff or request.user.is_superuser) else request.user
    context = fetch_complete_invoice_details(pk, distributor=dist_filter)
    invoice = context["invoice"]

    if request.method != "POST":
        return redirect("invoice_detail", pk=invoice.pk)

    recipient = (request.POST.get("recipient_email") or invoice.customer.email or "").strip().lower()
    if not recipient:
        messages.error(request, "Customer does not have an email address on file. Please provide an email address.")
        return redirect("invoice_detail", pk=invoice.pk)

    try:
        validate_email(recipient)
    except ValidationError:
        messages.error(request, "Please enter a valid recipient email address.")
        return redirect("invoice_detail", pk=invoice.pk)

    pdf_bytes = generate_invoice_pdf_bytes("billing/invoice_pdf.html", context)
    if pdf_bytes is None:
        messages.error(request, "Failed to generate PDF attachment for email.")
        return redirect("invoice_detail", pk=invoice.pk)

    prefix = getattr(settings, "EMAIL_SUBJECT_PREFIX", "[Advance Billing] ")
    subject = f"{prefix}Tax Invoice {invoice.invoice_number}"
    body = (
        f"Dear {invoice.customer.name},\n\n"
        f"Please find attached your tax invoice {invoice.invoice_number}.\n"
        f"Total Amount: Rs. {invoice.total_amount:.2f}\n"
        f"Payment Status: {invoice.status}\n"
        f"UPI Payment ID: {context['upi_id']}\n\n"
        f"Thank you for your business!"
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@advancebilling.local"),
        to=[recipient],
    )
    msg.attach(f"{invoice.invoice_number}.pdf", pdf_bytes, "application/pdf")

    try:
        msg.send(fail_silently=False)
        messages.success(request, f"Invoice {invoice.invoice_number} emailed successfully to {recipient}.")
    except Exception as exc:
        messages.error(request, f"Could not send email: {exc}")

    return redirect("invoice_detail", pk=invoice.pk)


@login_required
def invoice_pdf(request, pk):
    """
    Generate and download invoice as PDF with embedded dynamic verification & UPI payment QR code.
    Only the logged-in distributor (or admin) can access the invoice.
    """
    dist_filter = None if (request.user.is_staff or request.user.is_superuser) else request.user
    context = fetch_complete_invoice_details(pk, distributor=dist_filter)
    invoice = context["invoice"]

    pdf = render_to_pdf(
        "billing/invoice_pdf.html",
        context
    )

    if pdf is None:
        messages.error(
            request,
            "PDF generation failed. Please try again."
        )
        return redirect("invoice_detail", pk=invoice.pk)

    pdf["Content-Disposition"] = (
        f'attachment; filename="{invoice.invoice_number}.pdf"'
    )

    return pdf


# ==============================================================================
# CUSTOMER REGISTRATION API FOR DISTRIBUTOR (SECURED)
# ==============================================================================

@csrf_exempt
def customer_register_api(request):
    """
    REST API endpoint for registering a new Customer for an authenticated Distributor.
    Requires either active Django session authentication or valid HTTP Basic Auth.
    """
    if request.method != "POST":
        return JsonResponse({
            "status": "error",
            "message": "Method not allowed. Only POST requests are supported."
        }, status=405)

    # Strictly authenticate caller (no unauthenticated distributor_id bypass)
    distributor = _authenticate_api_user(request)
    if not distributor:
        return JsonResponse({
            "status": "error",
            "message": "Authentication required. Please login or provide valid distributor credentials."
        }, status=401)

    data = {}
    if request.content_type == "application/json" and request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({
                "status": "error",
                "message": "Malformed JSON payload in request body."
            }, status=400)
    else:
        data = request.POST.dict()

    # Only Admins may assign a customer to another distributor via distributor_id
    if distributor.is_staff or distributor.is_superuser:
        dist_id = data.get("distributor_id")
        if dist_id and str(dist_id).isdigit():
            assigned = User.objects.filter(pk=int(dist_id)).first()
            if assigned:
                distributor = assigned

    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    gstin = str(data.get("gstin", "")).strip().upper()
    address = str(data.get("address", "")).strip()
    city = str(data.get("city", "")).strip()
    state = str(data.get("state", "")).strip()
    pincode = str(data.get("pincode", "")).strip()

    raw_active = data.get("is_active", True)
    if isinstance(raw_active, str):
        is_active = raw_active.lower() not in ["false", "0", "off", "no"]
    elif isinstance(raw_active, bool):
        is_active = raw_active
    else:
        is_active = bool(raw_active)

    errors = {}

    if not name:
        errors["name"] = "Full Name is required."
    elif len(name) < 3:
        errors["name"] = "Name must contain at least 3 characters."
    elif len(name) > 100:
        errors["name"] = "Name cannot exceed 100 characters."

    if not phone:
        errors["phone"] = "Phone number is required."
    elif not phone.isdigit() or len(phone) != 10:
        errors["phone"] = "Please enter a valid 10-digit phone number."

    if email:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Please enter a valid email address."

    if gstin and not GSTIN_REGEX.match(gstin):
        errors["gstin"] = "Please enter a valid 15-character alphanumeric GSTIN."

    if not city:
        errors["city"] = "City is required."
    elif len(city) > 50:
        errors["city"] = "City cannot exceed 50 characters."

    if not state:
        errors["state"] = "State is required."
    elif len(state) > 50:
        errors["state"] = "State cannot exceed 50 characters."

    if not pincode:
        errors["pincode"] = "Pincode is required."
    elif not pincode.isdigit() or len(pincode) < 5 or len(pincode) > 6:
        errors["pincode"] = "Please enter a valid 5 or 6 digit postal pincode."

    if errors:
        return JsonResponse({
            "status": "error",
            "message": "Validation failed.",
            "errors": errors
        }, status=400)

    try:
        customer = Customer.objects.create(
            distributor=distributor,
            name=name,
            email=email if email else None,
            phone=phone,
            gstin=gstin,
            address=address if address else None,
            city=city,
            state=state,
            pincode=pincode,
            is_active=is_active
        )

        return JsonResponse({
            "status": "success",
            "message": "Customer registered successfully.",
            "data": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "phone": customer.phone,
                "gstin": customer.gstin,
                "address": customer.address,
                "city": customer.city,
                "state": customer.state,
                "pincode": customer.pincode,
                "is_active": customer.is_active,
                "distributor_id": distributor.id,
                "distributor_username": distributor.username,
                "created_at": customer.created_at.isoformat(),
            }
        }, status=201)

    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": f"Server error registering customer: {str(e)}"
        }, status=500)


# ==============================================================================
# PRODUCT CRUD REST API ENDPOINTS (SECURED)
# ==============================================================================

@csrf_exempt
def product_api_list_create(request):
    """
    REST API endpoint for Product CRUD (List & Create).
    Requires authenticated session or HTTP Basic Auth (no distributor_id bypass).
    """
    distributor = _authenticate_api_user(request)
    if not distributor:
        return JsonResponse({"status": "error", "message": "Authentication required."}, status=401)

    if request.method == "GET":
        if distributor.is_staff or distributor.is_superuser:
            products = Product.objects.all().order_by("-created_at")
        else:
            products = Product.objects.filter(distributor=distributor).order_by("-created_at")

        data = [{
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "hsn_code": p.hsn_code,
            "category": p.category,
            "price": str(p.price),
            "stock": p.stock,
            "gst_rate": str(p.gst_rate),
            "description": p.description,
            "created_at": p.created_at.isoformat(),
        } for p in products]
        return JsonResponse({"status": "success", "count": len(data), "data": data}, status=200)

    elif request.method == "POST":
        data = {}
        if request.content_type == "application/json" and request.body:
            try:
                data = json.loads(request.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse({"status": "error", "message": "Malformed JSON payload."}, status=400)
        else:
            data = request.POST.dict()

        name = str(data.get("name", "")).strip()
        sku = str(data.get("sku", "")).strip()
        hsn_code = str(data.get("hsn_code", "")).strip()
        category = str(data.get("category", "")).strip()
        price = data.get("price")
        stock = data.get("stock")
        gst_rate = data.get("gst_rate")
        description = str(data.get("description", "")).strip()

        errors = {}
        if not name:
            errors["name"] = "Product name is required."
        elif len(name) < 2:
            errors["name"] = "Product name must contain at least 2 characters."

        if not category:
            errors["category"] = "Category is required."

        if price is None or price == "":
            errors["price"] = "Price is required."
        else:
            try:
                price_val = Decimal(str(price))
                if price_val <= 0:
                    errors["price"] = "Price must be greater than 0."
            except (InvalidOperation, ValueError):
                errors["price"] = "Invalid price format."

        if stock is None or stock == "":
            errors["stock"] = "Stock is required."
        else:
            try:
                stock_val = int(stock)
                if stock_val < 0:
                    errors["stock"] = "Stock cannot be negative."
            except ValueError:
                errors["stock"] = "Stock must be an integer."

        if gst_rate is None or gst_rate == "":
            errors["gst_rate"] = "GST rate is required."
        else:
            try:
                gst_val = Decimal(str(gst_rate))
                if gst_val < 0 or gst_val > 100:
                    errors["gst_rate"] = "GST rate must be between 0 and 100."
            except (InvalidOperation, ValueError):
                errors["gst_rate"] = "Invalid GST rate format."

        if errors:
            return JsonResponse({"status": "error", "message": "Validation failed.", "errors": errors}, status=400)

        product = Product.objects.create(
            distributor=distributor,
            name=name,
            sku=sku,
            hsn_code=hsn_code,
            category=category,
            price=price_val,
            stock=stock_val,
            gst_rate=gst_val,
            description=description
        )
        return JsonResponse({
            "status": "success",
            "message": "Product created successfully.",
            "data": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "hsn_code": product.hsn_code,
                "category": product.category,
                "price": str(product.price),
                "stock": product.stock,
                "gst_rate": str(product.gst_rate),
                "description": product.description,
            }
        }, status=201)

    return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)


@csrf_exempt
def product_api_detail(request, pk):
    """
    REST API endpoint for Product CRUD (Read, Update, Delete single item).
    Handles ProtectedError cleanly with 409 Conflict instead of 500 crash.
    """
    distributor = _authenticate_api_user(request)
    if not distributor:
        return JsonResponse({"status": "error", "message": "Authentication required."}, status=401)

    if distributor.is_staff or distributor.is_superuser:
        product = Product.objects.filter(pk=pk).first()
    else:
        product = Product.objects.filter(pk=pk, distributor=distributor).first()

    if not product:
        return JsonResponse({"status": "error", "message": "Product not found or access denied."}, status=404)

    if request.method == "GET":
        return JsonResponse({
            "status": "success",
            "data": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "hsn_code": product.hsn_code,
                "category": product.category,
                "price": str(product.price),
                "stock": product.stock,
                "gst_rate": str(product.gst_rate),
                "description": product.description,
                "created_at": product.created_at.isoformat(),
            }
        }, status=200)

    elif request.method in ["PUT", "PATCH", "POST"]:
        data = {}
        if request.content_type == "application/json" and request.body:
            try:
                data = json.loads(request.body.decode("utf-8"))
            except Exception:
                return JsonResponse({"status": "error", "message": "Malformed JSON payload."}, status=400)
        else:
            data = request.POST.dict()

        if "name" in data:
            name = str(data["name"]).strip()
            if len(name) < 2:
                return JsonResponse({"status": "error", "errors": {"name": "Min length 2 chars."}}, status=400)
            product.name = name

        if "sku" in data:
            product.sku = str(data["sku"]).strip()

        if "hsn_code" in data:
            product.hsn_code = str(data["hsn_code"]).strip()

        if "category" in data:
            product.category = str(data["category"]).strip()

        if "price" in data:
            try:
                p_val = Decimal(str(data["price"]))
                if p_val <= 0:
                    return JsonResponse({"status": "error", "errors": {"price": "Must be > 0."}}, status=400)
                product.price = p_val
            except Exception:
                return JsonResponse({"status": "error", "errors": {"price": "Invalid price."}}, status=400)

        if "stock" in data:
            try:
                s_val = int(data["stock"])
                if s_val < 0:
                    return JsonResponse({"status": "error", "errors": {"stock": "Cannot be negative."}}, status=400)
                product.stock = s_val
            except Exception:
                return JsonResponse({"status": "error", "errors": {"stock": "Must be integer."}}, status=400)

        if "gst_rate" in data:
            try:
                g_val = Decimal(str(data["gst_rate"]))
                if g_val < 0 or g_val > 100:
                    return JsonResponse({"status": "error", "errors": {"gst_rate": "Must be 0-100."}}, status=400)
                product.gst_rate = g_val
            except Exception:
                return JsonResponse({"status": "error", "errors": {"gst_rate": "Invalid GST rate."}}, status=400)

        if "description" in data:
            product.description = str(data["description"]).strip()

        product.save()
        return JsonResponse({
            "status": "success",
            "message": "Product updated successfully.",
            "data": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "hsn_code": product.hsn_code,
                "category": product.category,
                "price": str(product.price),
                "stock": product.stock,
                "gst_rate": str(product.gst_rate),
                "description": product.description,
            }
        }, status=200)

    elif request.method == "DELETE":
        p_name = product.name
        try:
            product.delete()
            return JsonResponse({"status": "success", "message": f"Product '{p_name}' deleted successfully."}, status=200)
        except ProtectedError:
            return JsonResponse({
                "status": "error",
                "message": f"Cannot delete product '{p_name}' because it is linked to existing invoices."
            }, status=409)

    return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)


@login_required
def qr_decoder_view(request):
    """
    Task 47 & 48: Interactive frontend view for uploading QR code images and decoding them.
    Supports Admin (match any invoice) and Distributor (match own invoices only).
    """
    result = None
    matched_invoice = None

    if request.method == "POST":
        uploaded_image = (
            request.FILES.get("qr_image") or
            request.FILES.get("file") or
            request.FILES.get("image")
        )
        base64_data = request.POST.get("image_base64", "").strip()

        if not uploaded_image and not base64_data:
            messages.error(request, "Please select or upload a QR code image to decode.")
            return render(request, "billing/qr_decoder.html", {
                "result": None,
                "matched_invoice": None,
            })

        try:
            if uploaded_image:
                if uploaded_image.size == 0:
                    messages.error(request, "The uploaded file is empty (0 bytes). Please select a valid QR code image.")
                    return render(request, "billing/qr_decoder.html", {
                        "result": {"success": False, "error": "The uploaded file is empty (0 bytes). Please select a valid QR code image."},
                        "matched_invoice": None,
                    })
                if uploaded_image.size > 10 * 1024 * 1024:
                    messages.error(request, "Uploaded image file size must not exceed 10MB.")
                    return render(request, "billing/qr_decoder.html", {
                        "result": {"success": False, "error": "Uploaded image file size must not exceed 10MB."},
                        "matched_invoice": None,
                    })
                type_error = _validate_uploaded_qr_file(uploaded_image)
                if type_error:
                    messages.error(request, type_error)
                    return render(request, "billing/qr_decoder.html", {
                        "result": {"success": False, "error": type_error},
                        "matched_invoice": None,
                    })
                decode_res = decode_qr_image(uploaded_image)
            else:
                if "," in base64_data:
                    base64_data = base64_data.split(",", 1)[1]
                img_bytes = base64.b64decode(base64_data)
                decode_res = decode_qr_image(BytesIO(img_bytes))

            result = decode_res
            if decode_res.get("success"):
                inv_data = decode_res.get("parsed", {}).get("invoice_data", {})
                inv_num = inv_data.get("invoice_number") or inv_data.get("invoice")
                if inv_num:
                    qs = Invoice.objects.filter(invoice_number__iexact=inv_num)
                    if not (request.user.is_staff or request.user.is_superuser):
                        qs = qs.filter(distributor=request.user)
                    matched_invoice = qs.select_related("customer").prefetch_related("items__product").first()

                messages.success(request, f"QR code decoded successfully ({decode_res.get('code_type', 'QRCODE')})!")
            else:
                messages.error(request, decode_res.get("error", "No QR code could be detected in this image."))

        except Exception as e:
            messages.error(request, f"Error processing uploaded image: {str(e)}")

    return render(request, "billing/qr_decoder.html", {
        "result": result,
        "matched_invoice": matched_invoice,
    })


@csrf_exempt
def qr_decoder_api(request):
    """
    Task 47 & 48: Dedicated REST API endpoint for decoding QR codes from uploaded images.
    Database invoice lookup (`matched_invoice`) is strictly gated behind authentication
    to prevent unauthenticated data leakage.
    """
    if request.method != "POST":
        return JsonResponse({
            "status": "error",
            "message": "Method not allowed. Use POST to upload an image."
        }, status=405)

    uploaded_file = (
        request.FILES.get("file") or
        request.FILES.get("image") or
        request.FILES.get("qr_image") or
        request.FILES.get("qr_code")
    )

    image_source = None

    if uploaded_file:
        if uploaded_file.size == 0:
            return JsonResponse({
                "status": "error",
                "message": "The uploaded file is empty (0 bytes). Please select a valid QR code image.",
                "error_code": "EMPTY_FILE"
            }, status=400)
        if uploaded_file.size > 10 * 1024 * 1024:
            return JsonResponse({
                "status": "error",
                "message": "File size exceeds 10MB limit."
            }, status=400)
        type_error = _validate_uploaded_qr_file(uploaded_file)
        if type_error:
            return JsonResponse({
                "status": "error",
                "message": type_error,
                "error_code": "UNSUPPORTED_FILE_TYPE"
            }, status=422)
        image_source = uploaded_file
    elif request.content_type == "application/json" and request.body:
        try:
            body_json = json.loads(request.body.decode("utf-8"))
            b64_str = body_json.get("image_base64") or body_json.get("image") or body_json.get("data")
            if b64_str:
                if "," in b64_str:
                    b64_str = b64_str.split(",", 1)[1]
                image_bytes = base64.b64decode(b64_str)
                image_source = BytesIO(image_bytes)
        except Exception:
            return JsonResponse({
                "status": "error",
                "message": "Invalid JSON or corrupted base64 image data."
            }, status=400)
    elif request.POST.get("image_base64"):
        try:
            b64_str = request.POST.get("image_base64")
            if "," in b64_str:
                b64_str = b64_str.split(",", 1)[1]
            image_bytes = base64.b64decode(b64_str)
            image_source = BytesIO(image_bytes)
        except Exception:
            return JsonResponse({
                "status": "error",
                "message": "Corrupted base64 image data in POST payload."
            }, status=400)

    if not image_source:
        return JsonResponse({
            "status": "error",
            "message": "No image file provided. Please upload an image file using field 'file', 'image', or 'qr_image'."
        }, status=400)

    decode_res = decode_qr_image(image_source)

    if not decode_res.get("success"):
        return JsonResponse({
            "status": "error",
            "message": decode_res.get("error", "No QR code detected.")
        }, status=422)

    # Only query DB for matched invoice if caller is authenticated
    matched_data = None
    caller = _authenticate_api_user(request)
    if caller:
        inv_data = decode_res.get("parsed", {}).get("invoice_data", {})
        inv_num = inv_data.get("invoice_number") or inv_data.get("invoice")
        if inv_num:
            qs = Invoice.objects.filter(invoice_number__iexact=inv_num)
            if not (caller.is_staff or caller.is_superuser):
                qs = qs.filter(distributor=caller)
            inv_match = qs.select_related("customer").first()
            if inv_match:
                matched_data = {
                    "id": inv_match.id,
                    "invoice_number": inv_match.invoice_number,
                    "customer_name": inv_match.customer.name,
                    "total_amount": str(inv_match.total_amount),
                    "status": inv_match.status,
                    "url": f"/invoices/{inv_match.id}/",
                }

    return JsonResponse({
        "status": "success",
        "message": "QR code decoded successfully.",
        "data": {
            "raw_text": decode_res.get("raw_data"),
            "code_type": decode_res.get("code_type"),
            "parsed": decode_res.get("parsed"),
            "matched_invoice": matched_data
        }
    }, status=200)


# ==============================================================================
# PHASE 2: PARTIAL PAYMENTS & CUSTOMER KHATA (UDHAR LEDGER)
# ==============================================================================

@login_required
def invoice_add_payment(request, pk):
    """Record a full or partial payment against an invoice and recalculate status."""
    if request.user.is_staff or request.user.is_superuser:
        invoice = get_object_or_404(Invoice, pk=pk)
    else:
        invoice = get_object_or_404(Invoice, pk=pk, distributor=request.user)

    if request.method != "POST":
        return redirect("invoice_detail", pk=invoice.pk)

    if (invoice.status or "").lower() == "cancelled":
        messages.error(request, "Cannot record payments for a cancelled invoice.")
        return redirect("invoice_detail", pk=invoice.pk)

    raw_amount = (request.POST.get("amount") or "").strip()
    payment_mode = (request.POST.get("payment_mode") or "Cash").strip()
    reference_number = (request.POST.get("reference_number") or "").strip()[:100]
    raw_date = (request.POST.get("payment_date") or "").strip()
    notes = (request.POST.get("notes") or "").strip()[:255]

    if payment_mode not in PAID_PAYMENT_MODES:
        payment_mode = "Cash"

    try:
        amount = Decimal(raw_amount).quantize(Decimal("0.01"))
        if amount <= Decimal("0.00"):
            raise ValueError("Payment amount must be greater than zero.")
    except (InvalidOperation, ValueError):
        messages.error(request, "Please enter a valid payment amount greater than 0.")
        return redirect("invoice_detail", pk=invoice.pk)

    payment_date = timezone.localdate()
    if raw_date:
        try:
            payment_date = date.fromisoformat(raw_date)
        except ValueError:
            messages.error(request, "Please select a valid payment date.")
            return redirect("invoice_detail", pk=invoice.pk)

    with transaction.atomic():
        inv_locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        remaining = inv_locked.balance_due
        if remaining <= Decimal("0.00"):
            messages.info(request, f"Invoice {inv_locked.invoice_number} is already fully paid.")
            return redirect("invoice_detail", pk=inv_locked.pk)
        if amount > remaining:
            messages.error(
                request,
                f"Payment amount (Rs. {amount:.2f}) exceeds remaining balance due (Rs. {remaining:.2f})."
            )
            return redirect("invoice_detail", pk=inv_locked.pk)

        InvoicePayment.objects.create(
            invoice=inv_locked,
            distributor=inv_locked.distributor,
            amount=amount,
            payment_mode=payment_mode,
            reference_number=reference_number,
            payment_date=payment_date,
            notes=notes,
        )
        inv_locked.recalculate_payment_status()

    messages.success(
        request,
        f"Recorded Rs. {amount:.2f} via {payment_mode}. Balance due: Rs. {inv_locked.balance_due:.2f}."
    )
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("invoice_detail", pk=invoice.pk)


@login_required
def invoice_delete_payment(request, pk, payment_id):
    """Remove a recorded payment entry and recalculate invoice balance/status."""
    if request.user.is_staff or request.user.is_superuser:
        invoice = get_object_or_404(Invoice, pk=pk)
    else:
        invoice = get_object_or_404(Invoice, pk=pk, distributor=request.user)

    if request.method == "POST":
        with transaction.atomic():
            inv_locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
            payment = get_object_or_404(InvoicePayment, pk=payment_id, invoice=inv_locked)
            removed_amt = payment.amount
            payment.delete()
            inv_locked.recalculate_payment_status()
        messages.success(request, f"Removed payment entry of Rs. {removed_amt:.2f}.")
    return redirect("invoice_detail", pk=invoice.pk)


@login_required
def customer_ledger(request, pk):
    """
    Customer Khata / Udhar Statement: shows total billed, total received,
    net outstanding balance, overdue bills, payment history, WhatsApp reminder,
    and downloadable CSV statement.
    """
    if request.user.is_staff or request.user.is_superuser:
        customer = get_object_or_404(Customer.objects.select_related("distributor"), pk=pk)
    else:
        customer = get_object_or_404(Customer, pk=pk, distributor=request.user)

    invoices = list(
        Invoice.objects.filter(customer=customer)
        .prefetch_related("payments")
        .order_by("-invoice_date", "-id")
    )
    payments = list(
        InvoicePayment.objects.filter(invoice__customer=customer)
        .select_related("invoice")
        .order_by("-payment_date", "-created_at", "-id")
    )

    total_billed = Decimal("0.00")
    total_paid = Decimal("0.00")
    total_due = Decimal("0.00")
    overdue_count = 0
    unpaid_invoices = []

    for inv in invoices:
        if (inv.status or "").lower() == "cancelled":
            continue
        total_billed += inv.total_amount or Decimal("0.00")
        total_paid += inv.effective_amount_paid
        due = inv.balance_due
        total_due += due
        if inv.is_overdue:
            overdue_count += 1
        if due > Decimal("0.00"):
            unpaid_invoices.append(inv)

    # Chronological ledger entries (Invoices as Debit, Payments as Credit)
    ledger_entries = []
    for inv in invoices:
        if (inv.status or "").lower() == "cancelled":
            continue
        inv_dt = timezone.localtime(inv.invoice_date or inv.created_at).date()
        ledger_entries.append({
            "date": inv_dt,
            "sort_ts": inv.created_at,
            "entry_type": "Invoice",
            "reference": inv.invoice_number,
            "invoice_pk": inv.pk,
            "details": f"Tax Invoice ({inv.status})",
            "debit": inv.total_amount,
            "credit": Decimal("0.00"),
        })
    for pay in payments:
        if (pay.invoice.status or "").lower() == "cancelled":
            continue
        ref_str = f"{pay.payment_mode}" + (f" • Ref: {pay.reference_number}" if pay.reference_number else "")
        ledger_entries.append({
            "date": pay.payment_date,
            "sort_ts": pay.created_at,
            "entry_type": "Payment",
            "reference": pay.invoice.invoice_number,
            "invoice_pk": pay.invoice_id,
            "details": ref_str + (f" ({pay.notes})" if pay.notes else ""),
            "debit": Decimal("0.00"),
            "credit": pay.amount,
        })

    # Sort ascending to compute running balance, then reverse for latest-first display
    ledger_entries.sort(key=lambda e: (e["date"], e["sort_ts"]))
    running = Decimal("0.00")
    for entry in ledger_entries:
        running = (running + entry["debit"] - entry["credit"]).quantize(Decimal("0.01"))
        entry["running_balance"] = running
    ledger_entries.reverse()

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", customer.name).strip("_") or "customer"
        response["Content-Disposition"] = f'attachment; filename="khata_{safe_name}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date", "Type", "Invoice #", "Details", "Debit (Billed)", "Credit (Paid)", "Running Balance"])
        for entry in reversed(ledger_entries):
            writer.writerow([
                entry["date"].strftime("%Y-%m-%d"),
                sanitize_csv_cell(entry["entry_type"]),
                sanitize_csv_cell(entry["reference"]),
                sanitize_csv_cell(entry["details"]),
                f"{entry['debit']:.2f}",
                f"{entry['credit']:.2f}",
                f"{entry['running_balance']:.2f}",
            ])
        return response

    dist_profile = getattr(customer.distributor, "distributor_profile", None)
    seller_name = (
        (dist_profile.business_name or "").strip() if dist_profile else ""
    ) or customer.distributor.get_full_name() or customer.distributor.username
    upi_id = (
        (dist_profile.upi_id or "").strip() if dist_profile else ""
    ) or (f"{dist_profile.phone}@upi" if dist_profile and dist_profile.phone else "")

    wa_msg = (
        f"Namaste {customer.name},\n"
        f"Account Statement Reminder from *{seller_name}*:\n"
        f"Total Billed: Rs. {total_billed:.2f}\n"
        f"Total Paid: Rs. {total_paid:.2f}\n"
        f"Pending Balance (Udhar): *Rs. {total_due:.2f}*\n"
        + (f"Pay via UPI: {upi_id}\n" if upi_id else "")
        + "Thank you for your business!"
    )
    clean_phone = re.sub(r"\D", "", customer.phone or "")
    wa_phone = f"91{clean_phone}" if len(clean_phone) == 10 else clean_phone
    whatsapp_reminder_url = f"https://wa.me/{wa_phone}?text={quote(wa_msg)}"

    return render(request, "billing/customer_ledger.html", {
        "customer": customer,
        "invoices": invoices,
        "unpaid_invoices": unpaid_invoices,
        "payments": payments,
        "ledger_entries": ledger_entries,
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_due": total_due,
        "overdue_count": overdue_count,
        "whatsapp_reminder_url": whatsapp_reminder_url,
        "today_iso": timezone.localdate().isoformat(),
    })


# ==============================================================================
# PHASE 3: CA-READY GSTR-1 EXPORTS & STOCK-IN / INVENTORY AUDIT LEDGER
# ==============================================================================

@login_required
def gstr1_export_csv(request):
    """
    Export CA-ready GSTR-1 CSV reports (B2B GSTIN invoices, B2C state-wise summary,
    or HSN-wise GST summary) excluding Cancelled invoices.
    """
    section = (request.GET.get("section") or "b2b").strip().lower()
    if section not in ("b2b", "b2c", "hsn"):
        section = "b2b"

    is_admin = request.user.is_staff or request.user.is_superuser
    qs = (
        Invoice.objects.exclude(status__iexact="Cancelled")
        .select_related("customer", "distributor", "distributor__distributor_profile")
        .prefetch_related("items__product")
        .order_by("invoice_date", "id")
    )
    if not is_admin:
        qs = qs.filter(distributor=request.user)

    raw_start = (request.GET.get("start_date") or "").strip()
    raw_end = (request.GET.get("end_date") or "").strip()
    if raw_start:
        try:
            qs = qs.filter(invoice_date__date__gte=date.fromisoformat(raw_start))
        except ValueError:
            pass
    if raw_end:
        try:
            qs = qs.filter(invoice_date__date__lte=date.fromisoformat(raw_end))
        except ValueError:
            pass

    invoices = list(qs)
    today_tag = timezone.localdate().strftime("%Y%m%d")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="GSTR1_{section.upper()}_{today_tag}.csv"'
    writer = csv.writer(response)

    if section == "b2b":
        writer.writerow([
            "GSTIN/UIN of Recipient",
            "Receiver Name",
            "Invoice Number",
            "Invoice Date",
            "Invoice Value",
            "Place Of Supply",
            "Reverse Charge",
            "Invoice Type",
            "Taxable Value",
            "IGST Amount",
            "CGST Amount",
            "SGST Amount",
            "Total GST",
        ])
        for inv in invoices:
            cust_gstin = (inv.customer.gstin or "").strip().upper()
            if not cust_gstin:
                continue
            cgst, sgst, igst = inv.cgst_amount, inv.sgst_amount, inv.igst_amount
            if inv.gst_amount > 0 and cgst == 0 and sgst == 0 and igst == 0:
                _, cgst, sgst, igst = _compute_tax_split(inv.distributor, inv.customer, inv.gst_amount)
            inv_dt = timezone.localtime(inv.invoice_date or inv.created_at).strftime("%d-%b-%Y")
            writer.writerow([
                sanitize_csv_cell(cust_gstin),
                sanitize_csv_cell(inv.customer.name),
                sanitize_csv_cell(inv.invoice_number),
                inv_dt,
                f"{inv.total_amount:.2f}",
                sanitize_csv_cell(inv.customer.state or "N/A"),
                "N",
                "Regular B2B",
                f"{inv.subtotal:.2f}",
                f"{igst:.2f}",
                f"{cgst:.2f}",
                f"{sgst:.2f}",
                f"{inv.gst_amount:.2f}",
            ])

    elif section == "b2c":
        writer.writerow([
            "Type",
            "Place Of Supply",
            "GST Rate (%)",
            "Invoice Count",
            "Taxable Value",
            "IGST Amount",
            "CGST Amount",
            "SGST Amount",
            "Total Invoice Value",
        ])
        buckets = {}
        for inv in invoices:
            if (inv.customer.gstin or "").strip():
                continue
            pos = (inv.customer.state or "N/A").strip() or "N/A"
            is_inter = inv.is_interstate
            if inv.gst_amount > 0 and inv.cgst_amount == 0 and inv.sgst_amount == 0 and inv.igst_amount == 0:
                is_inter, _, _, _ = _compute_tax_split(inv.distributor, inv.customer, inv.gst_amount)
            for item in inv.items.all():
                rate = Decimal(str(item.gst_rate or 0)).quantize(Decimal("0.01"))
                key = (pos, rate)
                taxable = Decimal(str(item.subtotal or 0)).quantize(Decimal("0.01"))
                total_v = Decimal(str(item.total or 0)).quantize(Decimal("0.01"))
                tax_amt = max(Decimal("0.00"), (total_v - taxable).quantize(Decimal("0.01")))
                if is_inter:
                    cgst, sgst, igst = Decimal("0.00"), Decimal("0.00"), tax_amt
                else:
                    cgst = (tax_amt / Decimal("2")).quantize(Decimal("0.01"))
                    sgst = (tax_amt - cgst).quantize(Decimal("0.01"))
                    igst = Decimal("0.00")
                if key not in buckets:
                    buckets[key] = {
                        "pos": pos,
                        "rate": rate,
                        "invoice_ids": set(),
                        "taxable": Decimal("0.00"),
                        "igst": Decimal("0.00"),
                        "cgst": Decimal("0.00"),
                        "sgst": Decimal("0.00"),
                        "total": Decimal("0.00"),
                    }
                b = buckets[key]
                b["invoice_ids"].add(inv.id)
                b["taxable"] += taxable
                b["igst"] += igst
                b["cgst"] += cgst
                b["sgst"] += sgst
                b["total"] += total_v

        for key in sorted(buckets.keys()):
            b = buckets[key]
            writer.writerow([
                "OE",
                sanitize_csv_cell(b["pos"]),
                f"{b['rate']:.2f}",
                len(b["invoice_ids"]),
                f"{b['taxable']:.2f}",
                f"{b['igst']:.2f}",
                f"{b['cgst']:.2f}",
                f"{b['sgst']:.2f}",
                f"{b['total']:.2f}",
            ])

    else:  # hsn
        writer.writerow([
            "HSN/SAC",
            "Description",
            "GST Rate (%)",
            "Total Quantity",
            "Total Value",
            "Taxable Value",
            "IGST Amount",
            "CGST Amount",
            "SGST Amount",
            "Total Tax",
        ])
        hsn_buckets = {}
        for inv in invoices:
            is_inter = inv.is_interstate
            if inv.gst_amount > 0 and inv.cgst_amount == 0 and inv.sgst_amount == 0 and inv.igst_amount == 0:
                is_inter, _, _, _ = _compute_tax_split(inv.distributor, inv.customer, inv.gst_amount)
            for row in build_hsn_tax_summary(inv.items.all(), is_interstate=is_inter):
                key = (row["hsn_code"], row["gst_rate"])
                if key not in hsn_buckets:
                    hsn_buckets[key] = dict(row)
                else:
                    hsn_buckets[key]["quantity"] += row["quantity"]
                    hsn_buckets[key]["taxable_value"] += row["taxable_value"]
                    hsn_buckets[key]["cgst"] += row["cgst"]
                    hsn_buckets[key]["sgst"] += row["sgst"]
                    hsn_buckets[key]["igst"] += row["igst"]
                    hsn_buckets[key]["total_tax"] += row["total_tax"]
                    hsn_buckets[key]["total_value"] += row["total_value"]

        for key in sorted(hsn_buckets.keys()):
            r = hsn_buckets[key]
            writer.writerow([
                sanitize_csv_cell(r["hsn_code"]),
                sanitize_csv_cell(r["description"]),
                f"{r['gst_rate']:.2f}",
                r["quantity"],
                f"{r['total_value']:.2f}",
                f"{r['taxable_value']:.2f}",
                f"{r['igst']:.2f}",
                f"{r['cgst']:.2f}",
                f"{r['sgst']:.2f}",
                f"{r['total_tax']:.2f}",
            ])

    return response


@login_required
def product_restock(request, pk):
    """Record a Stock-In (Purchase/Restock) or Manual Stock Adjustment with full audit trail."""
    if request.user.is_staff or request.user.is_superuser:
        product = get_object_or_404(Product, pk=pk)
    else:
        product = get_object_or_404(Product, pk=pk, distributor=request.user)

    if request.method != "POST":
        return redirect("product_detail", pk=product.pk)

    movement_type = (request.POST.get("movement_type") or "RESTOCK").strip().upper()
    if movement_type not in ("RESTOCK", "ADJUSTMENT"):
        movement_type = "RESTOCK"

    raw_qty = (request.POST.get("quantity") or "").strip()
    reference = (request.POST.get("reference") or "").strip()[:100]
    notes = (request.POST.get("notes") or "").strip()[:255]

    try:
        qty = int(raw_qty)
    except ValueError:
        messages.error(request, "Please enter a valid whole number quantity.")
        return redirect(request.POST.get("next") or "product_list")

    if movement_type == "RESTOCK" and qty <= 0:
        messages.error(request, "Restock quantity must be a positive number.")
        return redirect("product_detail", pk=product.pk)
    if movement_type == "ADJUSTMENT" and qty == 0:
        messages.error(request, "Adjustment quantity cannot be zero.")
        return redirect("product_detail", pk=product.pk)

    with transaction.atomic():
        locked = Product.objects.select_for_update().get(pk=product.pk)
        stock_before = locked.stock
        stock_after = stock_before + qty
        if stock_after < 0:
            messages.error(
                request,
                f"Adjustment would make stock negative (Current stock: {stock_before}, Change: {qty})."
            )
            return redirect("product_detail", pk=product.pk)
        locked.stock = stock_after
        locked.save(update_fields=["stock", "updated_at"])
        StockMovement.objects.create(
            product=locked,
            distributor=locked.distributor,
            movement_type=movement_type,
            quantity_change=qty,
            stock_before=stock_before,
            stock_after=stock_after,
            reference=reference or ("Purchase Restock" if movement_type == "RESTOCK" else "Manual Adjustment"),
            notes=notes,
        )

    sign = "+" if qty > 0 else ""
    messages.success(
        request,
        f"Updated stock for '{locked.name}': {sign}{qty} units (New Stock: {stock_after})."
    )
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("product_detail", pk=product.pk)


@login_required
def stock_ledger(request):
    """Full Stock Movement & Purchase/Sale Audit History with filters and CSV export."""
    is_admin = request.user.is_staff or request.user.is_superuser
    qs = StockMovement.objects.select_related("product", "distributor").order_by("-created_at", "-id")
    products_qs = Product.objects.all() if is_admin else Product.objects.filter(distributor=request.user)
    if not is_admin:
        qs = qs.filter(distributor=request.user)

    product_id = (request.GET.get("product") or "").strip()
    movement_type = (request.GET.get("type") or "").strip().upper()
    search_q = (request.GET.get("q") or "").strip()

    if product_id.isdigit():
        qs = qs.filter(product_id=int(product_id))
    if movement_type in {"OPENING", "RESTOCK", "SALE", "CANCEL_RESTORE", "ADJUSTMENT"}:
        qs = qs.filter(movement_type=movement_type)
    if search_q:
        qs = qs.filter(
            Q(product__name__icontains=search_q) |
            Q(product__sku__icontains=search_q) |
            Q(reference__icontains=search_q) |
            Q(notes__icontains=search_q)
        )

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="stock_ledger.csv"'
        writer = csv.writer(response)
        writer.writerow(["Date & Time", "Product", "SKU", "Type", "Change", "Before", "After", "Reference", "Notes"])
        for mv in qs[:5000]:
            dt_str = timezone.localtime(mv.created_at).strftime("%Y-%m-%d %H:%M")
            writer.writerow([
                dt_str,
                sanitize_csv_cell(mv.product.name),
                sanitize_csv_cell(mv.product.sku),
                mv.get_movement_type_display(),
                mv.quantity_change,
                mv.stock_before,
                mv.stock_after,
                sanitize_csv_cell(mv.reference),
                sanitize_csv_cell(mv.notes),
            ])
        return response

    summary = qs.aggregate(
        total_events=Count("id"),
        total_in=Coalesce(Sum("quantity_change", filter=Q(quantity_change__gt=0)), 0),
        total_out=Coalesce(Sum("quantity_change", filter=Q(quantity_change__lt=0)), 0),
    )

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "billing/stock_ledger.html", {
        "movements": page_obj,
        "page_obj": page_obj,
        "products": products_qs.order_by("name"),
        "selected_product": product_id,
        "selected_type": movement_type,
        "search_query": search_q,
        "total_events": summary["total_events"],
        "total_in": summary["total_in"],
        "total_out": abs(summary["total_out"]),
    })


# ==============================================================================
# PHASE 4: QUOTATIONS / ESTIMATES -> 1-CLICK TAX INVOICE CONVERSION
# ==============================================================================

def generate_quotation_number(user):
    """Generate globally unique sequential quotation number: QTN-YYYYMMDD-0001."""
    today_str = timezone.localtime(timezone.now()).strftime("%Y%m%d")
    prefix = f"QTN-{today_str}-"
    existing = Quotation.objects.filter(
        quotation_number__startswith=prefix
    ).values_list("quotation_number", flat=True)
    max_seq = 0
    for qn in existing:
        suffix = qn[len(prefix):]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    next_seq = max_seq + 1
    candidate = f"{prefix}{next_seq:04d}"
    while Quotation.objects.filter(quotation_number=candidate).exists():
        next_seq += 1
        candidate = f"{prefix}{next_seq:04d}"
    return candidate


@login_required
def quotation_list(request):
    """Directory of Sales Quotations / Proforma Estimates."""
    is_admin = request.user.is_staff or request.user.is_superuser
    qs = (
        Quotation.objects.select_related("customer", "distributor", "converted_invoice")
        .prefetch_related("items__product")
        .order_by("-created_at", "-id")
    )
    if not is_admin:
        qs = qs.filter(distributor=request.user)

    search_q = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()
    if search_q:
        qs = qs.filter(
            Q(quotation_number__icontains=search_q) |
            Q(customer__name__icontains=search_q) |
            Q(customer__phone__icontains=search_q)
        )
    if status_filter:
        qs = qs.filter(status__iexact=status_filter)

    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
    stats = qs.aggregate(
        total_quotes=Count("id"),
        converted_quotes=Count("id", filter=Q(status__iexact="Converted")),
        open_value=Coalesce(Sum("total_amount", filter=~Q(status__iexact="Converted")), zero_dec),
    )

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "billing/quotation_list.html", {
        "quotations": page_obj,
        "page_obj": page_obj,
        "search_query": search_q,
        "status_filter": status_filter,
        "total_quotes": stats["total_quotes"],
        "converted_quotes": stats["converted_quotes"],
        "open_value": stats["open_value"],
    })


@login_required
def quotation_create(request):
    """Create a Sales Quotation / Estimate without deducting inventory stock."""
    distributor = request.user
    form = InvoiceCreateForm(distributor=distributor)
    products = Product.objects.filter(distributor=distributor).order_by("name")
    dist_profile = getattr(distributor, "distributor_profile", None)
    distributor_state = (dist_profile.state or "").strip() if dist_profile else ""
    customer_states = {
        str(c.id): (c.state or "").strip()
        for c in form.fields["customer"].queryset
    }
    default_valid_until = (timezone.localdate() + timedelta(days=15)).isoformat()
    base_ctx = {
        "form": form,
        "products": products,
        "distributor_state": distributor_state,
        "customer_states_json": json.dumps(customer_states),
        "default_valid_until": default_valid_until,
    }

    if request.method == "POST":
        form = InvoiceCreateForm(request.POST, distributor=distributor)
        base_ctx["form"] = form
        product_ids = request.POST.getlist("product[]")
        quantities = request.POST.getlist("quantity[]")
        unit_prices = request.POST.getlist("unit_price[]")
        gst_rates = request.POST.getlist("gst_rate[]")
        discounts = request.POST.getlist("discount[]")

        if form.is_valid():
            customer = form.cleaned_data["customer"]
            valid_rows = [i for i in range(len(product_ids)) if product_ids[i].strip()]
            if not valid_rows:
                messages.error(request, "Please add at least one product to the quotation.")
                return render(request, "billing/quotation_create.html", base_ctx)

            raw_valid_until = (request.POST.get("valid_until") or "").strip()
            valid_until_val = None
            if raw_valid_until:
                try:
                    valid_until_val = date.fromisoformat(raw_valid_until)
                except ValueError:
                    messages.error(request, "Invalid validity date.")
                    return render(request, "billing/quotation_create.html", base_ctx)

            notes_val = (request.POST.get("notes") or "").strip()[:1000]
            status_val = (request.POST.get("status") or "Sent").strip()
            if status_val not in ("Draft", "Sent", "Accepted"):
                status_val = "Sent"

            try:
                with transaction.atomic():
                    total_subtotal = Decimal("0.00")
                    total_discount = Decimal("0.00")
                    total_gst = Decimal("0.00")
                    items_to_create = []

                    for idx in valid_rows:
                        p_id = int(product_ids[idx])
                        product = get_object_or_404(Product, pk=p_id, distributor=distributor)
                        qty = int(quantities[idx]) if idx < len(quantities) and quantities[idx] else 1
                        if qty <= 0:
                            raise ValueError(f"Quantity for '{product.name}' must be at least 1.")
                        price = Decimal(str(unit_prices[idx])) if idx < len(unit_prices) and unit_prices[idx] else product.price
                        if price <= Decimal("0.00"):
                            raise ValueError(f"Unit price for '{product.name}' must be greater than 0.")
                        gst_rate = Decimal(str(gst_rates[idx])) if idx < len(gst_rates) and gst_rates[idx] else product.gst_rate
                        if gst_rate < Decimal("0.00") or gst_rate > Decimal("100.00"):
                            raise ValueError(f"GST rate for '{product.name}' must be between 0 and 100.")
                        disc_pct = Decimal(str(discounts[idx])) if idx < len(discounts) and discounts[idx] else Decimal("0.00")
                        if disc_pct < Decimal("0.00") or disc_pct > Decimal("100.00"):
                            raise ValueError(f"Discount for '{product.name}' must be between 0% and 100%.")

                        line_base = (Decimal(qty) * price).quantize(Decimal("0.01"))
                        disc_amount = (line_base * (disc_pct / Decimal("100"))).quantize(Decimal("0.01"))
                        line_subtotal = (line_base - disc_amount).quantize(Decimal("0.01"))
                        line_gst = (line_subtotal * (gst_rate / Decimal("100"))).quantize(Decimal("0.01"))
                        line_total = (line_subtotal + line_gst).quantize(Decimal("0.01"))

                        total_subtotal += line_subtotal
                        total_discount += disc_amount
                        total_gst += line_gst

                        items_to_create.append({
                            "product": product,
                            "quantity": qty,
                            "unit_price": price,
                            "discount_percent": disc_pct,
                            "discount_amount": disc_amount,
                            "gst_rate": gst_rate,
                            "subtotal": line_subtotal,
                            "total": line_total,
                        })

                    q_number = generate_quotation_number(distributor)
                    grand_total = (total_subtotal + total_gst).quantize(Decimal("0.01"))
                    is_interstate, cgst_amount, sgst_amount, igst_amount = _compute_tax_split(
                        distributor, customer, total_gst
                    )

                    quotation = Quotation.objects.create(
                        quotation_number=q_number,
                        customer=customer,
                        distributor=distributor,
                        valid_until=valid_until_val,
                        subtotal=total_subtotal,
                        discount_total=total_discount,
                        gst_amount=total_gst,
                        cgst_amount=cgst_amount,
                        sgst_amount=sgst_amount,
                        igst_amount=igst_amount,
                        is_interstate=is_interstate,
                        total_amount=grand_total,
                        status=status_val,
                        notes=notes_val,
                    )

                    for item_data in items_to_create:
                        QuotationItem.objects.create(quotation=quotation, **item_data)

                    messages.success(request, f"Quotation {q_number} created successfully.")
                    return redirect("quotation_detail", pk=quotation.pk)
            except (ValueError, InvalidOperation) as exc:
                messages.error(request, str(exc))
                return render(request, "billing/quotation_create.html", base_ctx)
        else:
            messages.error(request, "Please select a valid customer.")

    return render(request, "billing/quotation_create.html", base_ctx)


def _build_quotation_context(pk, distributor=None):
    qs = Quotation.objects.select_related(
        "customer", "distributor", "distributor__distributor_profile", "converted_invoice"
    ).prefetch_related("items__product")
    quotation = get_object_or_404(qs, pk=pk, distributor=distributor) if distributor is not None else get_object_or_404(qs, pk=pk)
    items = list(quotation.items.all())
    dist_profile = getattr(quotation.distributor, "distributor_profile", None)
    seller_name = (
        (dist_profile.business_name or "").strip() if dist_profile else ""
    ) or quotation.distributor.get_full_name() or quotation.distributor.username
    place_of_supply = (
        (quotation.customer.state or "").strip()
        or ((dist_profile.state or "").strip() if dist_profile else "")
        or "N/A"
    )
    hsn_summary = build_hsn_tax_summary(items, is_interstate=quotation.is_interstate)
    amount_in_words = amount_to_indian_words(quotation.total_amount)
    valid_str = quotation.valid_until.strftime("%d %b %Y") if quotation.valid_until else "N/A"
    wa_text = (
        f"Hello {quotation.customer.name},\n"
        f"Quotation *{quotation.quotation_number}* from *{seller_name}*:\n"
        f"Total Estimate: Rs. {quotation.total_amount:.2f}\n"
        f"Valid Until: {valid_str}\n"
        "Please confirm to proceed with GST Tax Invoice."
    )
    clean_phone = re.sub(r"\D", "", quotation.customer.phone or "")
    wa_phone = f"91{clean_phone}" if len(clean_phone) == 10 else clean_phone
    return {
        "quotation": quotation,
        "items": items,
        "distributor_profile": dist_profile,
        "seller_name": seller_name,
        "place_of_supply": place_of_supply,
        "hsn_summary": hsn_summary,
        "amount_in_words": amount_in_words,
        "whatsapp_share_url": f"https://wa.me/{wa_phone}?text={quote(wa_text)}",
    }


@login_required
def quotation_detail(request, pk):
    dist_filter = None if (request.user.is_staff or request.user.is_superuser) else request.user
    context = _build_quotation_context(pk, distributor=dist_filter)
    return render(request, "billing/quotation_detail.html", context)


@login_required
def quotation_pdf(request, pk):
    dist_filter = None if (request.user.is_staff or request.user.is_superuser) else request.user
    context = _build_quotation_context(pk, distributor=dist_filter)
    quotation = context["quotation"]
    pdf = render_to_pdf("billing/quotation_pdf.html", context)
    if pdf is None:
        messages.error(request, "Quotation PDF generation failed.")
        return redirect("quotation_detail", pk=quotation.pk)
    pdf["Content-Disposition"] = f'attachment; filename="{quotation.quotation_number}.pdf"'
    return pdf


@login_required
def quotation_convert_to_invoice(request, pk):
    """
    Convert a Sales Quotation into a full GST Tax Invoice in 1 click:
    atomically locks & verifies stock, deducts inventory, logs StockMovement,
    generates Invoice + QR code, and links Quotation -> Invoice.
    """
    if request.user.is_staff or request.user.is_superuser:
        quotation = get_object_or_404(Quotation, pk=pk)
    else:
        quotation = get_object_or_404(Quotation, pk=pk, distributor=request.user)

    if request.method != "POST":
        return redirect("quotation_detail", pk=quotation.pk)

    if quotation.status == "Converted" and quotation.converted_invoice_id:
        messages.info(request, f"Quotation {quotation.quotation_number} is already converted to {quotation.converted_invoice.invoice_number}.")
        return redirect("invoice_detail", pk=quotation.converted_invoice_id)

    q_items = list(quotation.items.select_related("product").all())
    if not q_items:
        messages.error(request, "Cannot convert an empty quotation.")
        return redirect("quotation_detail", pk=quotation.pk)

    try:
        with transaction.atomic():
            locked_products = {}
            stock_logs = []
            for qi in q_items:
                if qi.product_id not in locked_products:
                    prod = Product.objects.select_for_update().get(pk=qi.product_id)
                    locked_products[qi.product_id] = prod
                else:
                    prod = locked_products[qi.product_id]

                if prod.stock < qi.quantity:
                    raise ValueError(
                        f"Insufficient stock for '{prod.name}' (Available: {prod.stock}, Needed: {qi.quantity}). Please restock first."
                    )
                before = prod.stock
                prod.stock -= qi.quantity
                stock_logs.append({
                    "product": prod,
                    "qty": qi.quantity,
                    "stock_before": before,
                    "stock_after": prod.stock,
                })

            for prod in locked_products.values():
                prod.save(update_fields=["stock", "updated_at"])

            inv_number = generate_invoice_number(quotation.distributor)
            invoice = Invoice.objects.create(
                invoice_number=inv_number,
                customer=quotation.customer,
                distributor=quotation.distributor,
                subtotal=quotation.subtotal,
                discount_total=quotation.discount_total,
                gst_amount=quotation.gst_amount,
                cgst_amount=quotation.cgst_amount,
                sgst_amount=quotation.sgst_amount,
                igst_amount=quotation.igst_amount,
                is_interstate=quotation.is_interstate,
                total_amount=quotation.total_amount,
                amount_paid=Decimal("0.00"),
                status="Pending",
                payment_mode="Unpaid",
                notes=quotation.notes or f"Converted from Quotation {quotation.quotation_number}",
            )

            for qi in q_items:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    product=qi.product,
                    quantity=qi.quantity,
                    unit_price=qi.unit_price,
                    discount_percent=qi.discount_percent,
                    discount_amount=qi.discount_amount,
                    gst_rate=qi.gst_rate,
                    subtotal=qi.subtotal,
                    total=qi.total,
                )

            for sl in stock_logs:
                StockMovement.objects.create(
                    product=sl["product"],
                    distributor=quotation.distributor,
                    movement_type="SALE",
                    quantity_change=-sl["qty"],
                    stock_before=sl["stock_before"],
                    stock_after=sl["stock_after"],
                    reference=inv_number,
                    notes=f"Converted from {quotation.quotation_number}",
                )

            invoice.save()
            quotation.status = "Converted"
            quotation.converted_invoice = invoice
            quotation.save(update_fields=["status", "converted_invoice", "updated_at"])

        messages.success(
            request,
            f"Quotation {quotation.quotation_number} converted into Tax Invoice {inv_number}."
        )
        return redirect("invoice_detail", pk=invoice.pk)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("quotation_detail", pk=quotation.pk)


# ==============================================================================
# CUSTOMER DETAIL VIEW & TRANSACTION-SAFE INVOICE EDITING
# ==============================================================================

@login_required
def customer_detail(request, pk):
    """
    Dedicated Customer Details page showing full customer profile, GSTIN, address,
    financial billing summary (Khata KPIs), and recent invoices.
    """
    if request.user.is_staff or request.user.is_superuser:
        customer = get_object_or_404(Customer.objects.select_related("distributor"), pk=pk)
    else:
        customer = get_object_or_404(Customer, pk=pk, distributor=request.user)

    invoices_qs = Invoice.objects.filter(customer=customer).order_by("-created_at", "-id")
    active_invs = list(invoices_qs.exclude(status__iexact="Cancelled"))
    total_billed = sum((inv.total_amount for inv in active_invs), Decimal("0.00"))
    total_paid = sum((inv.effective_amount_paid for inv in active_invs), Decimal("0.00"))
    total_due = sum((inv.balance_due for inv in active_invs), Decimal("0.00"))
    overdue_count = sum(1 for inv in active_invs if inv.is_overdue)

    return render(request, "billing/customer_detail.html", {
        "customer": customer,
        "recent_invoices": invoices_qs[:10],
        "total_invoices_count": invoices_qs.count(),
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_due": total_due,
        "overdue_count": overdue_count,
    })


@login_required
def invoice_edit(request, pk):
    """
    Edit an existing Pending or Partial invoice safely inside a database transaction:
    restores old item stock, validates & deducts new item stock with StockMovement audit,
    recalculates server-side GST/discounts/totals, enforces amount_paid guard, and refreshes QR.
    """
    if request.user.is_staff or request.user.is_superuser:
        invoice = get_object_or_404(
            Invoice.objects.select_related("customer", "distributor", "distributor__distributor_profile").prefetch_related("items__product"),
            pk=pk,
        )
    else:
        invoice = get_object_or_404(
            Invoice.objects.select_related("customer", "distributor", "distributor__distributor_profile").prefetch_related("items__product"),
            pk=pk,
            distributor=request.user,
        )

    if (invoice.status or "").lower() in ("paid", "cancelled"):
        messages.error(
            request,
            f"Invoice {invoice.invoice_number} is {invoice.status} and cannot be edited."
        )
        return redirect("invoice_detail", pk=invoice.pk)

    owner_dist = invoice.distributor
    customers = Customer.objects.filter(distributor=owner_dist, is_active=True).order_by("name")
    products = Product.objects.filter(distributor=owner_dist).order_by("name")
    existing_items = list(invoice.items.all())

    base_ctx = {
        "invoice": invoice,
        "customers": customers,
        "products": products,
        "existing_items": existing_items,
    }

    if request.method == "POST":
        cust_id = (request.POST.get("customer") or "").strip()
        customer = customers.filter(pk=cust_id).first() if cust_id.isdigit() else None
        if not customer:
            messages.error(request, "Please select a valid customer.")
            return render(request, "billing/invoice_edit.html", base_ctx)

        product_ids = request.POST.getlist("product[]")
        quantities = request.POST.getlist("quantity[]")
        unit_prices = request.POST.getlist("unit_price[]")
        gst_rates = request.POST.getlist("gst_rate[]")
        discounts = request.POST.getlist("discount[]")
        valid_rows = [i for i in range(len(product_ids)) if product_ids[i].strip()]

        if not valid_rows:
            messages.error(request, "An invoice must contain at least one product.")
            return render(request, "billing/invoice_edit.html", base_ctx)

        raw_due_date = (request.POST.get("due_date") or "").strip()
        due_date_val = None
        if raw_due_date:
            try:
                due_date_val = date.fromisoformat(raw_due_date)
            except ValueError:
                messages.error(request, "Please enter a valid due date.")
                return render(request, "billing/invoice_edit.html", base_ctx)

        notes_val = (request.POST.get("notes") or "").strip()[:1000]
        apply_round_off = request.POST.get("apply_round_off") in ("1", "on", "true")

        try:
            with transaction.atomic():
                inv_locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
                if (inv_locked.status or "").lower() in ("paid", "cancelled"):
                    raise ValueError(f"Invoice {inv_locked.invoice_number} can no longer be edited.")

                old_items = list(inv_locked.items.select_related("product").all())
                all_prod_ids = sorted(
                    {it.product_id for it in old_items}
                    | {int(product_ids[idx]) for idx in valid_rows}
                )
                locked_products = {
                    p.id: p
                    for p in Product.objects.select_for_update().filter(pk__in=all_prod_ids, distributor=owner_dist)
                }

                # 1. Restore previous item quantities
                stock_logs = []
                for old_item in old_items:
                    prod = locked_products[old_item.product_id]
                    before = prod.stock
                    prod.stock += old_item.quantity
                    stock_logs.append({
                        "product": prod,
                        "movement_type": "ADJUSTMENT",
                        "qty_change": old_item.quantity,
                        "stock_before": before,
                        "stock_after": prod.stock,
                        "reference": f"Edit {inv_locked.invoice_number}",
                        "notes": "Restored prior to invoice edit",
                    })

                # 2. Validate & deduct new quantities
                total_subtotal = Decimal("0.00")
                total_discount = Decimal("0.00")
                total_gst = Decimal("0.00")
                items_to_create = []

                for idx in valid_rows:
                    p_id = int(product_ids[idx])
                    prod = locked_products.get(p_id)
                    if not prod:
                        raise ValueError("Selected product does not exist for this distributor.")

                    qty = int(quantities[idx]) if idx < len(quantities) and quantities[idx] else 1
                    if qty <= 0:
                        raise ValueError(f"Quantity for '{prod.name}' must be at least 1.")
                    if prod.stock < qty:
                        raise ValueError(
                            f"Insufficient stock for '{prod.name}' (Available after restore: {prod.stock}, Requested: {qty})."
                        )

                    price = Decimal(str(unit_prices[idx])) if idx < len(unit_prices) and unit_prices[idx] else prod.price
                    if price <= Decimal("0.00"):
                        raise ValueError(f"Unit price for '{prod.name}' must be greater than 0.")

                    gst_rate = Decimal(str(gst_rates[idx])) if idx < len(gst_rates) and gst_rates[idx] else prod.gst_rate
                    if gst_rate < Decimal("0.00") or gst_rate > Decimal("100.00"):
                        raise ValueError(f"GST rate for '{prod.name}' must be between 0 and 100.")

                    disc_pct = Decimal(str(discounts[idx])) if idx < len(discounts) and discounts[idx] else Decimal("0.00")
                    if disc_pct < Decimal("0.00") or disc_pct > Decimal("100.00"):
                        raise ValueError(f"Discount for '{prod.name}' must be between 0% and 100%.")

                    before = prod.stock
                    prod.stock -= qty
                    stock_logs.append({
                        "product": prod,
                        "movement_type": "SALE",
                        "qty_change": -qty,
                        "stock_before": before,
                        "stock_after": prod.stock,
                        "reference": f"Edit {inv_locked.invoice_number}",
                        "notes": f"Updated invoice for {customer.name}",
                    })

                    line_base = (Decimal(qty) * price).quantize(Decimal("0.01"))
                    disc_amount = (line_base * (disc_pct / Decimal("100"))).quantize(Decimal("0.01"))
                    line_subtotal = (line_base - disc_amount).quantize(Decimal("0.01"))
                    line_gst = (line_subtotal * (gst_rate / Decimal("100"))).quantize(Decimal("0.01"))
                    line_total = (line_subtotal + line_gst).quantize(Decimal("0.01"))

                    total_subtotal += line_subtotal
                    total_discount += disc_amount
                    total_gst += line_gst

                    items_to_create.append({
                        "product": prod,
                        "quantity": qty,
                        "unit_price": price,
                        "discount_percent": disc_pct,
                        "discount_amount": disc_amount,
                        "gst_rate": gst_rate,
                        "subtotal": line_subtotal,
                        "total": line_total,
                    })

                raw_grand_total = (total_subtotal + total_gst).quantize(Decimal("0.01"))
                round_off_val = Decimal("0.00")
                grand_total = raw_grand_total
                if apply_round_off:
                    rounded = raw_grand_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP).quantize(Decimal("0.01"))
                    round_off_val = (rounded - raw_grand_total).quantize(Decimal("0.01"))
                    grand_total = rounded

                already_paid = inv_locked.effective_amount_paid
                if grand_total < already_paid:
                    raise ValueError(
                        f"Updated invoice total (Rs. {grand_total:.2f}) cannot be less than already paid amount (Rs. {already_paid:.2f})."
                    )

                for prod in locked_products.values():
                    prod.save(update_fields=["stock", "updated_at"])

                is_interstate, cgst_amount, sgst_amount, igst_amount = _compute_tax_split(
                    owner_dist, customer, total_gst
                )

                inv_locked.items.all().delete()
                for item_data in items_to_create:
                    InvoiceItem.objects.create(invoice=inv_locked, **item_data)

                for sl in stock_logs:
                    StockMovement.objects.create(
                        product=sl["product"],
                        distributor=owner_dist,
                        movement_type=sl["movement_type"],
                        quantity_change=sl["qty_change"],
                        stock_before=sl["stock_before"],
                        stock_after=sl["stock_after"],
                        reference=sl["reference"],
                        notes=sl["notes"],
                    )

                inv_locked.customer = customer
                inv_locked.subtotal = total_subtotal
                inv_locked.discount_total = total_discount
                inv_locked.gst_amount = total_gst
                inv_locked.cgst_amount = cgst_amount
                inv_locked.sgst_amount = sgst_amount
                inv_locked.igst_amount = igst_amount
                inv_locked.is_interstate = is_interstate
                inv_locked.round_off = round_off_val
                inv_locked.total_amount = grand_total
                inv_locked.due_date = due_date_val
                inv_locked.notes = notes_val
                inv_locked.save()
                inv_locked.recalculate_payment_status()

            messages.success(request, f"Invoice {invoice.invoice_number} updated successfully and inventory reconciled.")
            return redirect("invoice_detail", pk=invoice.pk)
        except (ValueError, InvalidOperation) as exc:
            messages.error(request, str(exc))
            return render(request, "billing/invoice_edit.html", base_ctx)

    return render(request, "billing/invoice_edit.html", base_ctx)
