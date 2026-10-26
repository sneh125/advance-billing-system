from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
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

    gst_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        default="Pending"
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
        whenever an Invoice is saved.
        """
        super().save(*args, **kwargs)
        generated_qr = self.generate_qr_code_base64()
        self.qr_code_data = generated_qr
        Invoice.objects.filter(pk=self.pk).update(qr_code_data=generated_qr)

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