import secrets
from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from django.contrib import messages

from .models import PasswordResetOTP, DistributorProfile


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


# LOGIN

def login_view(request):

    # Already logged in
    if request.user.is_authenticated:

        if request.user.is_staff:
            return redirect("admin_dashboard")

        return redirect("distributor_dashboard")

    if request.method == "POST":

        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:

            return render(
                request,
                "accounts/login.html",
                {
                    "error": "Please enter username and password."
                }
            )

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:

            login(request, user)

            if user.is_staff:
                return redirect("admin_dashboard")

            return redirect("distributor_dashboard")

        return render(
            request,
            "accounts/login.html",
            {
                "error": "Invalid username or password."
            }
        )
    return render(
        request,
        "accounts/login.html"
    )

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

            # Delete all previous unverified OTPs
    
        PasswordResetOTP.objects.filter(
            email=email,
            is_verified=False
        ).delete()

            # Generate new OTP
    
        otp = generate_otp()

            # OTP expires after 5 minutes
    
        expires_at = (
            timezone.now()
            + timedelta(minutes=5)
        )

            # Save OTP
    
        PasswordResetOTP.objects.create(
            email=email,
            otp=otp,
            expires_at=expires_at
        )

            # Temporary testing
        # Later replace with email service
    
        print(
            f"OTP for {email}: {otp}"
        )

        return render(
            request,
            "accounts/forgot_password.html",
            {
                "email": email,
                "otp_sent": True,
                "message": "OTP sent successfully. Please check your OTP."
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
                "error": "Please enter the OTP.",
                "email": email,
                "otp_sent": True
            }
        )

    # Find latest OTP for this email

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
                "error": "Invalid or expired OTP.",
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
                "error": "Invalid OTP.",
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
            "success": "OTP verified successfully.",
            "email": email,
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

    # Email required
    if not email:

        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Please enter your email address."
            }
        )

    # Remove old OTPs

    PasswordResetOTP.objects.filter(
        email=email,
        is_verified=False
    ).delete()

    # Generate new OTP

    otp = generate_otp()

    # New expiry time

    expires_at = (
        timezone.now()
        + timedelta(minutes=5)
    )

    # Save new OTP

    PasswordResetOTP.objects.create(
        email=email,
        otp=otp,
        expires_at=expires_at
    )

    # Temporary testing
    print(
        f"RESEND OTP for {email}: {otp}"
    )

    return render(
        request,
        "accounts/forgot_password.html",
        {
            "email": email,
            "otp_sent": True,
            "message": "A new OTP has been generated successfully."
        }
    )


# ADMIN DASHBOARD

@login_required
def admin_dashboard(request):

    if not request.user.is_staff:

        return redirect(
            "distributor_dashboard"
        )

    return render(
        request,
        "admin/dashboard.html"
    )


# DISTRIBUTOR DASHBOARD

@login_required
def distributor_dashboard(request):

    if request.user.is_staff:
        return redirect("admin_dashboard")

    from billing.models import Customer
    total_customers = Customer.objects.filter(distributor=request.user).count()

    return render(
        request,
        "distributor/dashboard.html",
        {
            "total_customers": total_customers
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