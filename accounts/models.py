from django.db import models
from django.utils import timezone


class PasswordResetOTP(models.Model):
    MAX_ATTEMPTS = 5

    email = models.EmailField()

    otp = models.CharField(max_length=6)

    created_at = models.DateTimeField(auto_now_add=True)

    expires_at = models.DateTimeField()

    is_verified = models.BooleanField(default=False)

    failed_attempts = models.PositiveSmallIntegerField(default=0)

    def is_valid(self):
        return (
            not self.is_verified
            and self.failed_attempts < self.MAX_ATTEMPTS
            and timezone.now() <= self.expires_at
        )

    def is_reset_window_valid(self):
        return (
            self.is_verified
            and timezone.now() <= self.expires_at
        )

    def __str__(self):
        return f"{self.email} - OTP"


class DistributorProfile(models.Model):
    user = models.OneToOneField(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="distributor_profile"
    )

    phone = models.CharField(max_length=15)

    business_name = models.CharField(max_length=150, blank=True, default="")

    gstin = models.CharField(max_length=15, blank=True, default="")

    address = models.TextField(blank=True, default="")

    city = models.CharField(max_length=50, blank=True, default="")

    state = models.CharField(max_length=50, blank=True, default="")

    upi_id = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.business_name or self.user.username
