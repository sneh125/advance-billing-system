from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify SMTP / Email configuration by sending a test email."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Email address to send the test message to.")

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        backend = settings.EMAIL_BACKEND
        self.stdout.write(f"Using EMAIL_BACKEND: {backend}")
        try:
            sent = send_mail(
                subject=f"{settings.EMAIL_SUBJECT_PREFIX}SMTP Configuration Test",
                message="This is a verification email from Advance Billing System. Your email delivery is working.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f"Failed to send test email: {exc}") from exc

        if sent:
            self.stdout.write(self.style.SUCCESS(f"Test email sent successfully to {recipient}."))
        else:
            raise CommandError("Email backend returned 0 sent messages.")

