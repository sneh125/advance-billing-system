from django import forms
from .models import Invoice, Customer, Product


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
