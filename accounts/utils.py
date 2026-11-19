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


def send_otp_email(email, otp, user_name=None, is_admin=False):
    """
    Sends a formatted OTP verification email using Django's email system.
    Supports both rich HTML and fallback plain-text formats.
    Returns True on success, False on failure.
    """
    prefix = getattr(settings, "EMAIL_SUBJECT_PREFIX", "[Advance Billing] ")
    role_label = "Administrator" if is_admin else "Distributor"
    subject = f"{prefix}{role_label} Password Reset OTP"

    context = {
        "email": email,
        "otp": otp,
        "user_name": user_name or "User",
        "is_admin": is_admin,
    }

    try:
        html_content = render_to_string("emails/otp_password_reset.html", context)
        text_content = render_to_string("emails/otp_password_reset.txt", context)
    except Exception:
        # Fallback text if template rendering encounters an issue
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
        logger.info("OTP verification email dispatched to %s", email)
        return True
    except Exception as e:
        logger.error("Failed to send OTP email to %s: %s", email, e)
        return False
