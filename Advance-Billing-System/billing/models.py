from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal
import base64
from io import BytesIO
import qrcode


class Customer(models.Model):
    distributor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="customers"
    )
    name = models.CharField(max_length=100)
    email = models.EmailField(max_length=150, blank=True, null=True)
    phone = models.CharField(max_length=15)
    gstin = models.CharField(max_length=15, blank=True, default="")
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=50)
    state = models.CharField(max_length=50)
    pincode = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Product(models.Model):

    distributor = models.ForeignKey(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="products"
    )

    name = models.CharField(
        max_length=150
    )

    sku = models.CharField(
        max_length=50,
        blank=True,
        default=""
    )

    hsn_code = models.CharField(
        max_length=20,
        blank=True,
        default=""
    )

    category = models.CharField(
        max_length=100
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01"))
        ]
    )

    stock = models.PositiveIntegerField(
        default=0
    )

    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("100"))
        ]
    )

    description = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


class Invoice(models.Model):
    PAYMENT_MODE_CHOICES = [
        ("Unpaid", "Unpaid"),
        ("Cash", "Cash"),
        ("UPI", "UPI"),
        ("Bank Transfer", "Bank Transfer"),
        ("Card", "Card"),
        ("Cheque", "Cheque"),
    ]

    invoice_number = models.CharField(
        max_length=50,
        unique=True
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="invoices"
    )

    distributor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invoices"
    )

    invoice_date = models.DateTimeField(
        auto_now_add=True
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    discount_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    gst_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    cgst_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    sgst_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    igst_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    is_interstate = models.BooleanField(
        default=False
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    round_off = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    due_date = models.DateField(
        blank=True,
        null=True
    )

    notes = models.TextField(
        blank=True,
        default=""
    )

    status = models.CharField(
        max_length=20,
        default="Pending"
    )

    payment_mode = models.CharField(
        max_length=30,
        choices=PAYMENT_MODE_CHOICES,
        default="Unpaid"
    )

    paid_at = models.DateTimeField(
        blank=True,
        null=True
    )

    cancelled_at = models.DateTimeField(
        blank=True,
        null=True
    )

    qr_code_data = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def get_invoice_summary_data(self):
        """
        Task 57: Return core invoice data stored in the database
        (invoice ID, invoice number, customer name, total amount, and date).
        """
        inv_date = self.invoice_date or self.created_at
        return {
            "invoice_id": self.id,
            "invoice_number": self.invoice_number,
            "customer_name": self.customer.name if self.customer_id else "",
            "total_amount": self.total_amount,
            "date": inv_date.strftime("%d %b %Y") if inv_date else "",
        }

    def generate_qr_code_base64(self):
        """
        Task 60: Generate base64 PNG QR code using the qrcode library
        for this invoice instance.
        """
        summary = self.get_invoice_summary_data()
        product_count = self.items.count() if self.pk else 0
        payload = (
            f"Invoice ID: {summary['invoice_id']}\n"
            f"Invoice: {summary['invoice_number']}\n"
            f"Customer: {summary['customer_name']}\n"
            f"Products: {product_count}\n"
            f"Total: ₹{summary['total_amount']}\n"
            f"Date: {summary['date']}"
        )
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buf = BytesIO()
        qr_img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def save(self, *args, **kwargs):
        """
        Task 60: Automatically handle QR code generation using qrcode library
        whenever an Invoice is saved. Skip redundant regeneration when only
        updating non-QR fields via update_fields.
        """
        update_fields = kwargs.get("update_fields")
        super().save(*args, **kwargs)
        if update_fields is None or "qr_code_data" in update_fields:
            generated_qr = self.generate_qr_code_base64()
            self.qr_code_data = generated_qr
            Invoice.objects.filter(pk=self.pk).update(qr_code_data=generated_qr)

    @property
    def effective_amount_paid(self):
        paid = self.amount_paid or Decimal("0.00")
        total = self.total_amount or Decimal("0.00")
        if (self.status or "").lower() == "paid" and paid == Decimal("0.00"):
            return total
        return paid

    @property
    def balance_due(self):
        if (self.status or "").lower() == "cancelled":
            return Decimal("0.00")
        total = self.total_amount or Decimal("0.00")
        remaining = (total - self.effective_amount_paid).quantize(Decimal("0.01"))
        return remaining if remaining > Decimal("0.00") else Decimal("0.00")

    @property
    def is_overdue(self):
        if (self.status or "").lower() in ("paid", "cancelled"):
            return False
        if not self.due_date:
            return False
        return self.due_date < timezone.localdate() and self.balance_due > Decimal("0.00")

    def recalculate_payment_status(self, save=True):
        paid_sum = self.payments.aggregate(
            total=Coalesce(Sum("amount"), Decimal("0.00"))
        )["total"].quantize(Decimal("0.01"))
        self.amount_paid = paid_sum
        if (self.status or "").lower() != "cancelled":
            last_payment = self.payments.order_by("-payment_date", "-created_at", "-id").first()
            total = self.total_amount or Decimal("0.00")
            if paid_sum >= total and total > Decimal("0.00"):
                self.status = "Paid"
                self.paid_at = self.paid_at or timezone.now()
                if last_payment:
                    self.payment_mode = last_payment.payment_mode
                elif self.payment_mode == "Unpaid":
                    self.payment_mode = "Cash"
            elif paid_sum > Decimal("0.00"):
                self.status = "Partial"
                self.paid_at = None
                if last_payment:
                    self.payment_mode = last_payment.payment_mode
            else:
                self.status = "Pending"
                self.paid_at = None
                self.payment_mode = "Unpaid"
        if save:
            self.save(update_fields=["amount_paid", "status", "payment_mode", "paid_at", "updated_at"])
        return self.amount_paid

    def __str__(self):
        return self.invoice_number


class InvoiceItem(models.Model):

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="items"
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="invoice_items"
    )

    quantity = models.PositiveIntegerField()

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )

    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.product.name}"


class InvoicePayment(models.Model):
    """Records individual full or partial payments received against an Invoice."""
    PAYMENT_MODE_CHOICES = [
        ("Cash", "Cash"),
        ("UPI", "UPI"),
        ("Bank Transfer", "Bank Transfer"),
        ("Card", "Card"),
        ("Cheque", "Cheque"),
    ]

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="payments"
    )
    distributor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_payments"
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    payment_mode = models.CharField(
        max_length=30,
        choices=PAYMENT_MODE_CHOICES,
        default="Cash"
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        default=""
    )
    payment_date = models.DateField(default=timezone.localdate)
    notes = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-created_at", "-id"]

    def __str__(self):
        return f"{self.invoice.invoice_number} - ₹{self.amount} ({self.payment_mode})"


class StockMovement(models.Model):
    """Audit trail for all product inventory changes (Opening, Restock, Sale, Cancel Restore, Adjustment)."""
    MOVEMENT_TYPE_CHOICES = [
        ("OPENING", "Opening Stock"),
        ("RESTOCK", "Stock-In / Purchase"),
        ("SALE", "Invoice Sale"),
        ("CANCEL_RESTORE", "Invoice Cancelled (Restore)"),
        ("ADJUSTMENT", "Manual Adjustment"),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_movements"
    )
    distributor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="stock_movements"
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MOVEMENT_TYPE_CHOICES
    )
    quantity_change = models.IntegerField()
    stock_before = models.PositiveIntegerField(default=0)
    stock_after = models.PositiveIntegerField(default=0)
    reference = models.CharField(max_length=100, blank=True, default="")
    notes = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        sign = "+" if self.quantity_change > 0 else ""
        return f"{self.product.name}: {sign}{self.quantity_change} ({self.movement_type})"


class Quotation(models.Model):
    """Sales Quotation / Proforma Estimate that converts into a GST Tax Invoice in one click."""
    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Sent", "Sent"),
        ("Accepted", "Accepted"),
        ("Converted", "Converted"),
        ("Expired", "Expired"),
    ]

    quotation_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="quotations"
    )
    distributor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="quotations"
    )
    quotation_date = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateField(blank=True, null=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_interstate = models.BooleanField(default=False)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Sent")
    notes = models.TextField(blank=True, default="")
    converted_invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_quotations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def is_expired(self):
        if self.status == "Converted":
            return False
        return bool(self.valid_until and self.valid_until < timezone.localdate())

    def __str__(self):
        return self.quotation_number


class QuotationItem(models.Model):
    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="quotation_items"
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quotation.quotation_number} - {self.product.name}"
