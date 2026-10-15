import secrets
import json
from datetime import timedelta
from decimal import Decimal
import csv

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from django.contrib import messages

from .models import PasswordResetOTP, DistributorProfile
from .utils import send_otp_email


# DISTRIBUTOR REGISTRATION

def register_view(request):

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        # Required fields
        if not all([
            name,
            email,
            phone,
            password,
            confirm_password
        ]):
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Please fill in all required fields.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Name validation
        if len(name) < 3:
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Name must contain at least 3 characters.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Name character validation
        if not all(char.isalpha() or char.isspace() for char in name):
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Name can contain only letters and spaces.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Phone validation
        if not phone.isdigit() or len(phone) != 10:
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Please enter a valid 10-digit phone number.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Password confirmation
        if password != confirm_password:
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Passwords do not match.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Password length
        if len(password) < 8:
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Password must contain at least 8 characters.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # -----------------------------
        # Email format validation
        # -----------------------------

        try:
            validate_email(email)
        except ValidationError:
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Please enter a valid email address.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Duplicate email
        if User.objects.filter(email=email).exists():
            return render(
                request,
                "accounts/register.html",
                {
                    "error": "An account with this email already exists.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Generate unique username
        base_username = email.split("@")[0]
        username = base_username
        counter = 1

        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        # Create user
        try:

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=name
            )

            # Distributor is not admin
            user.is_staff = False
            user.is_superuser = False
            user.save()

            # Create distributor profile
            DistributorProfile.objects.create(
                user=user,
                phone=phone
            )

            # Registration success message
            messages.success(
                request,
                "Distributor account created successfully. Please login."
            )
            return redirect("login")

        except IntegrityError:

            return render(
                request,
                "accounts/register.html",
                {
                    "error": "Unable to create account. Please try again.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

    return render(
        request,
        "accounts/register.html"
    )


# ==============================================================================
# TASK 52: ADMIN AND DISTRIBUTOR LOGIN BACKEND
# ==============================================================================

def _authenticate_admin_or_distributor(identifier, password, request=None):
    """
    Core backend authentication logic for both Admin and Distributor users.
    Supports login via either username or email address, performs inactive checks,
    and returns (user, error_message, role).
    """
    identifier = (identifier or "").strip()
    if not identifier or not password:
        return None, "Please enter your username or email and password.", None

    user = None
    lookup_user = None

    # 1. Direct username authentication
    user = authenticate(request, username=identifier, password=password)

    # 2. Email-based authentication fallback
    if user is None and "@" in identifier:
        lookup_user = User.objects.filter(email__iexact=identifier).first()
        if lookup_user:
            user = authenticate(request, username=lookup_user.username, password=password)

    # 3. Case-insensitive username lookup fallback
    if user is None:
        if not lookup_user:
            lookup_user = User.objects.filter(username__iexact=identifier).first()
        if lookup_user:
            user = authenticate(request, username=lookup_user.username, password=password)

    # 4. Check for inactive user account with correct password
    if user is None and lookup_user and lookup_user.check_password(password):
        if not lookup_user.is_active:
            return None, "Your account has been deactivated. Please contact the administrator.", None

    if user is None:
        return None, "Invalid username/email or password.", None

    if not user.is_active:
        return None, "Your account has been deactivated. Please contact the administrator.", None

    # Determine user role
    role = "admin" if (user.is_staff or user.is_superuser) else "distributor"
    return user, None, role


def login_view(request):
    """
    Task 52: Admin and Distributor Login Backend Controller.
    Handles session authentication, role differentiation, next redirects, and flash alerts.
    """
    # Already logged in: redirect to respective role dashboard
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect("admin_dashboard")
        return redirect("distributor_dashboard")

    next_url = request.POST.get("next") or request.GET.get("next") or ""

    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        remember_me = request.POST.get("remember_me")

        user, error_msg, role = _authenticate_admin_or_distributor(identifier, password, request)

        if error_msg:
            return render(
                request,
                "accounts/login.html",
                {
                    "error": error_msg,
                    "username": identifier,
                    "next": next_url,
                }
            )

        # Authenticate and login to session
        login(request, user)

        # Configure session role attributes (Task 52 & Task 54)
        role_display = "Administrator" if role == "admin" else "Distributor"
        request.session["user_role"] = role
        request.session["role_display"] = role_display
        request.session["user_name"] = user.get_full_name() or user.username

        # Set session expiry if remember_me is unchecked
        if not remember_me:
            request.session.set_expiry(0)  # Expires on browser close
        else:
            request.session.set_expiry(1209600)  # 2 weeks in seconds

        messages.success(request, f"Welcome back, {user.first_name or user.username}! You are logged in as {role_display}.")

        # Safe next URL redirect
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)

        if role == "admin":
            return redirect("admin_dashboard")
        return redirect("distributor_dashboard")

    return render(
        request,
        "accounts/login.html",
        {
            "next": next_url
        }
    )


@csrf_exempt
def login_api_view(request):
    """
    Task 52: Dedicated REST API for Admin and Distributor authentication.
    Accepts JSON or form data and returns role + redirect URL.
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed. Use POST."}, status=405)

    identifier = ""
    password = ""

    if request.content_type == "application/json":
        try:
            body = json.loads(request.body.decode("utf-8"))
            identifier = body.get("username") or body.get("email") or ""
            password = body.get("password") or ""
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON format."}, status=400)
    else:
        identifier = request.POST.get("username") or request.POST.get("email") or ""
        password = request.POST.get("password") or ""

    user, error_msg, role = _authenticate_admin_or_distributor(identifier, password, request)

    if error_msg:
        return JsonResponse({
            "status": "error",
            "message": error_msg
        }, status=401)

    login(request, user)
    request.session["user_role"] = role
    request.session["role_display"] = "Administrator" if role == "admin" else "Distributor"

    redirect_url = "/admin-dashboard/" if role == "admin" else "/distributor/dashboard/"

    return JsonResponse({
        "status": "success",
        "message": f"Login successful as {role.capitalize()}.",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "role": role,
            "is_staff": user.is_staff,
        },
        "redirect_url": redirect_url
    }, status=200)

# LOGOUT

@login_required
def logout_view(request):

    logout(request)

    return redirect("login")

# OTP GENERATOR

def generate_otp():

    return str(
        secrets.randbelow(900000) + 100000
    )

# FORGOT PASSWORD - SEND OTP

def forgot_password(request):

    if request.method == "POST":

        email = request.POST.get(
            "email",
            ""
        ).strip().lower()

        # Email required
        if not email:
            return render(
                request,
                "accounts/forgot_password.html",
                {
                    "error": "Please enter your email address."
                }
            )

        # Check if account exists
        if not User.objects.filter(email=email).exists():
            return render(
                request,
                "accounts/forgot_password.html",
                {
                    "error": "No account found with this email address.",
                    "email": email
                }
            )

        # Delete all previous unverified OTPs
        PasswordResetOTP.objects.filter(
            email=email,
            is_verified=False
        ).delete()

        # Generate new OTP (expires in 5 minutes)
        otp = generate_otp()
        expires_at = timezone.now() + timedelta(minutes=5)

        PasswordResetOTP.objects.create(
            email=email,
            otp=otp,
            expires_at=expires_at
        )

        # Send OTP email
        user_obj = User.objects.filter(email=email).first()
        user_name = user_obj.first_name if user_obj else "User"
        send_otp_email(email=email, otp=otp, user_name=user_name, is_admin=False)

        print(f"[AUTH] Generated OTP for {email}: {otp}")

        return render(
            request,
            "accounts/forgot_password.html",
            {
                "email": email,
                "otp_sent": True,
                "message": f"A 6-digit verification code has been generated for {email}."
            }
        )

    return render(
        request,
        "accounts/forgot_password.html"
    )


# VERIFY OTP

def verify_otp(request):

    if request.method != "POST":
        return redirect("forgot_password")

    email = request.POST.get(
        "email",
        ""
    ).strip().lower()

    otp = request.POST.get(
        "otp",
        ""
    ).strip()

    # Required fields
    if not email or not otp:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Please enter the 6-digit OTP.",
                "email": email,
                "otp_sent": True
            }
        )

    # Find latest unverified OTP for this email
    otp_record = PasswordResetOTP.objects.filter(
        email=email,
        is_verified=False
    ).order_by(
        "-created_at"
    ).first()

    # No OTP found
    if otp_record is None:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "No active OTP request found. Please request a new OTP.",
                "email": email,
                "otp_sent": True
            }
        )

    # Check OTP value
    if otp_record.otp != otp:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Invalid OTP. Please check the code and try again.",
                "email": email,
                "otp_sent": True
            }
        )

    # Check expiry
    if not otp_record.is_valid():
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "OTP has expired. Please request a new OTP.",
                "email": email,
                "otp_sent": True
            }
        )

    # Mark OTP as verified
    otp_record.is_verified = True
    otp_record.save(
        update_fields=["is_verified"]
    )

    return render(
        request,
        "accounts/forgot_password.html",
        {
            "success": "OTP verified successfully. Please enter your new password.",
            "email": email,
            "otp_sent": True,
            "otp_verified": True
        }
    )


# RESEND OTP

def resend_otp(request):

    if request.method != "POST":
        return redirect("forgot_password")

    email = request.POST.get(
        "email",
        ""
    ).strip().lower()

    if not email:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Please enter your email address."
            }
        )

    if not User.objects.filter(email=email).exists():
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "No account found with this email address."
            }
        )

    PasswordResetOTP.objects.filter(
        email=email,
        is_verified=False
    ).delete()

    otp = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=5)

    PasswordResetOTP.objects.create(
        email=email,
        otp=otp,
        expires_at=expires_at
    )

    # Send OTP email
    user_obj = User.objects.filter(email=email).first()
    user_name = user_obj.first_name if user_obj else "User"
    send_otp_email(email=email, otp=otp, user_name=user_name, is_admin=False)

    print(f"[AUTH] RESEND OTP for {email}: {otp}")

    return render(
        request,
        "accounts/forgot_password.html",
        {
            "email": email,
            "otp_sent": True,
            "message": f"A new 6-digit verification code has been sent to {email}."
        }
    )


# RESET PASSWORD

def reset_password(request):

    if request.method != "POST":
        return redirect("forgot_password")

    email = request.POST.get("email", "").strip().lower()
    password = request.POST.get("password", "")
    confirm_password = request.POST.get("confirm_password", "")

    if not email or not password or not confirm_password:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "All fields are required to reset password.",
                "email": email,
                "otp_sent": True,
                "otp_verified": True
            }
        )

    # Check verified OTP session
    otp_record = PasswordResetOTP.objects.filter(
        email=email,
        is_verified=True
    ).order_by("-created_at").first()

    if not otp_record:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Verification session expired. Please request a new OTP.",
                "email": email
            }
        )

    if len(password) < 8:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Password must contain at least 8 characters.",
                "email": email,
                "otp_sent": True,
                "otp_verified": True
            }
        )

    if password != confirm_password:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Passwords do not match.",
                "email": email,
                "otp_sent": True,
                "otp_verified": True
            }
        )

    user = User.objects.filter(email=email).first()
    if not user:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "No account associated with this email address.",
                "email": email
            }
        )

    # Update password
    user.set_password(password)
    user.save()

    # Clear OTP records
    PasswordResetOTP.objects.filter(email=email).delete()

    messages.success(
        request,
        "Password has been reset successfully! Please sign in with your new password."
    )
    return redirect("login")


# ADMIN DASHBOARD

@login_required
def admin_dashboard(request):
    """
    Dedicated Admin Dashboard with Comprehensive System Reports & Analytics Suite.
    Aggregates real-time financial metrics, GST tax audit, distributor performance summaries,
    inventory catalog valuation, and CSV export capability.
    """
    if not request.user.is_staff:
        return redirect("distributor_dashboard")

    from billing.models import Customer, Product, Invoice

    period = request.GET.get("period", "all").strip().lower()
    now = timezone.now()

    invoices_qs = Invoice.objects.select_related("customer", "distributor").all()
    customers_qs = Customer.objects.select_related("distributor").all()
    products_qs = Product.objects.select_related("distributor").all()
    distributors_qs = User.objects.filter(is_staff=False).select_related("distributor_profile").order_by("-date_joined")

    # Time-based filtering
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        invoices_filtered = invoices_qs.filter(invoice_date__gte=start_date)
    elif period == "week":
        start_date = now - timedelta(days=7)
        invoices_filtered = invoices_qs.filter(invoice_date__gte=start_date)
    elif period == "month":
        start_date = now - timedelta(days=30)
        invoices_filtered = invoices_qs.filter(invoice_date__gte=start_date)
    else:
        period = "all"
        invoices_filtered = invoices_qs

    # Optional CSV Export
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="admin_sales_report_{period}_{now.strftime("%Y%m%d")}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Invoice Number", "Date", "Distributor", "Customer", "Subtotal (INR)", "GST (INR)", "Total Amount (INR)", "Status"])
        for inv in invoices_filtered.order_by("-created_at"):
            writer.writerow([
                inv.invoice_number,
                inv.invoice_date.strftime("%Y-%m-%d %H:%M"),
                inv.distributor.username,
                inv.customer.name,
                f"{inv.subtotal:.2f}",
                f"{inv.gst_amount:.2f}",
                f"{inv.total_amount:.2f}",
                inv.status
            ])
        return response

    # 1. Financial & Revenue Report Aggregations
    total_invoices_count = invoices_filtered.count()
    gross_revenue = sum(inv.total_amount for inv in invoices_filtered)
    total_tax_collected = sum(inv.gst_amount for inv in invoices_filtered)
    net_taxable_subtotal = sum(inv.subtotal for inv in invoices_filtered)

    paid_invoices_qs = invoices_filtered.filter(status__iexact="Paid")
    paid_invoices_count = paid_invoices_qs.count()
    paid_revenue = sum(inv.total_amount for inv in paid_invoices_qs)

    pending_invoices_qs = invoices_filtered.filter(status__iexact="Pending")
    pending_invoices_count = pending_invoices_qs.count()
    pending_revenue = sum(inv.total_amount for inv in pending_invoices_qs)

    avg_invoice_value = (gross_revenue / total_invoices_count) if total_invoices_count > 0 else Decimal("0.00")

    # Ratio calculation for paid vs pending progress bar
    paid_percentage = 0
    pending_percentage = 0
    if gross_revenue > 0:
        paid_percentage = round((float(paid_revenue) / float(gross_revenue)) * 100, 1)
        pending_percentage = round((float(pending_revenue) / float(gross_revenue)) * 100, 1)

    # 2. Distributor Performance Report
    distributor_reports = []
    for dist in distributors_qs:
        dist_inv = invoices_filtered.filter(distributor=dist)
        dist_rev = sum(i.total_amount for i in dist_inv)
        dist_cust_count = customers_qs.filter(distributor=dist).count()
        dist_prod_count = products_qs.filter(distributor=dist).count()
        phone = dist.distributor_profile.phone if hasattr(dist, "distributor_profile") else ""
        distributor_reports.append({
            "user": dist,
            "phone": phone,
            "invoice_count": dist_inv.count(),
            "revenue": dist_rev,
            "customer_count": dist_cust_count,
            "product_count": dist_prod_count,
            "is_active": dist.is_active,
        })
    distributor_reports.sort(key=lambda x: x["revenue"], reverse=True)

    # 3. Inventory & Catalog Stock Health
    total_products_count = products_qs.count()
    low_stock_products_count = products_qs.filter(stock__gt=0, stock__lte=10).count()
    out_of_stock_products_count = products_qs.filter(stock=0).count()
    in_stock_products_count = products_qs.filter(stock__gt=10).count()
    total_inventory_valuation = sum((p.price * p.stock) for p in products_qs)

    # 4. Customer Directory Totals
    total_customers_count = customers_qs.count()
    active_customers_count = customers_qs.filter(is_active=True).count()

    # 5. Recent Invoices Ledger (latest 10)
    recent_invoices = invoices_filtered.order_by("-created_at")[:10]

    context = {
        "period": period,
        # Financial Reports
        "gross_revenue": gross_revenue,
        "total_tax_collected": total_tax_collected,
        "net_taxable_subtotal": net_taxable_subtotal,
        "total_invoices_count": total_invoices_count,
        "paid_invoices_count": paid_invoices_count,
        "paid_revenue": paid_revenue,
        "pending_invoices_count": pending_invoices_count,
        "pending_revenue": pending_revenue,
        "avg_invoice_value": avg_invoice_value,
        "paid_percentage": paid_percentage,
        "pending_percentage": pending_percentage,
        # System Overview KPIs
        "total_distributors_count": distributors_qs.count(),
        "active_distributors_count": distributors_qs.filter(is_active=True).count(),
        "total_customers_count": total_customers_count,
        "active_customers_count": active_customers_count,
        # Stock & Inventory
        "total_products_count": total_products_count,
        "low_stock_products_count": low_stock_products_count,
        "out_of_stock_products_count": out_of_stock_products_count,
        "in_stock_products_count": in_stock_products_count,
        "total_inventory_valuation": total_inventory_valuation,
        # Detailed Tables
        "distributor_reports": distributor_reports,
        "recent_invoices": recent_invoices,
    }

    return render(request, "admin/dashboard.html", context)



# DISTRIBUTOR DASHBOARD

@login_required
def distributor_dashboard(request):

    if request.user.is_staff:
        return redirect("admin_dashboard")

    from billing.models import Customer, Product, Invoice
    total_customers = Customer.objects.filter(distributor=request.user).count()
    total_products = Product.objects.filter(distributor=request.user).count()
    invoices_qs = Invoice.objects.filter(distributor=request.user)
    total_invoices = invoices_qs.count()
    total_billed = sum(inv.total_amount for inv in invoices_qs)

    return render(
        request,
        "distributor/dashboard.html",
        {
            "total_customers": total_customers,
            "total_products": total_products,
            "total_invoices": total_invoices,
            "total_billed": total_billed,
        }
    )


@login_required
def distributor_profile(request):

    if request.user.is_staff:
        return redirect("admin_dashboard")

    # get_or_create: manually created users jinka profile nahi hai unke liye auto create karo
    profile, _ = DistributorProfile.objects.get_or_create(
        user=request.user,
        defaults={"phone": ""}
    )

    if request.method == "POST":

        action = request.POST.get("action", "")

        if action == "update_profile":

            name  = request.POST.get("name", "").strip()
            email = request.POST.get("email", "").strip().lower()
            phone = request.POST.get("phone", "").strip()

            # Validate name
            if not name or len(name) < 3:
                return render(request, "distributor/profile.html", {
                    "profile": profile,
                    "error": "Name must be at least 3 characters."
                })

            # Validate phone
            if not phone.isdigit() or len(phone) != 10:
                return render(request, "distributor/profile.html", {
                    "profile": profile,
                    "error": "Please enter a valid 10-digit phone number."
                })

            # Validate email
            if not email:
                return render(request, "distributor/profile.html", {
                    "profile": profile,
                    "error": "Please enter a valid email address."
                })

            # Check email duplicate (exclude current user)
            if User.objects.filter(
                email=email
            ).exclude(pk=request.user.pk).exists():
                return render(request, "distributor/profile.html", {
                    "profile": profile,
                    "error": "This email is already used by another account."
                })

            # Save changes
            request.user.first_name = name
            request.user.email = email
            request.user.save()

            profile.phone = phone
            profile.save()

            # Refresh profile
            profile.refresh_from_db()

            return render(request, "distributor/profile.html", {
                "profile": profile,
                "success": "Profile updated successfully!"
            })

    return render(
        request,
        "distributor/profile.html",
        {
            "profile": profile
        }
    )

@login_required
def update_profile(request):

    user = request.user
    profile = user.distributor_profile

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()

        # Required fields
        if not name or not email or not phone:
            return render(
                request,
                "distributor/update_profile.html",
                {
                    "error": "All fields are required.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Name validation
        if len(name) < 3:
            return render(
                request,
                "distributor/update_profile.html",
                {
                    "error": "Name must contain at least 3 characters.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Phone validation
        if not phone.isdigit() or len(phone) != 10:
            return render(
                request,
                "distributor/update_profile.html",
                {
                    "error": "Please enter a valid 10-digit phone number.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Email duplicate check
        if User.objects.filter(
            email=email
        ).exclude(id=user.id).exists():

            return render(
                request,
                "distributor/update_profile.html",
                {
                    "error": "This email is already registered.",
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        # Update User
        user.first_name = name
        user.email = email
        user.save()

        # Update Distributor Profile
        profile.phone = phone
        profile.save()

        messages.success(
            request,
            "Profile updated successfully."
        )

        return redirect("distributor_profile")

    return render(
        request,
        "distributor/update_profile.html",
        {
            "name": user.first_name,
            "email": user.email,
            "phone": profile.phone,
        }
    )


# ==============================================================================
# ADMIN USER REGISTRATION API ENDPOINT
# ==============================================================================

@csrf_exempt
def admin_register_api(request):
    """
    REST API endpoint for registering Admin users.
    Accepts JSON or Form POST data:
        - username (required, unique, min 3 chars)
        - email (required, unique, valid email format)
        - password (required, min 8 chars)
        - first_name / name (optional, admin full name)
    Creates User with is_staff=True, is_superuser=True.
    Returns:
        HTTP 201 Created with JSON on success
        HTTP 400 Bad Request on validation failure
        HTTP 405 Method Not Allowed for non-POST
    """
    if request.method != "POST":
        return JsonResponse({
            "status": "error",
            "message": "Method not allowed. Only POST requests are supported."
        }, status=405)

    # Parse payload (supports both application/json and form-data)
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

    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    first_name = str(data.get("name", "") or data.get("first_name", "")).strip()

    errors = {}

    # 1. Username validation
    if not username:
        errors["username"] = "Username is required."
    elif len(username) < 3:
        errors["username"] = "Username must be at least 3 characters long."
    elif User.objects.filter(username=username).exists():
        errors["username"] = "A user with this username already exists."

    # 2. Email validation
    if not email:
        errors["email"] = "Email address is required."
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Please enter a valid email address."
        if User.objects.filter(email=email).exists():
            errors["email"] = "An account with this email already exists."

    # 3. Password validation
    if not password:
        errors["password"] = "Password is required."
    elif len(password) < 8:
        errors["password"] = "Password must be at least 8 characters long."

    if errors:
        return JsonResponse({
            "status": "error",
            "message": "Validation failed.",
            "errors": errors
        }, status=400)

    try:
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name
        )
        user.is_staff = True
        user.is_superuser = True
        user.save()

        return JsonResponse({
            "status": "success",
            "message": "Admin user registered successfully.",
            "data": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
            }
        }, status=201)

    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": f"Server error creating admin account: {str(e)}"
        }, status=500)


# ==============================================================================
# ADMIN FRONTEND REGISTRATION VIEW
# ==============================================================================

def admin_register_view(request):
    """
    Frontend view for Admin registration.
    Renders admin_register.html on GET.
    Processes submission, validates input, and provisions Admin user on POST.
    """
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("admin_dashboard")
        return redirect("distributor_dashboard")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        context = {
            "name": name,
            "username": username,
            "email": email,
        }

        # Required fields validation
        if not all([name, username, email, password, confirm_password]):
            context["error"] = "Please fill in all required fields."
            return render(request, "accounts/admin_register.html", context)

        # Name length validation
        if len(name) < 3:
            context["error"] = "Full name must be at least 3 characters long."
            return render(request, "accounts/admin_register.html", context)

        # Username validation
        if len(username) < 3:
            context["error"] = "Username must be at least 3 characters long."
            return render(request, "accounts/admin_register.html", context)

        if User.objects.filter(username=username).exists():
            context["error"] = "An account with this username already exists."
            return render(request, "accounts/admin_register.html", context)

        # Email validation
        try:
            validate_email(email)
        except ValidationError:
            context["error"] = "Please enter a valid email address."
            return render(request, "accounts/admin_register.html", context)

        if User.objects.filter(email=email).exists():
            context["error"] = "An account with this email already exists."
            return render(request, "accounts/admin_register.html", context)

        # Password validation
        if len(password) < 8:
            context["error"] = "Password must be at least 8 characters long."
            return render(request, "accounts/admin_register.html", context)

        if password != confirm_password:
            context["error"] = "Passwords do not match."
            return render(request, "accounts/admin_register.html", context)

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=name
            )
            user.is_staff = True
            user.is_superuser = True
            user.save()

            messages.success(
                request,
                f"Administrator account '{username}' registered successfully! Please sign in."
            )
            return redirect("login")

        except Exception as e:
            context["error"] = f"Unable to create admin account: {str(e)}"
            return render(request, "accounts/admin_register.html", context)

    return render(request, "accounts/admin_register.html")


# ==============================================================================
# ADMIN PASSWORD RECOVERY BACKEND LOGIC
# ==============================================================================

@csrf_exempt
def admin_forgot_password(request):
    """
    Backend logic for Admin password recovery - Step 1: Request OTP.
    Ensures the account has is_staff=True (Admin privilege verification).
    """
    if request.method == "POST":
        data = {}
        if request.content_type == "application/json" and request.body:
            try:
                data = json.loads(request.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JsonResponse({"status": "error", "message": "Invalid JSON."}, status=400)
        else:
            data = request.POST.dict()

        email = str(data.get("email", "")).strip().lower()

        if not email:
            error_msg = "Please enter administrator email address."
            if request.content_type == "application/json":
                return JsonResponse({"status": "error", "message": error_msg}, status=400)
            return render(request, "accounts/forgot_password.html", {"error": error_msg, "is_admin": True})

        # Check if user exists and verify admin role (is_staff=True)
        user = User.objects.filter(email=email).first()
        if not user:
            error_msg = "No administrator account found with this email address."
            if request.content_type == "application/json":
                return JsonResponse({"status": "error", "message": error_msg}, status=404)
            return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "is_admin": True})

        if not user.is_staff:
            error_msg = "This email does not belong to an Administrator account. Access denied."
            if request.content_type == "application/json":
                return JsonResponse({"status": "error", "message": error_msg}, status=403)
            return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "is_admin": True})

        # Invalidate previous unverified OTPs
        PasswordResetOTP.objects.filter(email=email, is_verified=False).delete()

        # Generate new 6-digit OTP (5-minute expiry)
        otp = generate_otp()
        expires_at = timezone.now() + timedelta(minutes=5)
        PasswordResetOTP.objects.create(email=email, otp=otp, expires_at=expires_at)

        # Send OTP email for Administrator
        send_otp_email(email=email, otp=otp, user_name=user.first_name, is_admin=True)

        print(f"[AUTH-ADMIN] Generated Password Recovery OTP for Admin {email}: {otp}")

        success_msg = f"A 6-digit admin verification code has been generated for {email}."
        if request.content_type == "application/json":
            return JsonResponse({
                "status": "success",
                "message": success_msg,
                "email": email,
                "otp_sent": True
            }, status=200)

        return render(request, "accounts/forgot_password.html", {
            "email": email,
            "otp_sent": True,
            "is_admin": True,
            "message": success_msg
        })

    return render(request, "accounts/forgot_password.html", {"is_admin": True})


@csrf_exempt
def admin_verify_otp(request):
    """
    Backend logic for Admin password recovery - Step 2: Verify OTP.
    Validates OTP matches and is not expired, ensuring admin role.
    """
    if request.method != "POST":
        return redirect("admin_forgot_password")

    data = {}
    if request.content_type == "application/json" and request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"status": "error", "message": "Invalid JSON."}, status=400)
    else:
        data = request.POST.dict()

    email = str(data.get("email", "")).strip().lower()
    otp = str(data.get("otp", "")).strip()

    if not email or not otp:
        error_msg = "Both administrator email and OTP code are required."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    # Verify admin role
    admin_user = User.objects.filter(email=email, is_staff=True).first()
    if not admin_user:
        error_msg = "Administrator privilege verification failed for this account."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=403)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    otp_record = PasswordResetOTP.objects.filter(email=email, is_verified=False).order_by("-created_at").first()

    if not otp_record or otp_record.otp != otp:
        error_msg = "Invalid OTP code. Please verify and try again."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    if not otp_record.is_valid():
        error_msg = "OTP has expired. Please request a new code."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    # Mark OTP as verified
    otp_record.is_verified = True
    otp_record.save(update_fields=["is_verified"])

    success_msg = "Administrator OTP verified successfully. You may now reset your password."
    if request.content_type == "application/json":
        return JsonResponse({
            "status": "success",
            "message": success_msg,
            "email": email,
            "otp_verified": True
        }, status=200)

    return render(request, "accounts/forgot_password.html", {
        "email": email,
        "otp_sent": True,
        "otp_verified": True,
        "is_admin": True,
        "success": success_msg
    })


@csrf_exempt
def admin_reset_password(request):
    """
    Backend logic for Admin password recovery - Step 3: Set New Password.
    Verifies valid verified OTP session, updates admin password, clears OTP records.
    """
    if request.method != "POST":
        return redirect("admin_forgot_password")

    data = {}
    if request.content_type == "application/json" and request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"status": "error", "message": "Invalid JSON."}, status=400)
    else:
        data = request.POST.dict()

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    confirm_password = str(data.get("confirm_password", ""))

    if not email or not password or not confirm_password:
        error_msg = "All fields are required to reset administrator password."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "otp_verified": True, "is_admin": True})

    # Verify that a verified OTP session exists
    otp_record = PasswordResetOTP.objects.filter(email=email, is_verified=True).order_by("-created_at").first()
    if not otp_record:
        error_msg = "Verification session expired. Please request a new OTP."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "is_admin": True})

    # Validate admin user
    admin_user = User.objects.filter(email=email, is_staff=True).first()
    if not admin_user:
        error_msg = "Administrator account verification failed."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=403)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "is_admin": True})

    if len(password) < 8:
        error_msg = "Password must contain at least 8 characters."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "otp_verified": True, "is_admin": True})

    if password != confirm_password:
        error_msg = "Passwords do not match."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "otp_verified": True, "is_admin": True})

    # Set new password
    admin_user.set_password(password)
    admin_user.save()

    # Clear OTP records
    PasswordResetOTP.objects.filter(email=email).delete()

    success_msg = f"Administrator password for '{admin_user.username}' has been updated successfully!"
    if request.content_type == "application/json":
        return JsonResponse({
            "status": "success",
            "message": success_msg
        }, status=200)

    messages.success(request, success_msg)
    return redirect("login")

