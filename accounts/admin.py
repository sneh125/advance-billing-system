from django.contrib import admin
from .models import DistributorProfile, PasswordResetOTP


@admin.register(DistributorProfile)
class DistributorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "business_name", "phone", "gstin", "state", "upi_id", "created_at")
    search_fields = ("user__username", "user__email", "business_name", "phone", "gstin")


@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "failed_attempts", "expires_at", "is_verified", "created_at")
    list_filter = ("is_verified",)
    search_fields = ("email",)
    readonly_fields = ("otp",)
