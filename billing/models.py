from django.db import models
from django.contrib.auth.models import User


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
