from django.db import models
from django.utils import timezone
from datetime import timedelta


class PasswordResetOTP(models.Model):

    email = models.EmailField()

    otp = models.CharField(max_length=6)

    created_at = models.DateTimeField(auto_now_add=True)

    expires_at = models.DateTimeField()

    is_verified = models.BooleanField(default=False)

    def is_valid(self):
        return (
            not self.is_verified
            and timezone.now() <= self.expires_at
        )

    def __str__(self):
        return f"{self.email} - {self.otp}"

class DistributorProfile(models.Model):
    user = models.OneToOneField(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="distributor_profile"
    )

    phone = models.CharField(max_length=15)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username

