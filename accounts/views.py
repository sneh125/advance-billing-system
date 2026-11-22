import base64
import csv
import hmac
import json
import re
import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt

from .decorators import admin_required
from .models import Admin, DistributorProfile, PasswordResetOTP, RegistrationOTP
from .utils import sanitize_csv_cell, send_otp_email, send_otp_email_with_status


GSTIN_REGEX = re.compile(r"^[0-9A-Z]{15}$")


def _authenticate_basic_header(request):
    """Extract and authenticate a user from HTTP Basic Authorization header if present."""
    auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            username, password = decoded.split(":", 1)
            return authenticate(request, username=username, password=password)
        except Exception:
            return None
    return None


def _validate_profile_business_fields(gstin, upi_id):
    """Validate optional GSTIN and UPI VPA fields for distributor profiles."""
    if gstin and not GSTIN_REGEX.match(gstin.upper()):
        return "Please enter a valid 15-character alphanumeric GSTIN (e.g., 24ABCDE1234F1Z5)."
    if upi_id and ("@" not in upi_id or " " in upi_id or len(upi_id) < 5):
        return "Please enter a valid UPI ID (e.g., business@upi)."
    return None


# DISTRIBUTOR REGISTRATION (WITH EMAIL OTP VERIFICATION)

def register_view(request):
    """
    Step 1 of Distributor Registration:
    Validates registration details, stores pending profile with pre-hashed password in session,
    dispatches a 6-digit Email Verification OTP, and transitions to Step 2 (OTP entry).
    """
    if request.GET.get("reset") == "1":
        pending = request.session.pop("pending_registration", None) or {}
        return render(
            request,
            "accounts/register.html",
            {
                "name": pending.get("name", ""),
                "email": pending.get("email", ""),
                "phone": pending.get("phone", ""),
            }
        )

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        form_ctx = {
            "name": name,
            "email": email,
            "phone": phone,
        }

        # Required fields
        if not all([name, email, phone, password, confirm_password]):
            form_ctx["error"] = "Please fill in all required fields."
            return render(request, "accounts/register.html", form_ctx)

        # Name validation
        if len(name) < 3:
            form_ctx["error"] = "Name must contain at least 3 characters."
            return render(request, "accounts/register.html", form_ctx)

        # Name character validation
        if not all(char.isalpha() or char.isspace() for char in name):
            form_ctx["error"] = "Name can contain only letters and spaces."
            return render(request, "accounts/register.html", form_ctx)

        # Phone validation
        if not phone.isdigit() or len(phone) != 10:
            form_ctx["error"] = "Please enter a valid 10-digit phone number."
            return render(request, "accounts/register.html", form_ctx)

        # Password confirmation
        if password != confirm_password:
            form_ctx["error"] = "Passwords do not match."
            return render(request, "accounts/register.html", form_ctx)

        # Password length & Django strength validation
        if len(password) < 8:
            form_ctx["error"] = "Password must contain at least 8 characters."
            return render(request, "accounts/register.html", form_ctx)

        try:
            validate_password(password)
        except ValidationError as exc:
            form_ctx["error"] = exc.messages[0]
            return render(request, "accounts/register.html", form_ctx)

        # Email format validation
        try:
            validate_email(email)
        except ValidationError:
            form_ctx["error"] = "Please enter a valid email address."
            return render(request, "accounts/register.html", form_ctx)

        # Duplicate email
        if User.objects.filter(email=email).exists():
            form_ctx["error"] = "An account with this email already exists."
            return render(request, "accounts/register.html", form_ctx)

        # Generate Registration OTP (expires in 5 minutes)
        RegistrationOTP.objects.filter(email=email, is_verified=False).delete()
        otp = generate_otp()
        expires_at = timezone.now() + timedelta(minutes=5)
        otp_obj = RegistrationOTP.objects.create(
            email=email,
            otp=otp,
            expires_at=expires_at,
        )

        sent_ok, err_msg = send_otp_email_with_status(
            email=email,
            otp=otp,
            user_name=name,
            is_admin=False,
            purpose="registration",
        )
        if not sent_ok:
            otp_obj.delete()
            form_ctx["error"] = (
                f"Failed to send verification OTP email to {email}. "
                f"Please check SMTP settings in .env ({err_msg})."
            )
            return render(request, "accounts/register.html", form_ctx)

        # Store pending registration securely in session (password pre-hashed, never plaintext)
        request.session["pending_registration"] = {
            "name": name,
            "email": email,
            "phone": phone,
            "password_hash": make_password(password),
        }

        return render(
            request,
            "accounts/register.html",
            {
                "otp_step": True,
                "name": name,
                "email": email,
                "phone": phone,
                "message": f"A 6-digit verification OTP has been sent to {email}. Enter it below to complete registration.",
            }
        )

    return render(request, "accounts/register.html")


def register_verify_otp(request):
    """
    Step 2 of Distributor Registration:
    Verifies the 6-digit RegistrationOTP and creates User + DistributorProfile atomically.
    """
    if request.method != "POST":
        return redirect("register")

    pending = request.session.get("pending_registration")
    if not pending:
        messages.error(request, "Registration session expired. Please fill in your details again.")
        return redirect("register")

    email = (pending.get("email") or "").strip().lower()
    name = (pending.get("name") or "").strip()
    phone = (pending.get("phone") or "").strip()
    password_hash = pending.get("password_hash") or ""
    otp = request.POST.get("otp", "").strip()

    step2_ctx = {
        "otp_step": True,
        "name": name,
        "email": email,
        "phone": phone,
    }

    if not otp or len(otp) != 6 or not otp.isdigit():
        step2_ctx["error"] = "Please enter the valid 6-digit verification OTP."
        return render(request, "accounts/register.html", step2_ctx)

    otp_record = RegistrationOTP.objects.filter(
        email=email,
        is_verified=False
    ).order_by("-created_at").first()

    if otp_record is None:
        step2_ctx["error"] = "No active verification OTP found. Please resend OTP."
        return render(request, "accounts/register.html", step2_ctx)

    if otp_record.failed_attempts >= RegistrationOTP.MAX_ATTEMPTS:
        otp_record.delete()
        step2_ctx["error"] = "Too many failed OTP attempts. Please request a new OTP."
        return render(request, "accounts/register.html", step2_ctx)

    if not hmac.compare_digest(otp_record.otp, otp):
        otp_record.failed_attempts += 1
        otp_record.save(update_fields=["failed_attempts"])
        remaining = RegistrationOTP.MAX_ATTEMPTS - otp_record.failed_attempts
        if remaining <= 0:
            otp_record.delete()
            step2_ctx["error"] = "Too many failed OTP attempts. Please request a new OTP."
        else:
            step2_ctx["error"] = f"Invalid OTP code. Please try again ({remaining} attempts left)."
        return render(request, "accounts/register.html", step2_ctx)

    if timezone.now() > otp_record.expires_at:
        step2_ctx["error"] = "Verification OTP has expired. Please click Resend OTP."
        return render(request, "accounts/register.html", step2_ctx)

    if User.objects.filter(email=email).exists():
        request.session.pop("pending_registration", None)
        RegistrationOTP.objects.filter(email=email).delete()
        return render(
            request,
            "accounts/register.html",
            {"error": "An account with this email already exists. Please sign in."}
        )

    try:
        with transaction.atomic():
            base_username = email.split("@")[0]
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User(
                username=username,
                email=email,
                first_name=name,
                password=password_hash,
                is_staff=False,
                is_superuser=False,
                is_active=True,
            )
            user.save()

            DistributorProfile.objects.create(
                user=user,
                phone=phone,
            )

            RegistrationOTP.objects.filter(email=email).delete()

        request.session.pop("pending_registration", None)
        messages.success(
            request,
            "Email verified! Distributor account created successfully. Please login."
        )
        return redirect("login")

    except IntegrityError:
        step2_ctx["error"] = "Unable to create account. Please try again."
        return render(request, "accounts/register.html", step2_ctx)


def register_resend_otp(request):
    """
    Resends a fresh 6-digit Registration OTP for the pending email in session,
    enforcing a 3-resend / 15-minute sliding window rate limit.
    """
    if request.method != "POST":
        return redirect("register")

    pending = request.session.get("pending_registration")
    if not pending:
        messages.error(request, "Registration session expired. Please fill in your details again.")
        return redirect("register")

    email = (pending.get("email") or "").strip().lower()
    name = (pending.get("name") or "").strip()
    phone = (pending.get("phone") or "").strip()

    now_ts = int(timezone.now().timestamp())
    window_secs = 15 * 60
    max_resends = 3
    resend_history = request.session.get("reg_otp_resend_history", {})
    timestamps = [
        ts for ts in resend_history.get(email, [])
        if isinstance(ts, (int, float)) and (now_ts - ts) < window_secs
    ]
    if len(timestamps) >= max_resends:
        return render(
            request,
            "accounts/register.html",
            {
                "otp_step": True,
                "name": name,
                "email": email,
                "phone": phone,
                "error": "Too many OTP resend requests. Please wait 15 minutes before trying again.",
            }
        )
    timestamps.append(now_ts)
    resend_history[email] = timestamps
    request.session["reg_otp_resend_history"] = resend_history

    RegistrationOTP.objects.filter(email=email, is_verified=False).delete()
    otp = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=5)
    otp_obj = RegistrationOTP.objects.create(email=email, otp=otp, expires_at=expires_at)

    sent_ok, err_msg = send_otp_email_with_status(
        email=email,
        otp=otp,
        user_name=name,
        is_admin=False,
        purpose="registration",
    )
    if not sent_ok:
        otp_obj.delete()
        return render(
            request,
            "accounts/register.html",
            {
                "otp_step": True,
                "name": name,
                "email": email,
                "phone": phone,
                "error": f"Could not send verification OTP email. Check SMTP settings in .env ({err_msg}).",
            }
        )

    return render(
        request,
        "accounts/register.html",
        {
            "otp_step": True,
            "name": name,
            "email": email,
            "phone": phone,
            "message": f"A new 6-digit verification OTP has been sent to {email}.",
        }
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


def login_view(request, forced_role=None):
    """
    Task 52: Admin and Distributor Login Backend Controller.
    Handles session authentication, role differentiation, next redirects, and flash alerts.
    Supports optional forced_role ('admin' or 'distributor') for dedicated role login routes.
    """
    # Allow explicit role switch via ?role=admin or ?role=distributor
    requested_role_param = (forced_role or request.GET.get("role", "")).strip().lower()
    if request.user.is_authenticated:
        if requested_role_param in ("admin", "distributor"):
            if forced_role == "admin" and (request.user.is_staff or request.user.is_superuser):
                return redirect("admin_dashboard")
            if forced_role == "distributor" and not (request.user.is_staff or request.user.is_superuser):
                return redirect("distributor_dashboard")
            logout(request)
        else:
            if request.user.is_staff or request.user.is_superuser:
                return redirect("admin_dashboard")
            return redirect("distributor_dashboard")

    next_url = request.POST.get("next") or request.GET.get("next") or ""

    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        remember_me = request.POST.get("remember_me")
        selected_role = (forced_role or request.POST.get("selected_role", "")).strip().lower()

        user, error_msg, role = _authenticate_admin_or_distributor(identifier, password, request)

        if not error_msg and selected_role == "admin" and role != "admin":
            return render(
                request,
                "accounts/login.html",
                {
                    "error": (
                        f"Account '{user.username}' is a Distributor account without Administrator privileges. "
                        "Please sign in with an authorized Administrator account."
                    ),
                    "username": identifier,
                    "selected_role": "admin",
                    "next": next_url,
                }
            )

        if not error_msg and forced_role == "distributor" and role == "admin":
            return render(
                request,
                "accounts/login.html",
                {
                    "error": (
                        f"Account '{user.username}' is an Administrator account. "
                        "Please sign in via the Administrator Login portal."
                    ),
                    "username": identifier,
                    "selected_role": "distributor",
                    "next": next_url,
                }
            )

        if error_msg:
            return render(
                request,
                "accounts/login.html",
                {
                    "error": error_msg,
                    "username": identifier,
                    "selected_role": selected_role,
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

        # Safe next URL redirect (prevent open redirect & cross-role dashboard bounce)
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            if role == "admin" and (selected_role == "admin" or next_url.startswith("/distributor")):
                return redirect("admin_dashboard")
            if role == "distributor" and next_url.startswith("/admin"):
                return redirect("distributor_dashboard")
            return redirect(next_url)

        if role == "admin":
            return redirect("admin_dashboard")
        return redirect("distributor_dashboard")

    return render(
        request,
        "accounts/login.html",
        {
            "next": next_url,
            "selected_role": requested_role_param if requested_role_param in ("admin", "distributor") else "",
        }
    )


def admin_login_view(request):
    """Dedicated Administrator Login route (/admin-login/)."""
    return login_view(request, forced_role="admin")


def distributor_login_view(request):
    """Dedicated Distributor Login route (/distributor-login/)."""
    return login_view(request, forced_role="distributor")


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


# ==============================================================================
# TASK 54: SESSION-BASED AUTHENTICATION STATUS & INSPECTION API
# ==============================================================================

def session_status_api(request):
    """
    Task 54: Session Authentication Inspector API.
    Returns authentication state, expiry age, and role WITHOUT exposing raw session_key
    (preserving HttpOnly cookie protection against XSS session theft).
    """
    is_authenticated = request.user.is_authenticated
    has_active_session = bool(request.session.session_key)
    expiry_age = request.session.get_expiry_age()

    data = {
        "authenticated": is_authenticated,
        "has_active_session": has_active_session,
        "expiry_seconds": expiry_age,
        "session_cookie_name": "advance_billing_sessionid",
    }

    if is_authenticated:
        role = request.session.get("user_role") or ("admin" if request.user.is_staff else "distributor")
        data["user"] = {
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
            "role": role,
            "role_display": request.session.get("role_display") or ("Administrator" if role == "admin" else "Distributor"),
            "is_staff": request.user.is_staff,
        }
    else:
        data["user"] = None

    return JsonResponse(data, status=200)


# LOGOUT

@login_required
def logout_view(request):
    """
    Task 56: Logout handler that flushes user session and redirects to login page.
    """
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect("login")


# OTP GENERATOR

def generate_otp():
    return str(
        secrets.randbelow(900000) + 100000
    )


# FORGOT PASSWORD - SEND OTP

def forgot_password(request):

    if request.method == "POST":

        email = request.POST.get("email", "").strip().lower()

        if not email:
            return render(
                request,
                "accounts/forgot_password.html",
                {"error": "Please enter your email address."}
            )

        user_obj = User.objects.filter(email=email).first()
        if not user_obj:
            return render(
                request,
                "accounts/forgot_password.html",
                {
                    "error": "No account found with this email address.",
                    "email": email
                }
            )

        if user_obj.is_staff or user_obj.is_superuser:
            return render(
                request,
                "accounts/forgot_password.html",
                {
                    "error": "Administrator accounts must use the Admin Password Recovery portal.",
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

        otp_obj = PasswordResetOTP.objects.create(
            email=email,
            otp=otp,
            expires_at=expires_at
        )

        # Clear any stale reset session markers
        request.session.pop("pwd_reset_email", None)
        request.session.pop("pwd_reset_otp_id", None)

        # Send OTP email and verify dispatch succeeded
        sent_ok, err_msg = send_otp_email_with_status(
            email=email,
            otp=otp,
            user_name=user_obj.first_name or "User",
            is_admin=False,
            purpose="password_reset",
        )
        if not sent_ok:
            otp_obj.delete()
            return render(
                request,
                "accounts/forgot_password.html",
                {
                    "email": email,
                    "error": f"Failed to send OTP email to {email}. Check SMTP settings in .env ({err_msg}).",
                }
            )

        return render(
            request,
            "accounts/forgot_password.html",
            {
                "email": email,
                "otp_sent": True,
                "message": f"A 6-digit verification code has been sent to {email}.",
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

    email = request.POST.get("email", "").strip().lower()
    otp = request.POST.get("otp", "").strip()

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
    ).order_by("-created_at").first()

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

    # Check brute-force attempt limit
    if otp_record.failed_attempts >= PasswordResetOTP.MAX_ATTEMPTS:
        otp_record.delete()
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Too many failed OTP attempts. Please request a new OTP.",
                "email": email,
            }
        )

    # Constant-time OTP check
    if not hmac.compare_digest(otp_record.otp, otp):
        otp_record.failed_attempts += 1
        otp_record.save(update_fields=["failed_attempts"])
        remaining = PasswordResetOTP.MAX_ATTEMPTS - otp_record.failed_attempts
        if remaining <= 0:
            otp_record.delete()
            return render(
                request,
                "accounts/forgot_password.html",
                {
                    "error": "Too many failed OTP attempts. Please request a new OTP.",
                    "email": email,
                }
            )
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": f"Invalid OTP. Please check the code and try again ({remaining} attempts left).",
                "email": email,
                "otp_sent": True
            }
        )

    # Check expiry
    if timezone.now() > otp_record.expires_at:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "OTP has expired. Please request a new OTP.",
                "email": email,
                "otp_sent": True
            }
        )

    # Mark OTP as verified and bind to current session
    otp_record.is_verified = True
    otp_record.save(update_fields=["is_verified"])

    request.session["pwd_reset_email"] = email
    request.session["pwd_reset_otp_id"] = otp_record.id

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

    email = request.POST.get("email", "").strip().lower()

    if not email:
        return render(
            request,
            "accounts/forgot_password.html",
            {"error": "Please enter your email address."}
        )

    user_obj = User.objects.filter(email=email).first()
    if not user_obj:
        return render(
            request,
            "accounts/forgot_password.html",
            {"error": "No account found with this email address."}
        )

    if user_obj.is_staff or user_obj.is_superuser:
        return render(
            request,
            "accounts/forgot_password.html",
            {"error": "Administrator accounts must use the Admin Password Recovery portal."}
        )

    # Enforce OTP resend rate limit: max 3 resends per 15-minute window per email
    now_ts = int(timezone.now().timestamp())
    window_secs = 15 * 60
    max_resends = 3
    resend_history = request.session.get("otp_resend_history", {})
    email_timestamps = [
        ts for ts in resend_history.get(email, [])
        if isinstance(ts, (int, float)) and (now_ts - ts) < window_secs
    ]
    if len(email_timestamps) >= max_resends:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "email": email,
                "otp_sent": True,
                "error": "Too many OTP resend requests. Please wait 15 minutes before requesting another code.",
            }
        )
    email_timestamps.append(now_ts)
    resend_history[email] = email_timestamps
    request.session["otp_resend_history"] = resend_history

    PasswordResetOTP.objects.filter(
        email=email,
        is_verified=False
    ).delete()

    otp = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=5)

    otp_obj = PasswordResetOTP.objects.create(
        email=email,
        otp=otp,
        expires_at=expires_at
    )

    request.session.pop("pwd_reset_email", None)
    request.session.pop("pwd_reset_otp_id", None)

    sent_ok, err_msg = send_otp_email_with_status(
        email=email,
        otp=otp,
        user_name=user_obj.first_name or "User",
        is_admin=False,
        purpose="password_reset",
    )
    if not sent_ok:
        otp_obj.delete()
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "email": email,
                "otp_sent": True,
                "error": f"Failed to resend OTP email. Check SMTP settings in .env ({err_msg}).",
            }
        )

    return render(
        request,
        "accounts/forgot_password.html",
        {
            "email": email,
            "otp_sent": True,
            "message": f"A new 6-digit verification code has been sent to {email}.",
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

    # Enforce session binding & verified unexpired OTP
    session_email = request.session.get("pwd_reset_email")
    session_otp_id = request.session.get("pwd_reset_otp_id")
    if session_email != email or not session_otp_id:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "Verification session expired or invalid. Please request a new OTP.",
                "email": email
            }
        )

    otp_record = PasswordResetOTP.objects.filter(
        pk=session_otp_id,
        email=email,
        is_verified=True
    ).first()

    if not otp_record or not otp_record.is_reset_window_valid():
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

    user = User.objects.filter(email=email, is_staff=False, is_superuser=False).first()
    if not user:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": "No distributor account associated with this email address.",
                "email": email
            }
        )

    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return render(
            request,
            "accounts/forgot_password.html",
            {
                "error": exc.messages[0],
                "email": email,
                "otp_sent": True,
                "otp_verified": True
            }
        )

    # Update password
    user.set_password(password)
    user.save()

    # Clear OTP records & session binding
    PasswordResetOTP.objects.filter(email=email).delete()
    request.session.pop("pwd_reset_email", None)
    request.session.pop("pwd_reset_otp_id", None)

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
    Aggregates real-time financial metrics via SQL aggregations, GST tax audit,
    distributor performance summaries, inventory catalog valuation, and safe CSV export.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(
            request,
            "Access restricted: You are signed in as a Distributor. Please sign in with an Administrator account to open the Admin Portal."
        )
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

    # Optional CSV Export (protected against CSV Formula Injection)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="admin_sales_report_{period}_{now.strftime("%Y%m%d")}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Invoice Number", "Date", "Distributor", "Customer", "Subtotal (INR)", "GST (INR)", "Total Amount (INR)", "Status", "Payment Mode"])
        for inv in invoices_filtered.order_by("-created_at"):
            writer.writerow([
                sanitize_csv_cell(inv.invoice_number),
                inv.invoice_date.strftime("%Y-%m-%d %H:%M"),
                sanitize_csv_cell(inv.distributor.username),
                sanitize_csv_cell(inv.customer.name),
                f"{inv.subtotal:.2f}",
                f"{inv.gst_amount:.2f}",
                f"{inv.total_amount:.2f}",
                sanitize_csv_cell(inv.status),
                sanitize_csv_cell(inv.payment_mode),
            ])
        return response

    # 1. Financial & Revenue Report Aggregations (SQL aggregate — exclude Cancelled from revenue)
    active_invoices = invoices_filtered.exclude(status__iexact="Cancelled")
    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
    fin_agg = active_invoices.aggregate(
        total_invoices_count=Count("id"),
        gross_revenue=Coalesce(Sum("total_amount"), zero_dec),
        total_tax_collected=Coalesce(Sum("gst_amount"), zero_dec),
        net_taxable_subtotal=Coalesce(Sum("subtotal"), zero_dec),
        paid_invoices_count=Count("id", filter=Q(status__iexact="Paid")),
        partial_invoices_count=Count("id", filter=Q(status__iexact="Partial")),
        pending_invoices_count=Count("id", filter=Q(status__iexact="Pending")),
    )
    cancelled_invoices_count = invoices_filtered.filter(status__iexact="Cancelled").count()

    total_invoices_count = fin_agg["total_invoices_count"]
    gross_revenue = fin_agg["gross_revenue"]
    total_tax_collected = fin_agg["total_tax_collected"]
    net_taxable_subtotal = fin_agg["net_taxable_subtotal"]
    paid_invoices_count = fin_agg["paid_invoices_count"]
    partial_invoices_count = fin_agg["partial_invoices_count"]
    pending_invoices_count = fin_agg["pending_invoices_count"]

    # Separate true collected cash payments from billed revenue (never mix billed vs collected)
    paid_revenue = Decimal("0.00")
    pending_revenue = Decimal("0.00")
    for inv in active_invoices.select_related(None).only("total_amount", "amount_paid", "status"):
        paid_revenue += inv.effective_amount_paid
        pending_revenue += inv.balance_due

    avg_invoice_value = (gross_revenue / total_invoices_count) if total_invoices_count > 0 else Decimal("0.00")

    paid_percentage = 0
    pending_percentage = 0
    if gross_revenue > 0:
        paid_percentage = round((float(paid_revenue) / float(gross_revenue)) * 100, 1)
        pending_percentage = round((float(pending_revenue) / float(gross_revenue)) * 100, 1)

    # 2. Distributor Performance Report (Batched SQL aggregations instead of N+1 queries)
    dist_inv_stats = {
        row["distributor_id"]: row
        for row in active_invoices.values("distributor_id").annotate(
            invoice_count=Count("id"),
            revenue=Coalesce(Sum("total_amount"), zero_dec),
        )
    }
    dist_cust_stats = {
        row["distributor_id"]: row["cnt"]
        for row in customers_qs.values("distributor_id").annotate(cnt=Count("id"))
    }
    dist_prod_stats = {
        row["distributor_id"]: row["cnt"]
        for row in products_qs.values("distributor_id").annotate(cnt=Count("id"))
    }

    distributor_reports = []
    for dist in distributors_qs:
        inv_stat = dist_inv_stats.get(dist.id, {})
        dist_rev = inv_stat.get("revenue", Decimal("0.00"))
        dist_inv_count = inv_stat.get("invoice_count", 0)
        phone = dist.distributor_profile.phone if hasattr(dist, "distributor_profile") else ""
        distributor_reports.append({
            "user": dist,
            "phone": phone,
            "invoice_count": dist_inv_count,
            "revenue": dist_rev,
            "customer_count": dist_cust_stats.get(dist.id, 0),
            "product_count": dist_prod_stats.get(dist.id, 0),
            "is_active": dist.is_active,
        })
    distributor_reports.sort(key=lambda x: x["revenue"], reverse=True)

    max_dist_rev = max((float(d["revenue"]) for d in distributor_reports), default=0.0)
    for d in distributor_reports:
        rev_f = float(d["revenue"])
        d["bar_pct"] = round((rev_f / max_dist_rev) * 100, 1) if max_dist_rev > 0 else 0
        d["share_pct"] = round((rev_f / float(gross_revenue)) * 100, 1) if gross_revenue > 0 else 0

    # Time-series Revenue & GST Trend Chart buckets (only non-cancelled invoices)
    all_invoices_list = list(
        Invoice.objects.exclude(status__iexact="Cancelled").only("invoice_date", "total_amount", "subtotal", "gst_amount")
    )
    trend_chart_data = []
    if period in ("week", "today"):
        for i in reversed(range(7)):
            b_date = (now - timedelta(days=i)).date()
            bucket_invs = [inv for inv in all_invoices_list if inv.invoice_date.date() == b_date]
            b_rev = sum((inv.total_amount for inv in bucket_invs), Decimal("0.00"))
            b_sub = sum((inv.subtotal for inv in bucket_invs), Decimal("0.00"))
            b_gst = sum((inv.gst_amount for inv in bucket_invs), Decimal("0.00"))
            trend_chart_data.append({
                "label": b_date.strftime("%d %b"),
                "revenue": float(b_rev),
                "subtotal": float(b_sub),
                "gst": float(b_gst),
                "count": len(bucket_invs),
            })
    elif period == "month":
        for k in range(6):
            w_start = (now - timedelta(days=29 - k * 5)).date()
            w_end = now.date() if k == 5 else (now - timedelta(days=25 - k * 5)).date()
            bucket_invs = [inv for inv in all_invoices_list if w_start <= inv.invoice_date.date() <= w_end]
            b_rev = sum((inv.total_amount for inv in bucket_invs), Decimal("0.00"))
            b_sub = sum((inv.subtotal for inv in bucket_invs), Decimal("0.00"))
            b_gst = sum((inv.gst_amount for inv in bucket_invs), Decimal("0.00"))
            trend_chart_data.append({
                "label": w_start.strftime("%d %b"),
                "revenue": float(b_rev),
                "subtotal": float(b_sub),
                "gst": float(b_gst),
                "count": len(bucket_invs),
            })
    else:
        cur_y, cur_m = now.year, now.month
        for offset in reversed(range(6)):
            total_months = (cur_y * 12 + (cur_m - 1)) - offset
            b_y, b_m = divmod(total_months, 12)
            b_m += 1
            b_date = now.date().replace(year=b_y, month=b_m, day=1)
            bucket_invs = [
                inv for inv in all_invoices_list
                if inv.invoice_date.year == b_y and inv.invoice_date.month == b_m
            ]
            b_rev = sum((inv.total_amount for inv in bucket_invs), Decimal("0.00"))
            b_sub = sum((inv.subtotal for inv in bucket_invs), Decimal("0.00"))
            b_gst = sum((inv.gst_amount for inv in bucket_invs), Decimal("0.00"))
            trend_chart_data.append({
                "label": b_date.strftime("%b %Y"),
                "revenue": float(b_rev),
                "subtotal": float(b_sub),
                "gst": float(b_gst),
                "count": len(bucket_invs),
            })

    max_trend_rev = max((b["revenue"] for b in trend_chart_data), default=0.0)
    for b in trend_chart_data:
        if max_trend_rev > 0:
            b["rev_pct"] = round((b["revenue"] / max_trend_rev) * 100, 1)
            b["gst_pct"] = round((b["gst"] / max_trend_rev) * 100, 1)
        else:
            b["rev_pct"] = 0
            b["gst_pct"] = 0

    # 3. Inventory & Catalog Stock Health (Single SQL Aggregate)
    inv_val_expr = ExpressionWrapper(
        F("price") * F("stock"),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )
    prod_agg = products_qs.aggregate(
        total_products_count=Count("id"),
        low_stock_products_count=Count("id", filter=Q(stock__gt=0, stock__lte=10)),
        out_of_stock_products_count=Count("id", filter=Q(stock=0)),
        in_stock_products_count=Count("id", filter=Q(stock__gt=10)),
        total_inventory_valuation=Coalesce(Sum(inv_val_expr), zero_dec),
    )
    total_products_count = prod_agg["total_products_count"]
    low_stock_products_count = prod_agg["low_stock_products_count"]
    out_of_stock_products_count = prod_agg["out_of_stock_products_count"]
    in_stock_products_count = prod_agg["in_stock_products_count"]
    total_inventory_valuation = prod_agg["total_inventory_valuation"]

    if total_products_count > 0:
        in_stock_pct = round((in_stock_products_count / total_products_count) * 100, 1)
        low_stock_pct = round((low_stock_products_count / total_products_count) * 100, 1)
        out_of_stock_pct = round((out_of_stock_products_count / total_products_count) * 100, 1)
    else:
        in_stock_pct = 0.0
        low_stock_pct = 0.0
        out_of_stock_pct = 0.0

    in_stock_end_pct = in_stock_pct
    low_stock_end_pct = round(min(100.0, in_stock_pct + low_stock_pct), 1)

    chart_payload = {
        "trend": trend_chart_data,
        "distributors": [
            {
                "name": d["user"].get_full_name() or d["user"].username,
                "revenue": float(d["revenue"]),
                "invoices": d["invoice_count"],
                "share_pct": d["share_pct"],
            }
            for d in distributor_reports[:6]
        ],
    }
    chart_json = json.dumps(chart_payload)

    # 4. Customer Directory Totals
    cust_agg = customers_qs.aggregate(
        total_customers_count=Count("id"),
        active_customers_count=Count("id", filter=Q(is_active=True)),
    )
    total_customers_count = cust_agg["total_customers_count"]
    active_customers_count = cust_agg["active_customers_count"]

    # 5. Recent Invoices Ledger (latest 10) & Low Stock Products Watchlist (top 8)
    recent_invoices = invoices_filtered.order_by("-created_at")[:10]
    low_stock_products = products_qs.filter(stock__lte=10).select_related("distributor").order_by("stock", "name")[:8]

    total_distributors_count = len(distributor_reports)
    active_distributors_count = sum(1 for d in distributor_reports if d["is_active"])

    context = {
        "period": period,
        # Financial Reports
        "gross_revenue": gross_revenue,
        "total_tax_collected": total_tax_collected,
        "net_taxable_subtotal": net_taxable_subtotal,
        "total_invoices_count": total_invoices_count,
        "paid_invoices_count": paid_invoices_count,
        "partial_invoices_count": partial_invoices_count,
        "paid_revenue": paid_revenue,
        "pending_invoices_count": pending_invoices_count,
        "pending_revenue": pending_revenue,
        "cancelled_invoices_count": cancelled_invoices_count,
        "avg_invoice_value": avg_invoice_value,
        "paid_percentage": paid_percentage,
        "pending_percentage": pending_percentage,
        # System Overview KPIs
        "total_distributors_count": total_distributors_count,
        "active_distributors_count": active_distributors_count,
        "total_customers_count": total_customers_count,
        "active_customers_count": active_customers_count,
        # Stock & Inventory
        "total_products_count": total_products_count,
        "low_stock_products_count": low_stock_products_count,
        "out_of_stock_products_count": out_of_stock_products_count,
        "in_stock_products_count": in_stock_products_count,
        "in_stock_pct": in_stock_pct,
        "low_stock_pct": low_stock_pct,
        "out_of_stock_pct": out_of_stock_pct,
        "in_stock_end_pct": in_stock_end_pct,
        "low_stock_end_pct": low_stock_end_pct,
        "total_inventory_valuation": total_inventory_valuation,
        # Charts & Visualizations
        "trend_chart_data": trend_chart_data,
        "chart_payload": chart_payload,
        "chart_json": chart_json,
        # Detailed Tables
        "distributor_reports": distributor_reports,
        "recent_invoices": recent_invoices,
        "low_stock_products": low_stock_products,
    }

    return render(request, "admin/dashboard.html", context)


@admin_required
def admin_toggle_distributor_active(request, pk):
    """
    Allow Administrators to activate or deactivate a distributor account via POST.
    """
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("admin_dashboard")

    distributor = get_object_or_404(User, pk=pk, is_staff=False, is_superuser=False)
    distributor.is_active = not distributor.is_active
    distributor.save(update_fields=["is_active"])
    state_label = "activated" if distributor.is_active else "deactivated"
    messages.success(request, f"Distributor '{distributor.username}' has been {state_label}.")
    return redirect("admin_dashboard")


@admin_required
def admin_backup_db(request):
    """
    One-click Administrator database backup download.
    Streams a JSON snapshot (?format=json or non-file DB) or a hot online SQLite
    backup copy for safe disaster recovery.
    """
    import io
    import os
    import sqlite3
    import tempfile
    from django.conf import settings as dj_settings
    from django.core.management import call_command

    stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    req_format = (request.GET.get("format") or "json").strip().lower()
    db_cfg = dj_settings.DATABASES["default"]
    db_name = str(db_cfg.get("NAME", ""))

    if req_format == "sqlite" and "sqlite3" in db_cfg.get("ENGINE", "") and db_name and os.path.isfile(db_name):
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(tmp_fd)
        try:
            src = sqlite3.connect(db_name)
            dst = sqlite3.connect(tmp_path)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
            with open(tmp_path, "rb") as fh:
                payload = fh.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        response = HttpResponse(payload, content_type="application/x-sqlite3")
        response["Content-Disposition"] = f'attachment; filename="advance_billing_backup_{stamp}.sqlite3"'
        return response

    buf = io.StringIO()
    call_command("dumpdata", "auth.user", "accounts", "billing", indent=2, stdout=buf)
    response = HttpResponse(buf.getvalue(), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="advance_billing_backup_{stamp}.json"'
    return response


# DISTRIBUTOR DASHBOARD

@login_required
def distributor_dashboard(request):

    if request.user.is_staff or request.user.is_superuser:
        return redirect("admin_dashboard")

    from billing.models import Customer, Product, Invoice, Quotation
    total_customers = Customer.objects.filter(distributor=request.user).count()
    products_qs = Product.objects.filter(distributor=request.user)
    total_products = products_qs.count()
    invoices_qs = Invoice.objects.filter(distributor=request.user).select_related("customer")
    active_invoices_qs = invoices_qs.exclude(status__iexact="Cancelled")

    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
    agg = active_invoices_qs.aggregate(
        total_invoices=Count("id"),
        total_billed=Coalesce(Sum("total_amount"), zero_dec),
        total_gst_collected=Coalesce(Sum("gst_amount"), zero_dec),
        paid_invoices_count=Count("id", filter=Q(status__iexact="Paid")),
        partial_invoices_count=Count("id", filter=Q(status__iexact="Partial")),
        pending_invoices_count=Count("id", filter=Q(status__iexact="Pending")),
    )

    total_invoices = agg["total_invoices"]
    total_billed = agg["total_billed"]
    total_gst_collected = agg["total_gst_collected"]
    paid_invoices_count = agg["paid_invoices_count"]
    partial_invoices_count = agg["partial_invoices_count"]
    pending_invoices_count = agg["pending_invoices_count"]

    # Compute exact cash received vs pending receivables (accounting for Partial bills) & overdue count
    paid_revenue = Decimal("0.00")
    pending_revenue = Decimal("0.00")
    overdue_invoices_count = 0
    for inv in active_invoices_qs.select_related(None).only("total_amount", "amount_paid", "status", "due_date"):
        paid_revenue += inv.effective_amount_paid
        pending_revenue += inv.balance_due
        if inv.is_overdue:
            overdue_invoices_count += 1

    paid_percentage = 0
    pending_percentage = 0
    if total_billed > 0:
        paid_percentage = round((float(paid_revenue) / float(total_billed)) * 100, 1)
        pending_percentage = round((float(pending_revenue) / float(total_billed)) * 100, 1)

    low_stock_qs = products_qs.filter(stock__lte=10).order_by("stock", "name")
    low_stock_count = low_stock_qs.count()
    low_stock_products = low_stock_qs[:5]
    recent_invoices = invoices_qs.order_by("-created_at")[:5]
    quotations_count = Quotation.objects.filter(distributor=request.user).exclude(status__iexact="Converted").count()

    # Monthly Sales Chart (last 6 months for logged-in distributor only)
    now_dt = timezone.localtime(timezone.now())
    active_list = list(active_invoices_qs.select_related(None).only("invoice_date", "total_amount", "gst_amount"))
    monthly_sales_chart = []
    for m_offset in range(5, -1, -1):
        b_y, b_m = divmod(now_dt.year * 12 + (now_dt.month - 1) - m_offset, 12)
        b_m += 1
        b_date = now_dt.date().replace(year=b_y, month=b_m, day=1)
        m_invs = [
            inv for inv in active_list
            if inv.invoice_date and timezone.localtime(inv.invoice_date).year == b_y
            and timezone.localtime(inv.invoice_date).month == b_m
        ]
        m_rev = sum((inv.total_amount for inv in m_invs), Decimal("0.00"))
        m_gst = sum((inv.gst_amount for inv in m_invs), Decimal("0.00"))
        monthly_sales_chart.append({
            "label": b_date.strftime("%b %Y"),
            "revenue": float(m_rev),
            "gst": float(m_gst),
            "count": len(m_invs),
        })
    max_m_rev = max((pt["revenue"] for pt in monthly_sales_chart), default=0.0)
    for pt in monthly_sales_chart:
        pt["rev_pct"] = round((pt["revenue"] / max_m_rev) * 100, 1) if max_m_rev > 0 else 0
        pt["gst_pct"] = round((pt["gst"] / max_m_rev) * 100, 1) if max_m_rev > 0 else 0

    return render(
        request,
        "distributor/dashboard.html",
        {
            "total_customers": total_customers,
            "total_products": total_products,
            "total_invoices": total_invoices,
            "total_billed": total_billed,
            "total_gst_collected": total_gst_collected,
            "paid_invoices_count": paid_invoices_count,
            "partial_invoices_count": partial_invoices_count,
            "pending_invoices_count": pending_invoices_count,
            "overdue_invoices_count": overdue_invoices_count,
            "quotations_count": quotations_count,
            "paid_revenue": paid_revenue,
            "pending_revenue": pending_revenue,
            "paid_percentage": paid_percentage,
            "pending_percentage": pending_percentage,
            "low_stock_count": low_stock_count,
            "low_stock_products": low_stock_products,
            "recent_invoices": recent_invoices,
            "monthly_sales_chart": monthly_sales_chart,
        }
    )


@login_required
def distributor_profile(request):

    if request.user.is_staff or request.user.is_superuser:
        return redirect("admin_dashboard")

    # Auto-create profile if missing
    profile, _ = DistributorProfile.objects.get_or_create(
        user=request.user,
        defaults={"phone": ""}
    )

    if request.method == "POST":

        action = request.POST.get("action", "")

        if action == "update_profile":

            name = request.POST.get("name", "").strip()
            email = request.POST.get("email", "").strip().lower()
            phone = request.POST.get("phone", "").strip()
            business_name = request.POST.get("business_name", profile.business_name).strip()
            gstin = request.POST.get("gstin", profile.gstin).strip().upper()
            address = request.POST.get("address", profile.address).strip()
            city = request.POST.get("city", profile.city).strip()
            state = request.POST.get("state", profile.state).strip()
            upi_id = request.POST.get("upi_id", profile.upi_id).strip()

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
            try:
                validate_email(email)
            except ValidationError:
                return render(request, "distributor/profile.html", {
                    "profile": profile,
                    "error": "Please enter a valid email address."
                })

            # Validate optional business GSTIN & UPI ID
            biz_err = _validate_profile_business_fields(gstin, upi_id)
            if biz_err:
                return render(request, "distributor/profile.html", {
                    "profile": profile,
                    "error": biz_err
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
            profile.business_name = business_name
            profile.gstin = gstin
            profile.address = address
            profile.city = city
            profile.state = state
            profile.upi_id = upi_id
            profile.save()

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

    if request.user.is_staff or request.user.is_superuser:
        return redirect("admin_dashboard")

    user = request.user
    profile, _ = DistributorProfile.objects.get_or_create(
        user=user,
        defaults={"phone": ""}
    )

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        business_name = request.POST.get("business_name", profile.business_name).strip()
        gstin = request.POST.get("gstin", profile.gstin).strip().upper()
        address = request.POST.get("address", profile.address).strip()
        city = request.POST.get("city", profile.city).strip()
        state = request.POST.get("state", profile.state).strip()
        upi_id = request.POST.get("upi_id", profile.upi_id).strip()

        ctx = {
            "name": name,
            "email": email,
            "phone": phone,
            "business_name": business_name,
            "gstin": gstin,
            "address": address,
            "city": city,
            "state": state,
            "upi_id": upi_id,
        }

        if not name or not email or not phone:
            ctx["error"] = "All fields are required."
            return render(request, "distributor/update_profile.html", ctx)

        if len(name) < 3:
            ctx["error"] = "Name must contain at least 3 characters."
            return render(request, "distributor/update_profile.html", ctx)

        if not phone.isdigit() or len(phone) != 10:
            ctx["error"] = "Please enter a valid 10-digit phone number."
            return render(request, "distributor/update_profile.html", ctx)

        try:
            validate_email(email)
        except ValidationError:
            ctx["error"] = "Please enter a valid email address."
            return render(request, "distributor/update_profile.html", ctx)

        biz_err = _validate_profile_business_fields(gstin, upi_id)
        if biz_err:
            ctx["error"] = biz_err
            return render(request, "distributor/update_profile.html", ctx)

        if User.objects.filter(email=email).exclude(id=user.id).exists():
            ctx["error"] = "This email is already registered."
            return render(request, "distributor/update_profile.html", ctx)

        user.first_name = name
        user.email = email
        user.save()

        profile.phone = phone
        profile.business_name = business_name
        profile.gstin = gstin
        profile.address = address
        profile.city = city
        profile.state = state
        profile.upi_id = upi_id
        profile.save()

        messages.success(request, "Profile updated successfully.")
        return redirect("distributor_profile")

    return render(
        request,
        "distributor/update_profile.html",
        {
            "name": user.first_name,
            "email": user.email,
            "phone": profile.phone,
            "business_name": profile.business_name,
            "gstin": profile.gstin,
            "address": profile.address,
            "city": profile.city,
            "state": profile.state,
            "upi_id": profile.upi_id,
        }
    )


# ==============================================================================
# ADMIN USER REGISTRATION API ENDPOINT (LOCKED DOWN)
# ==============================================================================

@csrf_exempt
def admin_register_api(request):
    """
    REST API endpoint for registering Admin users.
    Security policy:
      - If at least one Admin already exists in the system, caller MUST be an
        authenticated Admin (via session or HTTP Basic Auth).
      - If zero Admins exist (initial bootstrap), allows creating the first Admin.
    """
    if request.method != "POST":
        return JsonResponse({
            "status": "error",
            "message": "Method not allowed. Only POST requests are supported."
        }, status=405)

    # Enforce admin authorization once an administrator exists
    if User.objects.filter(is_staff=True).exists():
        caller = request.user if request.user.is_authenticated else _authenticate_basic_header(request)
        if not caller:
            return JsonResponse({
                "status": "error",
                "message": "Authentication required. Only existing administrators can register new admins."
            }, status=401)
        if not (caller.is_staff or caller.is_superuser):
            return JsonResponse({
                "status": "error",
                "message": "Forbidden. Administrator privileges are required."
            }, status=403)

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

    if not username:
        errors["username"] = "Username is required."
    elif len(username) < 3:
        errors["username"] = "Username must be at least 3 characters long."
    elif User.objects.filter(username=username).exists():
        errors["username"] = "A user with this username already exists."

    if not email:
        errors["email"] = "Email address is required."
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Please enter a valid email address."
        if User.objects.filter(email=email).exists():
            errors["email"] = "An account with this email already exists."

    if not password:
        errors["password"] = "Password is required."
    elif len(password) < 8:
        errors["password"] = "Password must be at least 8 characters long."
    else:
        try:
            validate_password(password)
        except ValidationError as exc:
            errors["password"] = exc.messages[0]

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
        Admin.objects.get_or_create(
            user=user,
            defaults={
                "phone": str(data.get("phone", "")).strip()[:15],
                "department": str(data.get("department", "Administration")).strip()[:100] or "Administration",
            }
        )

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
# ADMIN FRONTEND REGISTRATION VIEW (LOCKED DOWN)
# ==============================================================================

def admin_register_view(request):
    """
    Frontend view for Admin registration.
    Security policy:
      - If an Admin already exists, ONLY an authenticated Admin can access this view.
      - If zero Admins exist (initial bootstrap), allows creating the first Admin.
    """
    admins_exist = User.objects.filter(is_staff=True).exists()
    if admins_exist:
        if not request.user.is_authenticated:
            messages.error(request, "Admin registration is restricted. Please sign in as an Administrator.")
            return redirect("login")
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, "Access restricted to Administrator accounts.")
            return redirect("distributor_dashboard")
    elif request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
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

        if not all([name, username, email, password, confirm_password]):
            context["error"] = "Please fill in all required fields."
            return render(request, "accounts/admin_register.html", context)

        if len(name) < 3:
            context["error"] = "Full name must be at least 3 characters long."
            return render(request, "accounts/admin_register.html", context)

        if len(username) < 3:
            context["error"] = "Username must be at least 3 characters long."
            return render(request, "accounts/admin_register.html", context)

        if User.objects.filter(username=username).exists():
            context["error"] = "An account with this username already exists."
            return render(request, "accounts/admin_register.html", context)

        try:
            validate_email(email)
        except ValidationError:
            context["error"] = "Please enter a valid email address."
            return render(request, "accounts/admin_register.html", context)

        if User.objects.filter(email=email).exists():
            context["error"] = "An account with this email already exists."
            return render(request, "accounts/admin_register.html", context)

        if len(password) < 8:
            context["error"] = "Password must be at least 8 characters long."
            return render(request, "accounts/admin_register.html", context)

        if password != confirm_password:
            context["error"] = "Passwords do not match."
            return render(request, "accounts/admin_register.html", context)

        try:
            validate_password(password)
        except ValidationError as exc:
            context["error"] = exc.messages[0]
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
            Admin.objects.get_or_create(
                user=user,
                defaults={
                    "phone": request.POST.get("phone", "").strip()[:15],
                    "department": request.POST.get("department", "Administration").strip()[:100] or "Administration",
                }
            )

            messages.success(
                request,
                f"Administrator account '{username}' registered successfully! Please sign in."
            )
            if request.user.is_authenticated and request.user.is_staff:
                return redirect("admin_dashboard")
            return redirect("login")

        except Exception as e:
            context["error"] = f"Unable to create admin account: {str(e)}"
            return render(request, "accounts/admin_register.html", context)

    return render(request, "accounts/admin_register.html")


# ==============================================================================
# ADMIN PASSWORD RECOVERY BACKEND LOGIC (CSRF-PROTECTED WEB + JSON API WRAPPERS)
# ==============================================================================

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
        otp_obj = PasswordResetOTP.objects.create(email=email, otp=otp, expires_at=expires_at)

        request.session.pop("admin_pwd_reset_email", None)
        request.session.pop("admin_pwd_reset_otp_id", None)

        sent_ok, err_msg = send_otp_email_with_status(
            email=email,
            otp=otp,
            user_name=user.first_name,
            is_admin=True,
            purpose="password_reset",
        )
        if not sent_ok:
            otp_obj.delete()
            fail_msg = f"Failed to send admin OTP email to {email}. Check SMTP settings in .env ({err_msg})."
            if request.content_type == "application/json":
                return JsonResponse({"status": "error", "message": fail_msg}, status=502)
            return render(request, "accounts/forgot_password.html", {
                "email": email,
                "is_admin": True,
                "error": fail_msg,
            })

        success_msg = f"A 6-digit admin verification code has been sent to {email}."
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
            "message": success_msg,
        })

    return render(request, "accounts/forgot_password.html", {"is_admin": True})


def admin_verify_otp(request):
    """
    Backend logic for Admin password recovery - Step 2: Verify OTP.
    Enforces attempt limits, constant-time OTP check, expiry, and session binding.
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

    admin_user = User.objects.filter(email=email, is_staff=True).first()
    if not admin_user:
        error_msg = "Administrator privilege verification failed for this account."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=403)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    otp_record = PasswordResetOTP.objects.filter(email=email, is_verified=False).order_by("-created_at").first()

    if not otp_record:
        error_msg = "Invalid OTP code. Please verify and try again."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    if otp_record.failed_attempts >= PasswordResetOTP.MAX_ATTEMPTS:
        otp_record.delete()
        error_msg = "Too many failed OTP attempts. Please request a new code."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=429)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "is_admin": True})

    if not hmac.compare_digest(otp_record.otp, otp):
        otp_record.failed_attempts += 1
        otp_record.save(update_fields=["failed_attempts"])
        if otp_record.failed_attempts >= PasswordResetOTP.MAX_ATTEMPTS:
            otp_record.delete()
            error_msg = "Too many failed OTP attempts. Please request a new code."
            status_code = 429
        else:
            error_msg = "Invalid OTP code. Please verify and try again."
            status_code = 400
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=status_code)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    if timezone.now() > otp_record.expires_at:
        error_msg = "OTP has expired. Please request a new code."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "is_admin": True})

    # Mark OTP as verified and bind to current session
    otp_record.is_verified = True
    otp_record.save(update_fields=["is_verified"])

    request.session["admin_pwd_reset_email"] = email
    request.session["admin_pwd_reset_otp_id"] = otp_record.id

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


def admin_reset_password(request):
    """
    Backend logic for Admin password recovery - Step 3: Set New Password.
    Verifies session-bound verified & unexpired OTP, updates admin password, clears OTP records.
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

    session_email = request.session.get("admin_pwd_reset_email")
    session_otp_id = request.session.get("admin_pwd_reset_otp_id")
    if session_email != email or not session_otp_id:
        error_msg = "Verification session expired. Please request a new OTP."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "is_admin": True})

    otp_record = PasswordResetOTP.objects.filter(
        pk=session_otp_id,
        email=email,
        is_verified=True
    ).first()
    if not otp_record or not otp_record.is_reset_window_valid():
        error_msg = "Verification session expired. Please request a new OTP."
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "is_admin": True})

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

    try:
        validate_password(password, user=admin_user)
    except ValidationError as exc:
        error_msg = exc.messages[0]
        if request.content_type == "application/json":
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        return render(request, "accounts/forgot_password.html", {"error": error_msg, "email": email, "otp_sent": True, "otp_verified": True, "is_admin": True})

    # Set new password
    admin_user.set_password(password)
    admin_user.save()

    # Clear OTP records & session binding
    PasswordResetOTP.objects.filter(email=email).delete()
    request.session.pop("admin_pwd_reset_email", None)
    request.session.pop("admin_pwd_reset_otp_id", None)

    success_msg = f"Administrator password for '{admin_user.username}' has been updated successfully!"
    if request.content_type == "application/json":
        return JsonResponse({
            "status": "success",
            "message": success_msg
        }, status=200)

    messages.success(request, success_msg)
    return redirect("login")


@csrf_exempt
def api_admin_forgot_password(request):
    """JSON API wrapper for Admin password recovery step 1."""
    return admin_forgot_password(request)


@csrf_exempt
def api_admin_verify_otp(request):
    """JSON API wrapper for Admin password recovery step 2."""
    return admin_verify_otp(request)


@csrf_exempt
def api_admin_reset_password(request):
    """JSON API wrapper for Admin password recovery step 3."""
    return admin_reset_password(request)
