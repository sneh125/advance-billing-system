from django.contrib import admin
from .models import (
    Customer,
    Product,
    Invoice,
    InvoiceItem,
    InvoicePayment,
    StockMovement,
    Quotation,
    QuotationItem,
)


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1


class InvoicePaymentInline(admin.TabularInline):
    model = InvoicePayment
    extra = 0


class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "gstin", "city", "state", "distributor", "is_active", "created_at")
    list_filter = ("is_active", "city", "state")
    search_fields = ("name", "phone", "email", "gstin", "city")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "hsn_code", "category", "price", "stock", "gst_rate", "distributor")
    list_filter = ("category", "gst_rate")
    search_fields = ("name", "sku", "hsn_code", "category")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "customer", "distributor", "total_amount", "amount_paid", "status", "due_date", "payment_mode", "invoice_date")
    list_filter = ("status", "payment_mode", "is_interstate", "invoice_date")
    search_fields = ("invoice_number", "customer__name")
    inlines = [InvoiceItemInline, InvoicePaymentInline]


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "product", "quantity", "unit_price", "discount_percent", "gst_rate", "total")
    search_fields = ("invoice__invoice_number", "product__name")


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "distributor", "amount", "payment_mode", "reference_number", "payment_date")
    list_filter = ("payment_mode", "payment_date")
    search_fields = ("invoice__invoice_number", "reference_number")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product", "distributor", "movement_type", "quantity_change", "stock_before", "stock_after", "reference", "created_at")
    list_filter = ("movement_type", "created_at")
    search_fields = ("product__name", "reference")


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ("quotation_number", "customer", "distributor", "total_amount", "status", "valid_until", "converted_invoice")
    list_filter = ("status", "is_interstate", "created_at")
    search_fields = ("quotation_number", "customer__name")
    inlines = [QuotationItemInline]
