from django import forms
from decimal import Decimal
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from .models import Invoice, Customer, Product


class CustomerForm(forms.ModelForm):
    """
    Form for Customer registration and profile management with strict validations.
    """
    class Meta:
        model = Customer
        fields = ['name', 'email', 'phone', 'address', 'city', 'state', 'pincode', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '10-digit Phone'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Address'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '6-digit Pincode'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if len(name) < 3:
            raise forms.ValidationError("Name must contain at least 3 characters.")
        if len(name) > 100:
            raise forms.ValidationError("Name cannot exceed 100 characters.")
        return name

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if not phone.isdigit() or len(phone) != 10:
            raise forms.ValidationError("Please enter a valid 10-digit phone number.")
        return phone

    def clean_pincode(self):
        pincode = self.cleaned_data.get('pincode', '').strip()
        if not pincode.isdigit() or len(pincode) < 5 or len(pincode) > 6:
            raise forms.ValidationError("Please enter a valid 6-digit postal pincode.")
        return pincode


class ProductForm(forms.ModelForm):
    """
    Form for Product creation and updating with strict validation.
    """
    class Meta:
        model = Product
        fields = ['name', 'category', 'price', 'stock', 'gst_rate', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product Name'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'step': '1'}),
            'gst_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if len(name) < 2:
            raise forms.ValidationError("Product name must contain at least 2 characters.")
        return name

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is None or price <= Decimal('0.00'):
            raise forms.ValidationError("Price must be greater than 0.")
        return price

    def clean_stock(self):
        stock = self.cleaned_data.get('stock')
        if stock is None or stock < 0:
            raise forms.ValidationError("Stock cannot be negative.")
        return stock

    def clean_gst_rate(self):
        gst = self.cleaned_data.get('gst_rate')
        if gst is None or gst < Decimal('0.00') or gst > Decimal('100.00'):
            raise forms.ValidationError("GST rate must be between 0 and 100.")
        return gst


class InvoiceCreateForm(forms.ModelForm):
    """
    Invoice creation form with dynamic customer selection
    isolated to the logged-in distributor.
    """
    class Meta:
        model = Invoice
        fields = ['customer']
        widgets = {
            'customer': forms.Select(attrs={
                'class': 'form-control customer-select',
                'id': 'customerSelect',
                'required': 'required'
            })
        }

    def __init__(self, *args, **kwargs):
        distributor = kwargs.pop('distributor', None)
        super().__init__(*args, **kwargs)

        if distributor:
            self.fields['customer'].queryset = Customer.objects.filter(
                distributor=distributor,
                is_active=True
            ).order_by('name')
        else:
            self.fields['customer'].queryset = Customer.objects.none()

        self.fields['customer'].empty_label = "-- Select Verified Customer --"
