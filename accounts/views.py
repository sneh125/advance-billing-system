import secrets
from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils import timezone

from .models import PasswordResetOTP, DistributorProfile


# =========================================================
# DISTRIBUTOR REGISTRATION
# =========================================================

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

            # Automatically login
            login(request, user)

            return redirect("distributor_dashboard")

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


# =========================================================
# LOGIN
# =========================================================

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


# =========================================================
# LOGOUT
# =========================================================

@login_required
def logout_view(request):

    logout(request)

    return redirect("login")


# =========================================================
# OTP GENERATOR
# =========================================================

def generate_otp():

    return str(
        secrets.randbelow(900000) + 100000
    )


# =========================================================
# FORGOT PASSWORD - SEND OTP
# =========================================================

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

        # -------------------------------------------------
        # Delete all previous unverified OTPs
        # -------------------------------------------------

        PasswordResetOTP.objects.filter(
            email=email,
            is_verified=False
        ).delete()

        # -------------------------------------------------
        # Generate new OTP
        # -------------------------------------------------

        otp = generate_otp()

        # -------------------------------------------------
        # OTP expires after 5 minutes
        # -------------------------------------------------

        expires_at = (
            timezone.now()
            + timedelta(minutes=5)
        )

        # -------------------------------------------------
        # Save OTP
        # -------------------------------------------------

        PasswordResetOTP.objects.create(
            email=email,
            otp=otp,
            expires_at=expires_at
        )

        # -------------------------------------------------
        # Temporary testing
        # Later replace with email service
        # -------------------------------------------------

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


# =========================================================
# VERIFY OTP
# =========================================================

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

    # -------------------------------------------------
    # Find latest OTP for this email
    # -------------------------------------------------

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

    # -------------------------------------------------
    # Check OTP value
    # -------------------------------------------------

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

    # -------------------------------------------------
    # Check expiry
    # -------------------------------------------------

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

    # -------------------------------------------------
    # Mark OTP as verified
    # -------------------------------------------------

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


# =========================================================
# RESEND OTP
# =========================================================

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

    # -------------------------------------------------
    # Remove old OTPs
    # -------------------------------------------------

    PasswordResetOTP.objects.filter(
        email=email,
        is_verified=False
    ).delete()

    # -------------------------------------------------
    # Generate new OTP
    # -------------------------------------------------

    otp = generate_otp()

    # -------------------------------------------------
    # New expiry time
    # -------------------------------------------------

    expires_at = (
        timezone.now()
        + timedelta(minutes=5)
    )

    # -------------------------------------------------
    # Save new OTP
    # -------------------------------------------------

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


# =========================================================
# ADMIN DASHBOARD
# =========================================================

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


# =========================================================
# DISTRIBUTOR DASHBOARD
# =========================================================

@login_required
def distributor_dashboard(request):

    if request.user.is_staff:

        return redirect(
            "admin_dashboard"
        )

    return render(
        request,
        "distributor/dashboard.html"
    )