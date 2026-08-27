from .utils import render_to_pdf
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

from .models import Customer, Product, Invoice, InvoiceItem
from .forms import InvoiceCreateForm


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
def customer_add(request):
    """
    Create a new customer attached to the logged-in distributor.
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

        if not state:
            errors["state"] = "State is required."

        if not pincode:
            errors["pincode"] = "Pincode is required."
        elif not pincode.isdigit() or len(pincode) < 5 or len(pincode) > 6:
            errors["pincode"] = "Please enter a valid 6-digit postal pincode."

        if not errors:
            Customer.objects.create(
                distributor=request.user,
                name=name,
                email=email if email else None,
                phone=phone,
                address=address,
                city=city,
                state=state,
                pincode=pincode,
                is_active=is_active,
            )
            messages.success(request, "Customer added successfully.")
            return redirect("customer_list")

    return render(
        request,
        "billing/customer_form.html",
        {
            "is_edit": False,
            "errors": errors,
            "form_data": form_data,
        }
    )


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

        if not state:
            errors["state"] = "State is required."

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

    query = request.GET.get("q", "").strip()

    products = Product.objects.filter(
        distributor=request.user
    ).order_by("-created_at")

    if query:
        products = products.filter(
            models.Q(name__icontains=query) |
            models.Q(category__icontains=query)
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


def generate_invoice_qr(invoice):
    """
    Generate QR code containing important invoice information.
    """
    product_count = invoice.items.count()

    qr_data = (
        f"Invoice: {invoice.invoice_number}\n"
        f"Customer: {invoice.customer.name}\n"
        f"Products: {product_count}\n"
        f"Total: ₹{invoice.total_amount}\n"
        f"Date: {invoice.created_at.strftime('%d %b %Y')}"
    )

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
    )

    buffer = BytesIO()
    qr_image.save(buffer, format="PNG")

    qr_base64 = base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")

    return qr_base64


@login_required
def invoice_detail(request, pk):
    """
    Detailed invoice view with dynamically generated QR code.
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

    return render(
        request,
        "billing/invoice_detail.html",
        {
            "invoice": invoice,
            "items": items,
            "qr_code": qr_code,
        }
    )

@login_required
def invoice_pdf(request, pk):
    """
    Generate and download invoice as PDF.
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

    context = {
        "invoice": invoice,
        "items": items,
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