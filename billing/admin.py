from django.contrib import admin
from .models import Customer, Product, Invoice, InvoiceItem


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "city", "distributor", "is_active", "created_at")
    list_filter = ("is_active", "city", "state")
    search_fields = ("name", "phone", "email", "city")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "stock", "gst_rate", "distributor")
    list_filter = ("category", "gst_rate")
    search_fields = ("name", "category")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "customer", "distributor", "total_amount", "status", "invoice_date")
    list_filter = ("status", "invoice_date")
    search_fields = ("invoice_number", "customer__name")
    inlines = [InvoiceItemInline]


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "product", "quantity", "unit_price", "gst_rate", "total")
    search_fields = ("invoice__invoice_number", "product__name")
