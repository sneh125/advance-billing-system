import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)


def sanitize_csv_cell(value):
    """
    Prevent CSV / Spreadsheet Formula Injection (CWE-1236) by prefixing cells
    that start with dangerous formula trigger characters with a single quote.
    """
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def is_console_email_backend():
    """
    Returns True ONLY when running in local DEBUG mode with Django's console email backend
    (i.e. SMTP credentials have not yet been configured in .env).
    """
    backend = getattr(settings, "EMAIL_BACKEND", "")
    return bool(getattr(settings, "DEBUG", False)) and backend.endswith("console.EmailBackend")


def send_otp_email_with_status(email, otp, user_name=None, is_admin=False, purpose="password_reset"):
    """
    Sends a formatted OTP verification email (HTML + plain-text fallback).
    Supports purpose='password_reset' and purpose='registration'.
    Returns (success: bool, error_message: str).
    """
    prefix = getattr(settings, "EMAIL_SUBJECT_PREFIX", "[Advance Billing] ")
    role_label = "Administrator" if is_admin else "Distributor"

    if purpose == "registration":
        subject = f"{prefix}Email Verification OTP - Distributor Registration"
        html_tpl = "emails/otp_registration.html"
        txt_tpl = "emails/otp_registration.txt"
    else:
        subject = f"{prefix}{role_label} Password Reset OTP"
        html_tpl = "emails/otp_password_reset.html"
        txt_tpl = "emails/otp_password_reset.txt"

    context = {
        "email": email,
        "otp": otp,
        "user_name": user_name or "User",
        "is_admin": is_admin,
        "purpose": purpose,
    }

    try:
        html_content = render_to_string(html_tpl, context)
        text_content = render_to_string(txt_tpl, context)
    except Exception:
        text_content = f"Your Advance Billing OTP code is {otp}. It expires in 5 minutes."
        html_content = f"<p>Your Advance Billing OTP code is <strong>{otp}</strong>. It expires in 5 minutes.</p>"

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "Advance Billing <no-reply@advancebilling.local>")

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=[email]
    )
    msg.attach_alternative(html_content, "text/html")

    try:
        msg.send(fail_silently=False)
        logger.info("OTP verification email (%s) dispatched to %s", purpose, email)
        return True, ""
    except Exception as exc:
        logger.error("Failed to send OTP email (%s) to %s: %s", purpose, email, exc)
        return False, str(exc)


def send_otp_email(email, otp, user_name=None, is_admin=False, purpose="password_reset"):
    """
    Backwards-compatible wrapper around send_otp_email_with_status returning bool.
    """
    ok, _ = send_otp_email_with_status(
        email=email,
        otp=otp,
        user_name=user_name,
        is_admin=is_admin,
        purpose=purpose,
    )
    return ok
