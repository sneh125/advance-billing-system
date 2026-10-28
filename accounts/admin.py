from django.contrib import admin
from .models import DistributorProfile, PasswordResetOTP


@admin.register(DistributorProfile)
class DistributorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "created_at")
    search_fields = ("user__username", "user__email", "phone")


@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "otp", "expires_at", "is_verified", "created_at")
    list_filter = ("is_verified",)
    search_fields = ("email", "otp")
