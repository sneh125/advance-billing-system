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
from django.db import models

from .models import Customer, Product


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