from .utils import render_to_pdf, decode_qr_image
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from decimal import Decimal, InvalidOperation
from django.db.models import Q
from django.utils import timezone
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
import uuid

import qrcode
import base64
from io import BytesIO

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate
from django.contrib.auth.models import User

from .models import Customer, Product, Invoice, InvoiceItem
from .forms import InvoiceCreateForm, InvoiceReportFilterForm


@login_required
def customer_list(request):
    """
    Customer Dashboard / List View with real-time statistics,
    search filtering, and distributor-level ownership isolation.
    """
    search_query = request.GET.get("q", "").strip()

    # Ownership isolation: Only get customers of the logged-in distributor
    customers_qs = Customer.objects.filter(distributor=request.user)

    # Real-time statistics from the database
    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)

    total_customers = customers_qs.count()
    active_customers = customers_qs.filter(is_active=True).count()
    recently_added = customers_qs.filter(created_at__gte=seven_days_ago).count()
    this_month = customers_qs.filter(
        created_at__year=now.year,
        created_at__month=now.month
    ).count()

    # Search filtering
    if search_query:
        customers_qs = customers_qs.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(city__icontains=search_query) |
            Q(state__icontains=search_query)
        )

    context = {
        "customers": customers_qs,
        "search_query": search_query,
        "total_customers": total_customers,
        "active_customers": active_customers,
        "recently_added": recently_added,
        "this_month": this_month,
    }
    return render(request, "billing/customer_list.html", context)


@login_required
def customer_register_view(request):
    """
    Front-end view for registering a new customer by the authenticated distributor.
    Renders the modern customer registration form with real-time feedback and validation.
    """
    errors = {}
    form_data = {}

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        is_active = request.POST.get("is_active") in ["on", "true", True, "1"]

        form_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "address": address,
            "city": city,
            "state": state,
            "pincode": pincode,
            "is_active": is_active,
        }

        # Validation
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
            customer = Customer.objects.create(
                distributor=request.user,
                name=name,
                email=email if email else None,
                phone=phone,
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
        }
    )

# Alias for backward-compatibility
customer_add = customer_register_view



@login_required
def customer_edit(request, pk):
    """
    Edit existing customer with distributor-level ownership verification.
    """
    # Safe lookup ensuring logged-in distributor owns the customer
    customer = get_object_or_404(Customer, pk=pk, distributor=request.user)

    errors = {}
    form_data = {
        "name": customer.name,
        "email": customer.email or "",
        "phone": customer.phone,
        "address": customer.address or "",
        "city": customer.city,
        "state": customer.state,
        "pincode": customer.pincode,
        "is_active": customer.is_active,
    }

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        city = request.POST.get("city", "").strip()
        state = request.POST.get("state", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        is_active = request.POST.get("is_active") == "on"

        form_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "address": address,
            "city": city,
            "state": state,
            "pincode": pincode,
            "is_active": is_active,
        }

        # Validation
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
            customer.address = address
            customer.city = city
            customer.state = state
            customer.pincode = pincode
            customer.is_active = is_active
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
        }
    )


@login_required
def customer_delete(request, pk):
    """
    Safely delete customer via POST with distributor ownership check.
    """
    customer = get_object_or_404(Customer, pk=pk, distributor=request.user)

    if request.method == "POST":
        customer_name = customer.name
        customer.delete()
        messages.success(request, f'Customer "{customer_name}" deleted successfully.')
        return redirect("customer_list")

    messages.error(request, "Invalid request method for delete.")
    return redirect("customer_list")

@login_required
def product_add(request):

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "").strip()
        price = request.POST.get("price", "").strip()
        stock = request.POST.get("stock", "").strip()
        gst_rate = request.POST.get("gst_rate", "").strip()
        description = request.POST.get("description", "").strip()

        context = {
            "name": name,
            "category": category,
            "price": price,
            "stock": stock,
            "gst_rate": gst_rate,
            "description": description,
        }

        # Required fields
        if not all([name, category, price, stock, gst_rate]):
            context["error"] = "Please fill in all required fields."
            return render(
                request,
                "billing/product_add.html",
                context
            )

        # Name validation
        if len(name) < 2:
            context["error"] = "Product name must contain at least 2 characters."
            return render(
                request,
                "billing/product_add.html",
                context
            )

        # Price validation
        try:
            price_value = float(price)

            if price_value <= 0:
                raise ValueError

        except ValueError:
            context["error"] = "Please enter a valid price greater than 0."
            return render(
                request,
                "billing/product_add.html",
                context
            )

        # Stock validation
        try:
            stock_value = int(stock)

            if stock_value < 0:
                raise ValueError

        except ValueError:
            context["error"] = "Stock must be a valid non-negative number."
            return render(
                request,
                "billing/product_add.html",
                context
            )

        # GST validation
        try:
            gst_value = float(gst_rate)

            if gst_value < 0 or gst_value > 100:
                raise ValueError

        except ValueError:
            context["error"] = "GST rate must be between 0 and 100."
            return render(
                request,
                "billing/product_add.html",
                context
            )

        # Create product
        Product.objects.create(
            distributor=request.user,
            name=name,
            category=category,
            price=price_value,
            stock=stock_value,
            gst_rate=gst_value,
            description=description,
        )

        messages.success(
            request,
            "Product added successfully."
        )

        return redirect("product_list")

    return render(
        request,
        "billing/product_add.html"
    )

@login_required
def product_list(request):
    """
    Product Management Dashboard & List View with live inventory KPI metrics,
    search filtering, pagination, and multi-tenant isolation.
    """
    query = request.GET.get("q", "").strip()

    base_qs = Product.objects.filter(distributor=request.user)

    # Real-time inventory metrics
    total_products = base_qs.count()
    low_stock_count = base_qs.filter(stock__gt=0, stock__lte=10).count()
    out_of_stock_count = base_qs.filter(stock=0).count()
    in_stock_count = base_qs.filter(stock__gt=10).count()
    total_inventory_value = sum((p.price * p.stock) for p in base_qs)

    products = base_qs.order_by("-created_at")

    if query:
        products = products.filter(
            models.Q(name__icontains=query) |
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
            "total_products": total_products,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "in_stock_count": in_stock_count,
            "total_inventory_value": total_inventory_value,
        }
    )


@login_required
def product_edit(request, pk):

    # Security:
    # Only the logged-in distributor can edit his own product
    product = get_object_or_404(
        Product,
        pk=pk,
        distributor=request.user
    )

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        category = request.POST.get("category", "").strip()
        price = request.POST.get("price", "").strip()
        stock = request.POST.get("stock", "").strip()
        gst_rate = request.POST.get("gst_rate", "").strip()
        description = request.POST.get("description", "").strip()

        # -----------------------------
        # Required validation
        # -----------------------------

        if not name or not category or not price or not stock or not gst_rate:
            return render(
                request,
                "billing/product_edit.html",
                {
                    "product": product,
                    "error": "Please fill in all required fields."
                }
            )

        if len(name) < 2:
            return render(
                request,
                "billing/product_edit.html",
                {
                    "product": product,
                    "error": "Product name must contain at least 2 characters."
                }
            )

        # -----------------------------
        # Price validation
        # -----------------------------

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
                    "error": "Price must be greater than 0."
                }
            )

        # -----------------------------
        # Stock validation
        # -----------------------------

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
                    "error": "Stock cannot be negative."
                }
            )

        # -----------------------------
        # GST validation
        # -----------------------------

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
                    "error": "GST rate must be between 0 and 100."
                }
            )

        # -----------------------------
        # Update Product
        # -----------------------------

        product.name = name
        product.category = category
        product.price = price_value
        product.stock = stock_value
        product.gst_rate = gst_value
        product.description = description

        product.save()

        messages.success(
            request,
            f"Product '{product.name}' updated successfully."
        )

        return redirect("product_list")

    return render(
        request,
        "billing/product_edit.html",
        {
            "product": product
        }
    )

@login_required
def product_delete(request, pk):

    # Security:
    # Only the logged-in distributor can delete his own product
    product = get_object_or_404(
        Product,
        pk=pk,
        distributor=request.user
    )

    # Delete only through POST request
    if request.method == "POST":

        product_name = product.name

        product.delete()

        messages.success(
            request,
            f"Product '{product_name}' deleted successfully."
        )

        return redirect("product_list")

    # If someone tries GET directly, don't delete anything
    messages.error(
        request,
        "Invalid request for product deletion."
    )

    return redirect("product_list")


@login_required
def product_detail(request, pk):
    """
    Read / View single product details with distributor ownership verification.
    """
    product = get_object_or_404(
        Product,
        pk=pk,
        distributor=request.user
    )
    return render(
        request,
        "billing/product_detail.html",
        {
            "product": product
        }
    )



def generate_invoice_number(user):
    """
    Generate a clean sequential invoice number: INV-YYYYMMDD-0001
    """
    today_str = timezone.now().strftime("%Y%m%d")
    count_today = Invoice.objects.filter(
        distributor=user,
        invoice_date__date=timezone.now().date()
    ).count() + 1
    return f"INV-{today_str}-{count_today:04d}"


@login_required
def invoice_create(request):
    """
    25 Aug Task: Create Invoice with dynamic customer & product dropdowns,
    JavaScript real-time calculations (Qty, GST, Discount), and dynamic rows.
    """
    distributor = request.user
    form = InvoiceCreateForm(distributor=distributor)
    products = Product.objects.filter(distributor=distributor).order_by("name")

    if request.method == "POST":
        form = InvoiceCreateForm(request.POST, distributor=distributor)
        product_ids = request.POST.getlist("product[]")
        quantities = request.POST.getlist("quantity[]")
        unit_prices = request.POST.getlist("unit_price[]")
        gst_rates = request.POST.getlist("gst_rate[]")
        discounts = request.POST.getlist("discount[]")

        if form.is_valid():
            customer = form.cleaned_data["customer"]

            # Filter valid row entries
            valid_rows = [i for i in range(len(product_ids)) if product_ids[i].strip()]

            if not valid_rows:
                messages.error(request, "Please add at least one product to the invoice.")
                return render(request, "billing/invoice_create.html", {
                    "form": form,
                    "products": products,
                })

            try:
                with transaction.atomic():
                    total_subtotal = Decimal("0.00")
                    total_gst = Decimal("0.00")
                    items_to_create = []

                    for idx in valid_rows:
                        p_id = int(product_ids[idx])
                        product = get_object_or_404(Product, pk=p_id, distributor=distributor)

                        qty = int(quantities[idx]) if idx < len(quantities) and quantities[idx] else 1
                        if qty <= 0:
                            raise ValueError(f"Quantity for product '{product.name}' must be at least 1.")

                        price = Decimal(str(unit_prices[idx])) if idx < len(unit_prices) and unit_prices[idx] else product.price
                        gst_rate = Decimal(str(gst_rates[idx])) if idx < len(gst_rates) and gst_rates[idx] else product.gst_rate
                        disc_pct = Decimal(str(discounts[idx])) if idx < len(discounts) and discounts[idx] else Decimal("0.00")

                        # Line Calculations:
                        # 1. Base Price = qty * unit_price
                        # 2. Discount Amount = Base * (Discount% / 100)
                        # 3. Subtotal (taxable) = Base - Discount
                        # 4. GST Amount = Subtotal * (GST% / 100)
                        # 5. Line Total = Subtotal + GST
                        line_base = (Decimal(qty) * price).quantize(Decimal("0.01"))
                        disc_amount = (line_base * (disc_pct / Decimal("100"))).quantize(Decimal("0.01"))
                        line_subtotal = (line_base - disc_amount).quantize(Decimal("0.01"))
                        line_gst = (line_subtotal * (gst_rate / Decimal("100"))).quantize(Decimal("0.01"))
                        line_total = (line_subtotal + line_gst).quantize(Decimal("0.01"))

                        total_subtotal += line_subtotal
                        total_gst += line_gst

                        items_to_create.append({
                            "product": product,
                            "quantity": qty,
                            "unit_price": price,
                            "gst_rate": gst_rate,
                            "subtotal": line_subtotal,
                            "total": line_total,
                        })

                    inv_number = generate_invoice_number(distributor)
                    grand_total = (total_subtotal + total_gst).quantize(Decimal("0.01"))

                    invoice = Invoice.objects.create(
                        invoice_number=inv_number,
                        customer=customer,
                        distributor=distributor,
                        subtotal=total_subtotal,
                        gst_amount=total_gst,
                        total_amount=grand_total,
                        status="Pending"
                    )

                    for item_data in items_to_create:
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            product=item_data["product"],
                            quantity=item_data["quantity"],
                            unit_price=item_data["unit_price"],
                            gst_rate=item_data["gst_rate"],
                            subtotal=item_data["subtotal"],
                            total=item_data["total"]
                        )

                    # Refresh QR code on invoice save after items are attached (Task 60)
                    invoice.save()

                    messages.success(request, f"Invoice {inv_number} generated successfully.")
                    return redirect("invoice_detail", pk=invoice.pk)

            except (ValueError, InvalidOperation) as e:
                messages.error(request, str(e))
                return render(request, "billing/invoice_create.html", {
                    "form": form,
                    "products": products,
                })
        else:
            messages.error(request, "Please select a valid customer.")

    return render(request, "billing/invoice_create.html", {
        "form": form,
        "products": products,
    })


@login_required
def invoice_list(request):
    """
    Invoice directory listing with dynamic data retrieval from Invoice and InvoiceItem models,
    including customer name, total bill, date, product summary, and pagination.
    """
    search_query = request.GET.get("q", "").strip()
    invoices_qs = (
        Invoice.objects.filter(distributor=request.user)
        .select_related("customer")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )

    if search_query:
        invoices_qs = invoices_qs.filter(
            Q(invoice_number__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(customer__phone__icontains=search_query)
        )

    total_invoices = invoices_qs.count()
    total_billed = sum(inv.total_amount for inv in invoices_qs)

    # Attach dynamic product summary and item count for each invoice
    for inv in invoices_qs:
        item_list = list(inv.items.all())
        inv.product_count = len(item_list)
        inv.product_summary = ", ".join(f"{item.product.name} (x{item.quantity})" for item in item_list)
        inv.product_names = [item.product.name for item in item_list]

    # Pagination (10 items per page)
    paginator = Paginator(invoices_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "billing/invoice_list.html", {
        "invoices": page_obj,
        "page_obj": page_obj,
        "search_query": search_query,
        "total_invoices": total_invoices,
        "total_billed": total_billed,
    })


@login_required
def invoice_report(request):
    """
    Task 43: Report generation view for filtering invoices by date range.
    Builds the report generation form supporting start_date, end_date,
    payment status, and customer filters, with multi-tenant isolation.
    """
    distributor = request.user
    form = InvoiceReportFilterForm(request.GET or None, distributor=distributor)

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

    # Attach product summary
    for inv in invoices_qs:
        item_list = list(inv.items.all())
        inv.product_count = len(item_list)
        inv.product_summary = ", ".join(f"{item.product.name} (x{item.quantity})" for item in item_list)

    total_invoices_count = invoices_qs.count()
    total_amount_collected = sum(inv.total_amount for inv in invoices_qs)
    total_tax_collected = sum(inv.gst_amount for inv in invoices_qs)
    total_subtotal_amount = sum(inv.subtotal for inv in invoices_qs)

    paid_invoices_qs = [inv for inv in invoices_qs if (inv.status or "").lower() == "paid"]
    pending_invoices_qs = [inv for inv in invoices_qs if (inv.status or "").lower() == "pending"]

    paid_count = len(paid_invoices_qs)
    pending_count = len(pending_invoices_qs)
    paid_amount = sum(inv.total_amount for inv in paid_invoices_qs)
    pending_amount = sum(inv.total_amount for inv in pending_invoices_qs)

    paginator = Paginator(invoices_qs, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "form": form,
        "invoices": page_obj,
        "page_obj": page_obj,
        "start_date": start_date,
        "end_date": end_date,
        "selected_status": selected_status,
        "selected_customer": selected_customer,
        "total_invoices_count": total_invoices_count,
        "total_amount_collected": total_amount_collected,
        "total_tax_collected": total_tax_collected,
        "total_subtotal_amount": total_subtotal_amount,
        "paid_count": paid_count,
        "pending_count": pending_count,
        "paid_amount": paid_amount,
        "pending_amount": pending_amount,
    }
    return render(request, "billing/invoice_report.html", context)


@login_required
def invoice_report_pdf(request):
    """
    Task 45: Provide an option to download report as a PDF using xhtml2pdf.
    Renders the filtered invoice report with date range and KPI summary.
    """
    distributor = request.user
    form = InvoiceReportFilterForm(request.GET or None, distributor=distributor)

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

    total_invoices_count = invoices_qs.count()
    total_amount_collected = sum(inv.total_amount for inv in invoices_qs)
    total_tax_collected = sum(inv.gst_amount for inv in invoices_qs)
    total_subtotal_amount = sum(inv.subtotal for inv in invoices_qs)

    paid_invoices_qs = [inv for inv in invoices_qs if (inv.status or "").lower() == "paid"]
    pending_invoices_qs = [inv for inv in invoices_qs if (inv.status or "").lower() == "pending"]

    paid_count = len(paid_invoices_qs)
    pending_count = len(pending_invoices_qs)
    paid_amount = sum(inv.total_amount for inv in paid_invoices_qs)
    pending_amount = sum(inv.total_amount for inv in pending_invoices_qs)

    for inv in invoices_qs:
        item_list = list(inv.items.all())
        inv.product_count = len(item_list)
        inv.product_summary = ", ".join(f"{item.product.name} (x{item.quantity})" for item in item_list)

    context = {
        "distributor": distributor,
        "invoices": invoices_qs,
        "start_date": start_date,
        "end_date": end_date,
        "selected_status": selected_status,
        "selected_customer": selected_customer,
        "total_invoices_count": total_invoices_count,
        "total_amount_collected": total_amount_collected,
        "total_tax_collected": total_tax_collected,
        "total_subtotal_amount": total_subtotal_amount,
        "paid_count": paid_count,
        "pending_count": pending_count,
        "paid_amount": paid_amount,
        "pending_amount": pending_amount,
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
    URI Format: upi://pay?pa=<upi_id>&pn=<payee_name>&am=<amount>&cu=INR&tn=<note>
    """
    from urllib.parse import quote

    distributor = invoice.distributor
    dist_profile = getattr(distributor, "distributor_profile", None)
    phone = dist_profile.phone if dist_profile and dist_profile.phone else "9876543210"

    upi_id = f"{phone}@upi"
    payee_name = distributor.get_full_name() or distributor.username
    note = f"Bill {invoice.invoice_number}"
    amount = f"{invoice.total_amount:.2f}"

    upi_uri = (
        f"upi://pay?pa={upi_id}"
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


@login_required
def invoice_detail(request, pk):
    """
    Detailed invoice view with dynamically generated verification & UPI payment QR codes.
    """
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "customer",
            "distributor"
        ),
        pk=pk,
        distributor=request.user
    )

    items = invoice.items.select_related("product").all()
    qr_code = generate_invoice_qr(invoice)
    qr_payload = get_invoice_qr_payload(invoice)
    upi_qr_code, upi_uri, upi_id = generate_upi_qr(invoice)

    return render(
        request,
        "billing/invoice_detail.html",
        {
            "invoice": invoice,
            "items": items,
            "qr_code": qr_code,
            "qr_payload": qr_payload,
            "upi_qr_code": upi_qr_code,
            "upi_uri": upi_uri,
            "upi_id": upi_id,
        }
    )

@login_required
def invoice_pdf(request, pk):
    """
    Generate and download invoice as PDF with embedded dynamic verification & UPI payment QR code.
    Only the logged-in distributor can access his own invoice.
    """
    invoice = get_object_or_404(
        Invoice.objects.select_related(
            "customer",
            "distributor",
            "distributor__distributor_profile"
        ),
        pk=pk,
        distributor=request.user
    )

    items = invoice.items.select_related("product").all()
    qr_code = generate_invoice_qr(invoice)
    upi_qr_code, upi_uri, upi_id = generate_upi_qr(invoice)

    context = {
        "invoice": invoice,
        "items": items,
        "qr_code": qr_code,
        "upi_qr_code": upi_qr_code,
        "upi_uri": upi_uri,
        "upi_id": upi_id,
    }

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
# CUSTOMER REGISTRATION API FOR DISTRIBUTOR
# ==============================================================================

@csrf_exempt
def customer_register_api(request):
    """
    REST API endpoint for registering a new Customer for a Distributor.
    
    Accepts POST requests with either JSON (application/json) or Form data
    (application/x-www-form-urlencoded, multipart/form-data).
    
    Authentication / Distributor context:
      - Authenticated session user (request.user.is_authenticated)
      - HTTP Basic Authentication header (Authorization: Basic <base64>)
      - Optional distributor identifier in payload ('distributor_id' or 'distributor_username' or 'distributor')
    
    Required Fields:
      - name: Customer full name (string, min 3 chars, max 100 chars)
      - phone: 10-digit valid phone number (digits only, length 10)
      - city: City name (string, max 50 chars)
      - state: State name (string, max 50 chars)
      - pincode: 5 or 6 digit postal pincode
      
    Optional Fields:
      - email: Valid email address format
      - address: Detailed street address (string)
      - is_active: Boolean status (default: True)
      
    Returns:
      - 201 Created: Customer registered successfully with customer details JSON
      - 400 Bad Request: Validation failure with field errors
      - 401 Unauthorized: When caller is not authenticated and no distributor is identified
      - 405 Method Not Allowed: For non-POST requests
    """
    if request.method != "POST":
        return JsonResponse({
            "status": "error",
            "message": "Method not allowed. Only POST requests are supported."
        }, status=405)

    # Parse payload (supports JSON body and Form data)
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

    # Determine distributor
    distributor = None
    if request.user.is_authenticated:
        distributor = request.user
    else:
        # Check HTTP Basic Auth Header
        auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Basic "):
            try:
                auth_decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                u, p = auth_decoded.split(":", 1)
                user = authenticate(username=u, password=p)
                if user:
                    distributor = user
            except Exception:
                pass

        # Check distributor payload fields if provided
        if not distributor:
            dist_id = data.get("distributor_id") or data.get("distributor") or data.get("distributor_username")
            if dist_id:
                if str(dist_id).isdigit():
                    distributor = User.objects.filter(pk=int(dist_id)).first()
                if not distributor:
                    distributor = User.objects.filter(username=str(dist_id)).first()
                if not distributor:
                    distributor = User.objects.filter(email=str(dist_id)).first()

    if not distributor:
        return JsonResponse({
            "status": "error",
            "message": "Authentication required. Please login or provide valid distributor credentials."
        }, status=401)

    # Extract fields
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    address = str(data.get("address", "")).strip()
    city = str(data.get("city", "")).strip()
    state = str(data.get("state", "")).strip()
    pincode = str(data.get("pincode", "")).strip()

    # is_active handling
    raw_active = data.get("is_active", True)
    if isinstance(raw_active, str):
        is_active = raw_active.lower() not in ["false", "0", "off", "no"]
    elif isinstance(raw_active, bool):
        is_active = raw_active
    else:
        is_active = bool(raw_active)

    errors = {}

    # Validation: Name
    if not name:
        errors["name"] = "Full Name is required."
    elif len(name) < 3:
        errors["name"] = "Name must contain at least 3 characters."
    elif len(name) > 100:
        errors["name"] = "Name cannot exceed 100 characters."

    # Validation: Phone
    if not phone:
        errors["phone"] = "Phone number is required."
    elif not phone.isdigit() or len(phone) != 10:
        errors["phone"] = "Please enter a valid 10-digit phone number."

    # Validation: Email
    if email:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Please enter a valid email address."

    # Validation: City
    if not city:
        errors["city"] = "City is required."
    elif len(city) > 50:
        errors["city"] = "City cannot exceed 50 characters."

    # Validation: State
    if not state:
        errors["state"] = "State is required."
    elif len(state) > 50:
        errors["state"] = "State cannot exceed 50 characters."

    # Validation: Pincode
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
# PRODUCT CRUD REST API ENDPOINTS
# ==============================================================================

@csrf_exempt
def product_api_list_create(request):
    """
    REST API endpoint for Product CRUD (List & Create).
    GET: Return JSON list of distributor's products.
    POST: Create a new product with full validations.
    """
    distributor = None
    if request.user.is_authenticated:
        distributor = request.user
    else:
        auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Basic "):
            try:
                auth_decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                u, p = auth_decoded.split(":", 1)
                user = authenticate(username=u, password=p)
                if user:
                    distributor = user
            except Exception:
                pass
        if not distributor:
            dist_id = request.GET.get("distributor_id") or request.GET.get("distributor")
            if dist_id:
                if str(dist_id).isdigit():
                    distributor = User.objects.filter(pk=int(dist_id)).first()
                if not distributor:
                    distributor = User.objects.filter(username=str(dist_id)).first()

    if not distributor:
        return JsonResponse({"status": "error", "message": "Authentication required."}, status=401)

    if request.method == "GET":
        products = Product.objects.filter(distributor=distributor).order_by("-created_at")
        data = [{
            "id": p.id,
            "name": p.name,
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
    """
    distributor = None
    if request.user.is_authenticated:
        distributor = request.user
    else:
        auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Basic "):
            try:
                auth_decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                u, p = auth_decoded.split(":", 1)
                user = authenticate(username=u, password=p)
                if user:
                    distributor = user
            except Exception:
                pass

    if not distributor:
        return JsonResponse({"status": "error", "message": "Authentication required."}, status=401)

    product = Product.objects.filter(pk=pk, distributor=distributor).first()
    if not product:
        return JsonResponse({"status": "error", "message": "Product not found or access denied."}, status=404)

    if request.method == "GET":
        return JsonResponse({
            "status": "success",
            "data": {
                "id": product.id,
                "name": product.name,
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
                "category": product.category,
                "price": str(product.price),
                "stock": product.stock,
                "gst_rate": str(product.gst_rate),
                "description": product.description,
            }
        }, status=200)

    elif request.method == "DELETE":
        p_name = product.name
        product.delete()
        return JsonResponse({"status": "success", "message": f"Product '{p_name}' deleted successfully."}, status=200)

    return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)


@login_required
def qr_decoder_view(request):
    """
    Task 47 & 48: Interactive frontend view for uploading QR code images and decoding them.
    Supports file uploads, drag & drop, and base64 preview, utilizing pyzbar and Pillow.
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
                    matched_invoice = Invoice.objects.filter(
                        invoice_number__iexact=inv_num,
                        distributor=request.user
                    ).select_related("customer").prefetch_related("items__product").first()

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
    Accepts multipart/form-data or application/json payloads with image file or base64.
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

    # Decode QR code using pyzbar/Pillow
    decode_res = decode_qr_image(image_source)

    if not decode_res.get("success"):
        return JsonResponse({
            "status": "error",
            "message": decode_res.get("error", "No QR code detected.")
        }, status=422)

    # Attach matched invoice in database if exists
    matched_data = None
    inv_data = decode_res.get("parsed", {}).get("invoice_data", {})
    inv_num = inv_data.get("invoice_number") or inv_data.get("invoice")
    if inv_num:
        qs = Invoice.objects.filter(invoice_number__iexact=inv_num)
        if request.user.is_authenticated:
            qs = qs.filter(distributor=request.user)
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