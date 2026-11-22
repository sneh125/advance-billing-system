from django.contrib import admin
from .models import Admin, DistributorProfile, PasswordResetOTP, RegistrationOTP


@admin.register(RegistrationOTP)
class RegistrationOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "failed_attempts", "expires_at", "is_verified", "created_at")
    list_filter = ("is_verified",)
    search_fields = ("email",)
    readonly_fields = ("otp",)


@admin.register(Admin)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "department", "designation", "is_active", "created_at")
    list_filter = ("is_active", "department")
    search_fields = ("user__username", "user__email", "phone", "department")


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
