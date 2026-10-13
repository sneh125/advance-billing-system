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


class InvoiceReportFilterForm(forms.Form):
    """
    Task 43: Form for generating reports by filtering invoices with date range,
    payment status, and optional customer selection.
    """
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'startDate',
        }),
        label="From Date"
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'endDate',
        }),
        label="To Date"
    )
    status = forms.ChoiceField(
        required=False,
        choices=[
            ('', '-- All Statuses --'),
            ('Paid', 'Paid'),
            ('Pending', 'Pending'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'statusSelect',
        }),
        label="Payment Status"
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        required=False,
        empty_label="-- All Customers --",
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'customerSelect',
        }),
        label="Customer"
    )

    def __init__(self, *args, **kwargs):
        distributor = kwargs.pop('distributor', None)
        super().__init__(*args, **kwargs)
        if distributor:
            self.fields['customer'].queryset = Customer.objects.filter(
                distributor=distributor
            ).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        # Task 46: Validation to prevent empty date selection or invalid ranges
        has_date_keys = 'start_date' in self.data or 'end_date' in self.data

        if has_date_keys:
            raw_start = str(self.data.get('start_date', '')).strip()
            raw_end = str(self.data.get('end_date', '')).strip()
            raw_status = str(self.data.get('status', '')).strip()
            raw_customer = str(self.data.get('customer', '')).strip()

            # Prevent submitting empty dates when generating report without other filters
            if not raw_start and not raw_end:
                if not raw_status and not raw_customer:
                    raise forms.ValidationError("Please select both From Date and To Date to generate the report.")
            elif not raw_start and raw_end:
                raise forms.ValidationError("From Date is required when To Date is provided. Please select a valid start date.")
            elif raw_start and not raw_end:
                raise forms.ValidationError("To Date is required when From Date is provided. Please select a valid end date.")

        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("From Date cannot be later than To Date.")

        return cleaned_data

