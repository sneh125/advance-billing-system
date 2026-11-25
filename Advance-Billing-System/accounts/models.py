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


class RegistrationOTP(models.Model):
    """Dedicated OTP verification table for new Distributor email registration."""
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

    def __str__(self):
        return f"{self.email} - Registration OTP"


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


class Admin(models.Model):
    """Custom Admin profile table linked 1-to-1 with Django staff/superuser accounts."""
    user = models.OneToOneField(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="admin_profile"
    )
    phone = models.CharField(max_length=15, blank=True, default="")
    department = models.CharField(max_length=100, blank=True, default="Administration")
    designation = models.CharField(max_length=100, blank=True, default="System Administrator")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Admin Profile"
        verbose_name_plural = "Admin Profiles"

    def __str__(self):
        return f"Admin: {self.user.get_full_name() or self.user.username}"


class SystemAnnouncement(models.Model):
    """Admin-managed broadcast notices displayed live on all Distributor dashboards."""
    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_URGENT = "urgent"
    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_WARNING, "Warning"),
        (LEVEL_URGENT, "Urgent"),
    ]

    title = models.CharField(max_length=140)
    message = models.TextField(max_length=600)
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="system_announcements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "System Announcement"
        verbose_name_plural = "System Announcements"

    def __str__(self):
        state = "LIVE" if self.is_active else "PAUSED"
        return f"[{state}] {self.title}"
