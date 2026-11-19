import json
import base64
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from decimal import Decimal
from datetime import date, timedelta
from .models import Customer, Product, Invoice, InvoiceItem
from .forms import CustomerForm, ProductForm, InvoiceReportFilterForm


class CustomerManagementTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Distributor 1
        self.distributor1 = User.objects.create_user(
            username="distributor1",
            email="dist1@example.com",
            password="Password@123",
            first_name="Distributor One"
        )

        # Distributor 2 (for multi-tenant isolation testing)
        self.distributor2 = User.objects.create_user(
            username="distributor2",
            email="dist2@example.com",
            password="Password@123",
            first_name="Distributor Two"
        )

        # Create a customer for Distributor 1
        self.customer1 = Customer.objects.create(
            distributor=self.distributor1,
            name="Ramesh Patel",
            email="ramesh@example.com",
            phone="9876543210",
            address="101 Market Street",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001",
            is_active=True
        )

        # Create a customer for Distributor 2
        self.customer2 = Customer.objects.create(
            distributor=self.distributor2,
            name="Suresh Shah",
            email="suresh@example.com",
            phone="9123456780",
            address="202 Ring Road",
            city="Surat",
            state="Gujarat",
            pincode="395001",
            is_active=True
        )

    def test_unauthenticated_access_redirects(self):
        """Unauthenticated user should be redirected to login"""
        response = self.client.get(reverse('customer_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_customer_list_isolation(self):
        """Distributor 1 should only see their own customer, not Distributor 2's"""
        self.client.login(username="distributor1", password="Password@123")
        response = self.client.get(reverse('customer_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ramesh Patel")
        self.assertNotContains(response, "Suresh Shah")
        self.assertEqual(response.context['total_customers'], 1)
        self.assertEqual(response.context['active_customers'], 1)

    def test_customer_search(self):
        """Search functionality should filter customers accurately"""
        self.client.login(username="distributor1", password="Password@123")
        
        # Search match
        response = self.client.get(reverse('customer_list') + '?q=Ramesh')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ramesh Patel")

        # Search no match
        response = self.client.get(reverse('customer_list') + '?q=NonExistent')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No Matching Customers Found")

    def test_customer_add_validation_and_creation(self):
        """Test validation error on short name and success on valid data"""
        self.client.login(username="distributor1", password="Password@123")

        # Invalid: name too short & phone invalid
        response = self.client.post(reverse('customer_add'), {
            'name': 'A',
            'phone': '123',
            'city': 'Rajkot',
            'state': 'Gujarat',
            'pincode': '360001',
            'is_active': 'on'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('name', response.context['errors'])
        self.assertIn('phone', response.context['errors'])

        # Valid customer creation
        response = self.client.post(reverse('customer_add'), {
            'name': 'Pooja Sharma',
            'email': 'pooja@example.com',
            'phone': '9898989898',
            'address': 'Flat 404, Green Heights',
            'city': 'Vadodara',
            'state': 'Gujarat',
            'pincode': '390001',
            'is_active': 'on'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Customer.objects.filter(distributor=self.distributor1).count(), 2)

    def test_customer_edit(self):
        """Test editing customer details"""
        self.client.login(username="distributor1", password="Password@123")

        response = self.client.post(reverse('customer_edit', kwargs={'pk': self.customer1.pk}), {
            'name': 'Ramesh Patel Updated',
            'email': 'ramesh_new@example.com',
            'phone': '9876543210',
            'address': '101 Market Street Updated',
            'city': 'Ahmedabad',
            'state': 'Gujarat',
            'pincode': '380001',
            'is_active': 'on'
        })
        self.assertEqual(response.status_code, 302)
        self.customer1.refresh_from_db()
        self.assertEqual(self.customer1.name, 'Ramesh Patel Updated')
        self.assertEqual(self.customer1.email, 'ramesh_new@example.com')

    def test_customer_edit_security_isolation(self):
        """Distributor 1 cannot edit Distributor 2's customer"""
        self.client.login(username="distributor1", password="Password@123")

        response = self.client.get(reverse('customer_edit', kwargs={'pk': self.customer2.pk}))
        self.assertEqual(response.status_code, 404)

    def test_customer_delete_post_only_and_security(self):
        """Delete must be POST and only allowed on owned customers"""
        self.client.login(username="distributor1", password="Password@123")

        # GET request to delete should redirect without deleting
        response = self.client.get(reverse('customer_delete', kwargs={'pk': self.customer1.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(pk=self.customer1.pk).exists())

        # Attempt to delete Distributor 2's customer -> 404
        response = self.client.post(reverse('customer_delete', kwargs={'pk': self.customer2.pk}))
        self.assertEqual(response.status_code, 404)

        # Valid POST delete on own customer
        response = self.client.post(reverse('customer_delete', kwargs={'pk': self.customer1.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Customer.objects.filter(pk=self.customer1.pk).exists())

    def test_product_add_validation_and_creation(self):
        """Test Product add validation and creation"""
        self.client.login(username="distributor1", password="Password@123")

        # Invalid: missing fields
        response = self.client.post(reverse('product_add'), {
            'name': 'A',
            'category': 'Electronics',
            'price': '-10',
            'stock': '5',
            'gst_rate': '18',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('error', response.context)

        # Valid creation
        response = self.client.post(reverse('product_add'), {
            'name': 'Wireless Mouse',
            'category': 'Electronics',
            'price': '499.00',
            'stock': '50',
            'gst_rate': '18',
            'description': 'Ergonomic optical wireless mouse',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Product.objects.filter(distributor=self.distributor1).count(), 1)

    def test_product_list_search_and_isolation(self):
        """Test Product list, search, and distributor isolation"""
        Product.objects.create(
            distributor=self.distributor1,
            name="Laptop Stand",
            category="Accessories",
            price=799.00,
            stock=20,
            gst_rate=18.00
        )
        Product.objects.create(
            distributor=self.distributor2,
            name="Secret Product",
            category="Confidential",
            price=1000.00,
            stock=10,
            gst_rate=18.00
        )

        self.client.login(username="distributor1", password="Password@123")

        # View list - should see Laptop Stand, not Secret Product
        response = self.client.get(reverse('product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Laptop Stand")
        self.assertNotContains(response, "Secret Product")

        # Search match
        response = self.client.get(reverse('product_list') + '?q=Laptop')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Laptop Stand")

    def test_product_edit_and_isolation(self):
        """Test editing product and security isolation"""
        product = Product.objects.create(
            distributor=self.distributor1,
            name="Keyboard",
            category="Accessories",
            price=999.00,
            stock=15,
            gst_rate=18.00
        )
        self.client.login(username="distributor1", password="Password@123")

        # Edit GET
        response = self.client.get(reverse('product_edit', kwargs={'pk': product.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Keyboard")

        # Edit POST
        response = self.client.post(reverse('product_edit', kwargs={'pk': product.pk}), {
            'name': 'Mechanical Keyboard',
            'category': 'Gaming Accessories',
            'price': '1499.00',
            'stock': '10',
            'gst_rate': '18.00',
            'description': 'RGB Mechanical Keyboard',
        })
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.name, 'Mechanical Keyboard')

    def test_product_delete_post_only(self):
        """Test deleting product via POST only"""
        product = Product.objects.create(
            distributor=self.distributor1,
            name="USB Hub",
            category="Accessories",
            price=299.00,
            stock=5,
            gst_rate=18.00
        )
        self.client.login(username="distributor1", password="Password@123")

        # Delete POST
        response = self.client.post(reverse('product_delete', kwargs={'pk': product.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())


class InvoiceSystemTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Distributor 1
        self.distributor1 = User.objects.create_user(
            username="distributor1",
            email="dist1@example.com",
            password="Password@123",
            first_name="Distributor One"
        )

        # Distributor 2
        self.distributor2 = User.objects.create_user(
            username="distributor2",
            email="dist2@example.com",
            password="Password@123",
            first_name="Distributor Two"
        )

        # Customer for Distributor 1
        self.customer1 = Customer.objects.create(
            distributor=self.distributor1,
            name="Rahul Sharma",
            phone="9876543210",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001",
            is_active=True
        )

        # Customer for Distributor 2
        self.customer2 = Customer.objects.create(
            distributor=self.distributor2,
            name="Vikram Verma",
            phone="9123456780",
            city="Surat",
            state="Gujarat",
            pincode="395001",
            is_active=True
        )

        # Products for Distributor 1
        self.product1 = Product.objects.create(
            distributor=self.distributor1,
            name="Wireless Mouse",
            category="Electronics",
            price=Decimal("500.00"),
            stock=50,
            gst_rate=Decimal("18.00")
        )

        self.product2 = Product.objects.create(
            distributor=self.distributor1,
            name="USB Keyboard",
            category="Electronics",
            price=Decimal("1000.00"),
            stock=30,
            gst_rate=Decimal("18.00")
        )

    def test_invoice_create_get_dropdowns_and_isolation(self):
        """Test GET invoice_create renders customer and product dropdowns for logged-in distributor only"""
        self.client.login(username="distributor1", password="Password@123")
        response = self.client.get(reverse('invoice_create'))
        self.assertEqual(response.status_code, 200)

        # Should contain customer1 and product1/product2
        self.assertContains(response, "Rahul Sharma")
        self.assertContains(response, "Wireless Mouse")
        self.assertContains(response, "USB Keyboard")

        # Should NOT contain distributor 2's customer
        self.assertNotContains(response, "Vikram Verma")

    def test_invoice_create_post_multiple_items_and_calculations(self):
        """
        25 Aug Tasks 1, 2 & 3:
        Test invoice creation with 2 products, custom quantities, GST, and discount calculations.
        Item 1: Wireless Mouse (Qty: 2, Price: 500.00, Disc: 10%, GST: 18%)
                Base = 1000.00, Discount = 100.00, Taxable = 900.00, GST = 162.00, Total = 1062.00
        Item 2: USB Keyboard (Qty: 1, Price: 1000.00, Disc: 0%, GST: 18%)
                Base = 1000.00, Discount = 0.00, Taxable = 1000.00, GST = 180.00, Total = 1180.00
        Invoice Subtotal = 1900.00, GST = 342.00, Grand Total = 2242.00
        """
        self.client.login(username="distributor1", password="Password@123")

        response = self.client.post(reverse('invoice_create'), {
            'customer': self.customer1.id,
            'product[]': [str(self.product1.id), str(self.product2.id)],
            'quantity[]': ['2', '1'],
            'unit_price[]': ['500.00', '1000.00'],
            'gst_rate[]': ['18.00', '18.00'],
            'discount[]': ['10.00', '0.00'],
        })

        # Should redirect to invoice_detail
        self.assertEqual(response.status_code, 302)

        # Verify Invoice in DB
        invoice = Invoice.objects.filter(distributor=self.distributor1).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.customer, self.customer1)
        self.assertEqual(invoice.subtotal, Decimal("1900.00"))
        self.assertEqual(invoice.gst_amount, Decimal("342.00"))
        self.assertEqual(invoice.total_amount, Decimal("2242.00"))

        # Verify InvoiceItems in DB
        items = invoice.items.all()
        self.assertEqual(items.count(), 2)

        item1 = items.get(product=self.product1)
        self.assertEqual(item1.quantity, 2)
        self.assertEqual(item1.subtotal, Decimal("900.00"))
        self.assertEqual(item1.total, Decimal("1062.00"))

        item2 = items.get(product=self.product2)
        self.assertEqual(item2.quantity, 1)
        self.assertEqual(item2.subtotal, Decimal("1000.00"))
        self.assertEqual(item2.total, Decimal("1180.00"))

    def test_invoice_multi_tenant_isolation(self):
        """Distributor 1 cannot bill Distributor 2's customer"""
        self.client.login(username="distributor1", password="Password@123")

        response = self.client.post(reverse('invoice_create'), {
            'customer': self.customer2.id,
            'product[]': [str(self.product1.id)],
            'quantity[]': ['1'],
            'unit_price[]': ['500.00'],
            'gst_rate[]': ['18.00'],
            'discount[]': ['0.00'],
        })

        # Should fail validation since customer2 belongs to distributor2
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_invoice_list_and_detail_views(self):
        """Test invoice list and detail pages render accurately"""
        invoice = Invoice.objects.create(
            invoice_number="INV-20260825-0001",
            customer=self.customer1,
            distributor=self.distributor1,
            subtotal=Decimal("900.00"),
            gst_amount=Decimal("162.00"),
            total_amount=Decimal("1062.00"),
            status="Pending"
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product1,
            quantity=2,
            unit_price=Decimal("500.00"),
            gst_rate=Decimal("18.00"),
            subtotal=Decimal("900.00"),
            total=Decimal("1062.00")
        )

        self.client.login(username="distributor1", password="Password@123")

        # List view
        response = self.client.get(reverse('invoice_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INV-20260825-0001")
        self.assertContains(response, "Rahul Sharma")

        # Detail view
        response = self.client.get(reverse('invoice_detail', kwargs={'pk': invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INV-20260825-0001")
        self.assertContains(response, "Wireless Mouse")
        self.assertContains(response, "1062.00")

    def test_pdf_generation_library_configured(self):
        """Task 26: Test xhtml2pdf library is configured and produces valid PDF binary stream"""
        from billing.utils import render_to_pdf
        invoice = Invoice.objects.create(
            invoice_number="INV-20260826-PDF1",
            customer=self.customer1,
            distributor=self.distributor1,
            subtotal=Decimal("500.00"),
            gst_amount=Decimal("90.00"),
            total_amount=Decimal("590.00"),
            status="Pending"
        )
        items = [
            InvoiceItem.objects.create(
                invoice=invoice,
                product=self.product1,
                quantity=1,
                unit_price=Decimal("500.00"),
                gst_rate=Decimal("18.00"),
                subtotal=Decimal("500.00"),
                total=Decimal("590.00")
            )
        ]

        pdf_response = render_to_pdf('billing/invoice_pdf.html', {
            'invoice': invoice,
            'items': items,
        })
        self.assertIsNotNone(pdf_response)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        self.assertTrue(pdf_response.content.startswith(b'%PDF'))

    def test_invoice_pdf_download_view_and_isolation(self):
        """Task 27: Test invoice_pdf download endpoint and multi-tenant security isolation"""
        invoice = Invoice.objects.create(
            invoice_number="INV-20260826-PDFVIEW",
            customer=self.customer1,
            distributor=self.distributor1,
            subtotal=Decimal("500.00"),
            gst_amount=Decimal("90.00"),
            total_amount=Decimal("590.00"),
            status="Pending"
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product1,
            quantity=1,
            unit_price=Decimal("500.00"),
            gst_rate=Decimal("18.00"),
            subtotal=Decimal("500.00"),
            total=Decimal("590.00")
        )

        # 1. Distributor 1 downloads their own PDF -> HTTP 200 attachment
        self.client.login(username="distributor1", password="Password@123")
        response = self.client.get(reverse('invoice_pdf', kwargs={'pk': invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('INV-20260826-PDFVIEW.pdf', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

        # 2. Distributor 2 tries to download Distributor 1's PDF -> HTTP 404 (Security check)
        self.client.login(username="distributor2", password="Password@123")
        response2 = self.client.get(reverse('invoice_pdf', kwargs={'pk': invoice.pk}))
        self.assertEqual(response2.status_code, 404)

    def test_invoice_qr_code_generation_and_detail_view(self):
        """Task 28: Test dynamic QR code generation from invoice data and detail view rendering"""
        from billing.views import generate_invoice_qr
        import base64

        invoice = Invoice.objects.create(
            invoice_number="INV-20260827-QRTEST",
            customer=self.customer1,
            distributor=self.distributor1,
            subtotal=Decimal("1000.00"),
            gst_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            status="Pending"
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product1,
            quantity=2,
            unit_price=Decimal("500.00"),
            gst_rate=Decimal("18.00"),
            subtotal=Decimal("1000.00"),
            total=Decimal("1180.00")
        )

        # 1. Test generate_invoice_qr helper function produces valid base64 PNG data
        qr_b64 = generate_invoice_qr(invoice)
        self.assertIsInstance(qr_b64, str)
        self.assertTrue(len(qr_b64) > 100)
        decoded_bytes = base64.b64decode(qr_b64)
        self.assertTrue(decoded_bytes.startswith(b'\x89PNG\r\n\x1a\n'))

        # 2. Test invoice_detail view embeds QR in context and response HTML
        self.client.login(username="distributor1", password="Password@123")
        response = self.client.get(reverse('invoice_detail', kwargs={'pk': invoice.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertIn('qr_code', response.context)
        self.assertEqual(response.context['qr_code'], qr_b64)
        self.assertContains(response, 'data:image/png;base64,')
        self.assertContains(response, 'Invoice Verification QR Code')

    def test_dynamic_invoice_and_item_retrieval_with_product_summary(self):
        """Task 29: Test dynamic retrieval of customer, date, total bill, and product summary in invoice directory"""
        invoice = Invoice.objects.create(
            invoice_number="INV-20260827-TASK29",
            customer=self.customer1,
            distributor=self.distributor1,
            subtotal=Decimal("1500.00"),
            gst_amount=Decimal("270.00"),
            total_amount=Decimal("1770.00"),
            status="Pending"
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product1,
            quantity=3,
            unit_price=Decimal("500.00"),
            gst_rate=Decimal("18.00"),
            subtotal=Decimal("1500.00"),
            total=Decimal("1770.00")
        )

        self.client.login(username="distributor1", password="Password@123")
        response = self.client.get(reverse('invoice_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "INV-20260827-TASK29")
        self.assertContains(response, self.customer1.name)
        self.assertContains(response, "1770.00")
        self.assertContains(response, f"{self.product1.name} (x3)")
        self.assertContains(response, "1 Item")

    def test_invoice_list_pagination(self):
        """Task 29: Test pagination functionality when invoices exceed 10 records"""
        for i in range(12):
            inv = Invoice.objects.create(
                invoice_number=f"INV-PAG-{i:03d}",
                customer=self.customer1,
                distributor=self.distributor1,
                subtotal=Decimal("100.00"),
                gst_amount=Decimal("18.00"),
                total_amount=Decimal("118.00"),
                status="Pending"
            )
            InvoiceItem.objects.create(
                invoice=inv,
                product=self.product1,
                quantity=1,
                unit_price=Decimal("100.00"),
                gst_rate=Decimal("18.00"),
                subtotal=Decimal("100.00"),
                total=Decimal("118.00")
            )

        self.client.login(username="distributor1", password="Password@123")
        # Page 1
        response = self.client.get(reverse('invoice_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['invoices']), 10)
        self.assertTrue(response.context['page_obj'].has_next())

        # Page 2
        response_p2 = self.client.get(reverse('invoice_list') + '?page=2')
        self.assertEqual(response_p2.status_code, 200)
        self.assertTrue(len(response_p2.context['invoices']) >= 2)

    def test_invoice_pdf_dynamic_qr_code_embedding(self):
        """Task 30: Test that generated QR code is dynamically embedded in the invoice PDF export"""
        invoice = Invoice.objects.create(
            invoice_number="INV-20260827-PDFQR",
            customer=self.customer1,
            distributor=self.distributor1,
            subtotal=Decimal("2000.00"),
            gst_amount=Decimal("360.00"),
            total_amount=Decimal("2360.00"),
            status="Pending"
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product1,
            quantity=4,
            unit_price=Decimal("500.00"),
            gst_rate=Decimal("18.00"),
            subtotal=Decimal("2000.00"),
            total=Decimal("2360.00")
        )

        self.client.login(username="distributor1", password="Password@123")
        response = self.client.get(reverse('invoice_pdf', kwargs={'pk': invoice.pk}))

        # Validate HTTP 200 and Content-Type for application/pdf
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment; filename="INV-20260827-PDFQR.pdf"', response['Content-Disposition'])

        # Validate PDF binary content begins with %PDF header
        pdf_bytes = response.content
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertTrue(len(pdf_bytes) > 1000)

    def test_dynamic_upi_payment_qr_code_generation_and_views(self):
        """Test dynamic UPI Scan & Pay QR generation, upi:// URI format, and views embedding"""
        from billing.views import generate_upi_qr
        import base64

        invoice = Invoice.objects.create(
            invoice_number="INV-20260908-UPITEST",
            customer=self.customer1,
            distributor=self.distributor1,
            subtotal=Decimal("3000.00"),
            gst_amount=Decimal("540.00"),
            total_amount=Decimal("3540.00"),
            status="Pending"
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            product=self.product1,
            quantity=6,
            unit_price=Decimal("500.00"),
            gst_rate=Decimal("18.00"),
            subtotal=Decimal("3000.00"),
            total=Decimal("3540.00")
        )

        # 1. Test generate_upi_qr output
        upi_qr_b64, upi_uri, upi_id = generate_upi_qr(invoice)
        self.assertTrue(upi_uri.startswith("upi://pay?"))
        self.assertIn("am=3540.00", upi_uri)
        self.assertIn("cu=INR", upi_uri)
        self.assertIn("Bill%20INV-20260908-UPITEST", upi_uri)
        self.assertEqual(upi_id, "9876543210@upi")

        # Verify base64 PNG image
        decoded_bytes = base64.b64decode(upi_qr_b64)
        self.assertTrue(decoded_bytes.startswith(b'\x89PNG\r\n\x1a\n'))

        # 2. Test invoice_detail view renders UPI Card & button
        self.client.login(username="distributor1", password="Password@123")
        detail_resp = self.client.get(reverse('invoice_detail', kwargs={'pk': invoice.pk}))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn('upi_qr_code', detail_resp.context)
        self.assertIn('upi_uri', detail_resp.context)
        self.assertContains(detail_resp, "UPI Instant Pay")
        self.assertContains(detail_resp, "9876543210@upi")
        self.assertContains(detail_resp, "3540.00")

        # 3. Test invoice_pdf contains embedded UPI section
        pdf_resp = self.client.get(reverse('invoice_pdf', kwargs={'pk': invoice.pk}))
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertEqual(pdf_resp['Content-Type'], 'application/pdf')
        self.assertTrue(pdf_resp.content.startswith(b'%PDF'))


class CustomerRegistrationAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.distributor = User.objects.create_user(
            username="distributor_api",
            email="dist_api@example.com",
            password="Password@123",
            first_name="Distributor API"
        )
        self.distributor2 = User.objects.create_user(
            username="distributor_other",
            email="dist_other@example.com",
            password="Password@123",
            first_name="Other Distributor"
        )

    def test_customer_register_api_success_json(self):
        """Authenticated distributor successfully registers customer via JSON"""
        self.client.login(username="distributor_api", password="Password@123")
        payload = {
            "name": "Anil Ambani",
            "phone": "9876501234",
            "email": "anil@example.com",
            "address": "404 Reliance House, SG Highway",
            "city": "Ahmedabad",
            "state": "Gujarat",
            "pincode": "380015",
            "is_active": True
        }
        response = self.client.post(
            reverse("customer_register_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        res_data = response.json()
        self.assertEqual(res_data["status"], "success")
        self.assertEqual(res_data["message"], "Customer registered successfully.")
        self.assertEqual(res_data["data"]["name"], "Anil Ambani")
        self.assertEqual(res_data["data"]["phone"], "9876501234")
        self.assertEqual(res_data["data"]["distributor_id"], self.distributor.id)
        self.assertEqual(res_data["data"]["city"], "Ahmedabad")

        # Database verification
        customer = Customer.objects.get(id=res_data["data"]["id"])
        self.assertEqual(customer.distributor, self.distributor)
        self.assertEqual(customer.name, "Anil Ambani")
        self.assertEqual(customer.phone, "9876501234")

    def test_customer_register_api_success_form_data(self):
        """Authenticated distributor registers customer via standard form POST"""
        self.client.login(username="distributor_api", password="Password@123")
        response = self.client.post(
            reverse("customer_register_api"),
            {
                "name": "Bhavik Parekh",
                "phone": "9123456789",
                "email": "bhavik@example.com",
                "address": "12 Shanti Nagar",
                "city": "Rajkot",
                "state": "Gujarat",
                "pincode": "360001",
                "is_active": "true"
            }
        )
        self.assertEqual(response.status_code, 201)
        res_data = response.json()
        self.assertEqual(res_data["status"], "success")
        self.assertEqual(res_data["data"]["name"], "Bhavik Parekh")
        self.assertTrue(Customer.objects.filter(phone="9123456789", distributor=self.distributor).exists())

    def test_customer_register_api_with_basic_auth(self):
        """Unauthenticated client provides HTTP Basic Auth header to register customer"""
        credentials = base64.b64encode(b"distributor_api:Password@123").decode("utf-8")
        payload = {
            "name": "Chetan Bhagat",
            "phone": "9825098250",
            "city": "Surat",
            "state": "Gujarat",
            "pincode": "395007"
        }
        response = self.client.post(
            reverse("customer_register_api"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Basic {credentials}"
        )
        self.assertEqual(response.status_code, 201)
        res_data = response.json()
        self.assertEqual(res_data["status"], "success")
        self.assertEqual(res_data["data"]["distributor_id"], self.distributor.id)

    def test_customer_register_api_with_distributor_id_payload(self):
        """Unauthenticated distributor_id payload is rejected (401); authenticated admin can assign distributor_id."""
        payload = {
            "distributor_id": self.distributor2.id,
            "name": "Dhaval Jani",
            "phone": "9724097240",
            "city": "Vadodara",
            "state": "Gujarat",
            "pincode": "390001"
        }
        # Unauthenticated attempt must be blocked
        response_unauth = self.client.post(
            reverse("customer_register_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response_unauth.status_code, 401)

        # Authenticated admin may assign customer to distributor2
        admin_user = User.objects.create_user(
            username="api_assign_admin",
            email="api_assign_admin@example.com",
            password="AdminPassword@123",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(admin_user)
        response = self.client.post(
            reverse("customer_register_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        res_data = response.json()
        self.assertEqual(res_data["data"]["distributor_id"], self.distributor2.id)
        customer = Customer.objects.get(id=res_data["data"]["id"])
        self.assertEqual(customer.distributor, self.distributor2)

    def test_customer_register_api_unauthorized(self):
        """Unauthenticated request without valid distributor credentials returns 401"""
        payload = {
            "name": "Ghost Customer",
            "phone": "9999999999",
            "city": "Nowhere",
            "state": "Gujarat",
            "pincode": "380001"
        }
        response = self.client.post(
            reverse("customer_register_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)
        res_data = response.json()
        self.assertEqual(res_data["status"], "error")
        self.assertIn("Authentication required", res_data["message"])

    def test_customer_register_api_validation_errors(self):
        """Validation errors return 400 Bad Request with field details"""
        self.client.login(username="distributor_api", password="Password@123")
        payload = {
            "name": "A",             # too short (<3)
            "phone": "123",           # invalid phone (<10 digits)
            "email": "invalid-email", # invalid email format
            "city": "",               # missing city
            "state": "",              # missing state
            "pincode": "12"           # invalid pincode (<5 digits)
        }
        response = self.client.post(
            reverse("customer_register_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        res_data = response.json()
        self.assertEqual(res_data["status"], "error")
        self.assertIn("name", res_data["errors"])
        self.assertIn("phone", res_data["errors"])
        self.assertIn("email", res_data["errors"])
        self.assertIn("city", res_data["errors"])
        self.assertIn("state", res_data["errors"])
        self.assertIn("pincode", res_data["errors"])

    def test_customer_register_api_method_not_allowed(self):
        """Non-POST requests return 405 Method Not Allowed"""
        response = self.client.get(reverse("customer_register_api"))
        self.assertEqual(response.status_code, 405)
        res_data = response.json()
        self.assertEqual(res_data["status"], "error")
        self.assertIn("Method not allowed", res_data["message"])

    def test_customer_register_api_malformed_json(self):
        """Malformed JSON payload returns 400 Bad Request"""
        self.client.login(username="distributor_api", password="Password@123")
        response = self.client.post(
            reverse("customer_register_api"),
            data="{invalid_json:",
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        res_data = response.json()
        self.assertEqual(res_data["status"], "error")
        self.assertIn("Malformed JSON", res_data["message"])

    def test_customer_register_api_url_aliases(self):
        """All supported endpoint paths resolve and respond correctly"""
        self.client.login(username="distributor_api", password="Password@123")
        for url_name in ["customer_register_api", "api_customer_register", "api_distributor_customer_register"]:
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 405)


class CustomerRegistrationFrontendTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.distributor = User.objects.create_user(
            username="distributor_ui",
            email="dist_ui@example.com",
            password="Password@123",
            first_name="Distributor Front"
        )

    def test_customer_register_page_unauthenticated_redirect(self):
        """Unauthenticated visitor is redirected to login page"""
        response = self.client.get(reverse("customer_register"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_customer_register_page_renders_elements(self):
        """Authenticated distributor sees the customer registration form with all required fields"""
        self.client.login(username="distributor_ui", password="Password@123")
        response = self.client.get(reverse("customer_register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "billing/customer_register.html")
        self.assertContains(response, "Customer Registration")
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="phone"')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="address"')
        self.assertContains(response, 'name="city"')
        self.assertContains(response, 'name="state"')
        self.assertContains(response, 'name="pincode"')
        self.assertContains(response, 'name="is_active"')
        self.assertContains(response, "Save & Register Customer")

    def test_customer_register_post_success(self):
        """Submitting valid registration form creates Customer and redirects to list"""
        self.client.login(username="distributor_ui", password="Password@123")
        response = self.client.post(reverse("customer_register"), {
            "name": "Manish Malhotra",
            "phone": "9876543211",
            "email": "manish@example.com",
            "address": "701 Fashion Street",
            "city": "Surat",
            "state": "Gujarat",
            "pincode": "395003",
            "is_active": "on"
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("customer_list"))
        
        # Verify in database
        self.assertTrue(Customer.objects.filter(phone="9876543211", distributor=self.distributor).exists())
        cust = Customer.objects.get(phone="9876543211")
        self.assertEqual(cust.name, "Manish Malhotra")
        self.assertEqual(cust.city, "Surat")

    def test_customer_register_post_validation_errors(self):
        """Submitting invalid form re-renders form with error messages"""
        self.client.login(username="distributor_ui", password="Password@123")
        response = self.client.post(reverse("customer_register"), {
            "name": "M",        # <3 chars
            "phone": "invalid",  # not 10 digits
            "city": "",          # empty
            "state": "",         # empty
            "pincode": "00"      # <5 digits
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "billing/customer_register.html")
        self.assertIn("name", response.context["errors"])
        self.assertIn("phone", response.context["errors"])
        self.assertIn("city", response.context["errors"])
        self.assertIn("state", response.context["errors"])
        self.assertIn("pincode", response.context["errors"])

    def test_customer_register_routes_alias(self):
        """Route aliases customer_register, customer_register_alias, customer_register_page resolve properly"""
        self.client.login(username="distributor_ui", password="Password@123")
        for r_name in ["customer_register", "customer_register_alias", "customer_register_page"]:
            resp = self.client.get(reverse(r_name))
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "billing/customer_register.html")


class ProductCRUDOperationsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.distributor = User.objects.create_user(
            username="dist_product_crud",
            email="prod_crud@example.com",
            password="Password@123",
            first_name="Product Tester"
        )
        self.distributor2 = User.objects.create_user(
            username="dist_other_prod",
            email="other_prod@example.com",
            password="Password@123",
            first_name="Other Tester"
        )

    def test_web_product_create(self):
        """Web UI: Create new product"""
        self.client.login(username="dist_product_crud", password="Password@123")
        response = self.client.post(reverse("product_add"), {
            "name": "Bluetooth Speaker",
            "category": "Audio",
            "price": "1299.00",
            "stock": "25",
            "gst_rate": "18.00",
            "description": "Portable waterproof speaker",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(name="Bluetooth Speaker", distributor=self.distributor).exists())

    def test_web_product_detail_and_isolation(self):
        """Web UI: Read product details and verify multi-tenant isolation"""
        prod = Product.objects.create(
            distributor=self.distributor,
            name="Smart Watch",
            category="Wearables",
            price=Decimal("2499.00"),
            stock=15,
            gst_rate=Decimal("18.00"),
            description="Fitness tracker with AMOLED display"
        )
        self.client.login(username="dist_product_crud", password="Password@123")
        response = self.client.get(reverse("product_detail", kwargs={"pk": prod.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "billing/product_detail.html")
        self.assertContains(response, "Smart Watch")
        self.assertContains(response, "2499.00")

        # Distributor 2 cannot view distributor 1's product
        self.client.login(username="dist_other_prod", password="Password@123")
        response2 = self.client.get(reverse("product_detail", kwargs={"pk": prod.pk}))
        self.assertEqual(response2.status_code, 404)

    def test_web_product_update(self):
        """Web UI: Update product details"""
        prod = Product.objects.create(
            distributor=self.distributor,
            name="USB Cable",
            category="Accessories",
            price=Decimal("199.00"),
            stock=100,
            gst_rate=Decimal("18.00")
        )
        self.client.login(username="dist_product_crud", password="Password@123")
        response = self.client.post(reverse("product_edit", kwargs={"pk": prod.pk}), {
            "name": "USB-C Fast Cable",
            "category": "Accessories",
            "price": "249.00",
            "stock": "80",
            "gst_rate": "18.00",
            "description": "Braided 65W fast charging cable"
        })
        self.assertEqual(response.status_code, 302)
        prod.refresh_from_db()
        self.assertEqual(prod.name, "USB-C Fast Cable")
        self.assertEqual(prod.price, Decimal("249.00"))

    def test_web_product_delete(self):
        """Web UI: Delete product safely via POST"""
        prod = Product.objects.create(
            distributor=self.distributor,
            name="Delete Me",
            category="Temp",
            price=Decimal("50.00"),
            stock=5,
            gst_rate=Decimal("5.00")
        )
        self.client.login(username="dist_product_crud", password="Password@123")
        response = self.client.post(reverse("product_delete", kwargs={"pk": prod.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=prod.pk).exists())

    def test_api_product_crud_lifecycle(self):
        """REST API: Product CRUD full lifecycle (Create, Read, Update, Delete)"""
        self.client.login(username="dist_product_crud", password="Password@123")

        # 1. API Create
        create_payload = {
            "name": "Gaming Mousepad",
            "category": "Gaming",
            "price": "399.00",
            "stock": 40,
            "gst_rate": "18.00",
            "description": "XL extended desk mat"
        }
        res_create = self.client.post(
            reverse("api_products"),
            data=json.dumps(create_payload),
            content_type="application/json"
        )
        self.assertEqual(res_create.status_code, 201)
        res_data = res_create.json()
        self.assertEqual(res_data["status"], "success")
        prod_id = res_data["data"]["id"]

        # 2. API List
        res_list = self.client.get(reverse("api_products"))
        self.assertEqual(res_list.status_code, 200)
        self.assertGreaterEqual(res_list.json()["count"], 1)

        # 3. API Read Single
        res_read = self.client.get(reverse("api_product_detail", kwargs={"pk": prod_id}))
        self.assertEqual(res_read.status_code, 200)
        self.assertEqual(res_read.json()["data"]["name"], "Gaming Mousepad")

        # 4. API Update
        res_update = self.client.post(
            reverse("api_product_detail", kwargs={"pk": prod_id}),
            data=json.dumps({"price": "449.00", "stock": 35}),
            content_type="application/json"
        )
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.json()["data"]["price"], "449.00")

        # 5. API Delete
        res_delete = self.client.delete(reverse("api_product_detail", kwargs={"pk": prod_id}))
        self.assertEqual(res_delete.status_code, 200)
        self.assertFalse(Product.objects.filter(pk=prod_id).exists())


class ValidationAndTestingBothModulesTests(TestCase):
    """
    Task 41: Perform validation and testing on both modules.
    Exhaustive validation test suite covering:
    1. Customer Module Form & Web UI validation edge-cases
    2. Customer Module REST API validation & security
    3. Customer Module Multi-Tenant isolation & unauthorized access
    4. Product Module Form & Web UI validation edge-cases
    5. Product Module REST API validation & security
    6. Product Module Multi-Tenant isolation & unauthorized access
    7. Cross-Module Data Integrity & Boundary Assurance
    """
    def setUp(self):
        self.client = Client()
        self.distributor1 = User.objects.create_user(
            username="dist_val_one",
            email="distval1@example.com",
            password="Password@123",
            first_name="Distributor Valid One"
        )
        self.distributor2 = User.objects.create_user(
            username="dist_val_two",
            email="distval2@example.com",
            password="Password@123",
            first_name="Distributor Valid Two"
        )

        self.customer1 = Customer.objects.create(
            distributor=self.distributor1,
            name="Anand Sharma",
            email="anand@example.com",
            phone="9876543210",
            address="123 Civil Lines",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001",
            is_active=True
        )

        self.product1 = Product.objects.create(
            distributor=self.distributor1,
            name="Wireless Mouse",
            category="Electronics",
            price=Decimal("499.00"),
            stock=50,
            gst_rate=Decimal("18.00"),
            description="2.4GHz optical mouse"
        )

    # ---------------------------------------------------------
    # MODULE 1: CUSTOMER FORM & WEB UI VALIDATION TESTS
    # ---------------------------------------------------------
    def test_customer_form_validation(self):
        """Unit test CustomerForm with valid, invalid phone, short name, and bad pincode"""
        # Valid form
        form = CustomerForm(data={
            "name": "Priya Patel",
            "email": "priya@example.com",
            "phone": "9825012345",
            "address": "45 Lotus Park",
            "city": "Vadodara",
            "state": "Gujarat",
            "pincode": "390001",
            "is_active": True
        })
        self.assertTrue(form.is_valid())

        # Invalid: short name
        form_short = CustomerForm(data={"name": "AB", "phone": "9825012345", "city": "Surat", "state": "Gujarat", "pincode": "395001"})
        self.assertFalse(form_short.is_valid())
        self.assertIn("name", form_short.errors)

        # Invalid: phone with letters
        form_bad_phone = CustomerForm(data={"name": "Valid Name", "phone": "982501234a", "city": "Surat", "state": "Gujarat", "pincode": "395001"})
        self.assertFalse(form_bad_phone.is_valid())
        self.assertIn("phone", form_bad_phone.errors)

        # Invalid: pincode with letters
        form_bad_pin = CustomerForm(data={"name": "Valid Name", "phone": "9825012345", "city": "Surat", "state": "Gujarat", "pincode": "PIN123"})
        self.assertFalse(form_bad_pin.is_valid())
        self.assertIn("pincode", form_bad_pin.errors)

    def test_customer_web_registration_validation_rules(self):
        """Web UI: Validate required fields, formats, and limits for customer registration"""
        self.client.login(username="dist_val_one", password="Password@123")

        # 1. Missing required fields
        res = self.client.post(reverse("customer_register"), {
            "name": "",
            "phone": "",
            "city": "",
            "state": "",
            "pincode": ""
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("name", res.context["errors"])
        self.assertIn("phone", res.context["errors"])
        self.assertIn("city", res.context["errors"])
        self.assertIn("state", res.context["errors"])
        self.assertIn("pincode", res.context["errors"])

        # 2. Invalid phone (9 digits, 11 digits, alpha)
        for bad_p in ["123456789", "12345678901", "98765abcde"]:
            res = self.client.post(reverse("customer_register"), {
                "name": "Kavita Rao",
                "phone": bad_p,
                "city": "Rajkot",
                "state": "Gujarat",
                "pincode": "360001"
            })
            self.assertEqual(res.status_code, 200)
            self.assertIn("phone", res.context["errors"])

        # 3. Invalid email format
        res = self.client.post(reverse("customer_register"), {
            "name": "Kavita Rao",
            "phone": "9876543219",
            "email": "not-a-valid-email",
            "city": "Rajkot",
            "state": "Gujarat",
            "pincode": "360001"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("email", res.context["errors"])

        # 4. Successful registration creates Customer associated to logged-in distributor
        res_ok = self.client.post(reverse("customer_register"), {
            "name": "Kavita Rao",
            "phone": "9876543219",
            "email": "kavita@example.com",
            "address": "12 Palace Road",
            "city": "Rajkot",
            "state": "Gujarat",
            "pincode": "360001",
            "is_active": "on"
        })
        self.assertEqual(res_ok.status_code, 302)
        created = Customer.objects.filter(phone="9876543219").first()
        self.assertIsNotNone(created)
        self.assertEqual(created.distributor, self.distributor1)

    def test_customer_web_edit_and_delete_security(self):
        """Web UI: Test validation on edit, cross-tenant isolation, and safe POST delete"""
        # 1. Edit with invalid phone fails
        self.client.login(username="dist_val_one", password="Password@123")
        res_edit_invalid = self.client.post(reverse("customer_edit", kwargs={"pk": self.customer1.pk}), {
            "name": "Anand Updated",
            "phone": "invalid-phone",
            "city": "Ahmedabad",
            "state": "Gujarat",
            "pincode": "380001"
        })
        self.assertEqual(res_edit_invalid.status_code, 200)
        self.customer1.refresh_from_db()
        self.assertEqual(self.customer1.name, "Anand Sharma")

        # 2. Distributor 2 cannot edit Distributor 1's customer (returns 404)
        self.client.login(username="dist_val_two", password="Password@123")
        res_cross_edit = self.client.post(reverse("customer_edit", kwargs={"pk": self.customer1.pk}), {
            "name": "Hacked Name",
            "phone": "9876543210",
            "city": "Ahmedabad",
            "state": "Gujarat",
            "pincode": "380001"
        })
        self.assertEqual(res_cross_edit.status_code, 404)

        # 3. GET request to delete does not delete
        self.client.login(username="dist_val_one", password="Password@123")
        res_get_del = self.client.get(reverse("customer_delete", kwargs={"pk": self.customer1.pk}))
        self.assertEqual(res_get_del.status_code, 302)
        self.assertTrue(Customer.objects.filter(pk=self.customer1.pk).exists())

        # 4. Cross-distributor delete returns 404
        self.client.login(username="dist_val_two", password="Password@123")
        res_cross_del = self.client.post(reverse("customer_delete", kwargs={"pk": self.customer1.pk}))
        self.assertEqual(res_cross_del.status_code, 404)
        self.assertTrue(Customer.objects.filter(pk=self.customer1.pk).exists())

    def test_customer_api_validation_suite(self):
        """Customer Registration API: Test 401 unauthenticated, 400 validation errors, and 201 success"""
        # Unauthenticated
        res_unauth = self.client.post(reverse("customer_register_api"), data={}, content_type="application/json")
        self.assertEqual(res_unauth.status_code, 401)

        # Authenticated
        self.client.login(username="dist_val_one", password="Password@123")

        # Missing required fields
        res_missing = self.client.post(reverse("customer_register_api"), data=json.dumps({}), content_type="application/json")
        self.assertEqual(res_missing.status_code, 400)
        self.assertIn("errors", res_missing.json())

        # Invalid formats
        res_bad = self.client.post(reverse("customer_register_api"), data=json.dumps({
            "name": "Al",
            "phone": "123",
            "email": "bad_email",
            "city": "",
            "state": "",
            "pincode": "99"
        }), content_type="application/json")
        self.assertEqual(res_bad.status_code, 400)
        errors = res_bad.json()["errors"]
        self.assertIn("name", errors)
        self.assertIn("phone", errors)
        self.assertIn("email", errors)
        self.assertIn("pincode", errors)

        # Valid registration
        res_ok = self.client.post(reverse("customer_register_api"), data=json.dumps({
            "name": "Bharat Mehta",
            "phone": "9898989898",
            "email": "bharat@example.com",
            "city": "Bhavnagar",
            "state": "Gujarat",
            "pincode": "364001",
            "is_active": True
        }), content_type="application/json")
        self.assertEqual(res_ok.status_code, 201)
        self.assertEqual(res_ok.json()["status"], "success")
        self.assertTrue(Customer.objects.filter(phone="9898989898", distributor=self.distributor1).exists())

    # ---------------------------------------------------------
    # MODULE 2: PRODUCT FORM & WEB UI VALIDATION TESTS
    # ---------------------------------------------------------
    def test_product_form_validation(self):
        """Unit test ProductForm with valid data, short name, zero price, negative stock, and invalid GST"""
        # Valid form
        form = ProductForm(data={
            "name": "Mechanical Keyboard",
            "category": "Accessories",
            "price": "3499.00",
            "stock": 20,
            "gst_rate": "18.00",
            "description": "RGB mechanical keyboard"
        })
        self.assertTrue(form.is_valid())

        # Invalid: short name (<2 chars)
        form_short = ProductForm(data={"name": "X", "category": "General", "price": "100.00", "stock": 5, "gst_rate": "18.00"})
        self.assertFalse(form_short.is_valid())
        self.assertIn("name", form_short.errors)

        # Invalid: zero or negative price
        form_zero_price = ProductForm(data={"name": "Item", "category": "General", "price": "0.00", "stock": 5, "gst_rate": "18.00"})
        self.assertFalse(form_zero_price.is_valid())
        self.assertIn("price", form_zero_price.errors)

        # Invalid: negative stock
        form_neg_stock = ProductForm(data={"name": "Item", "category": "General", "price": "50.00", "stock": -3, "gst_rate": "18.00"})
        self.assertFalse(form_neg_stock.is_valid())
        self.assertIn("stock", form_neg_stock.errors)

        # Invalid: GST rate > 100
        form_bad_gst = ProductForm(data={"name": "Item", "category": "General", "price": "50.00", "stock": 10, "gst_rate": "150.00"})
        self.assertFalse(form_bad_gst.is_valid())
        self.assertIn("gst_rate", form_bad_gst.errors)

    def test_product_web_add_and_edit_validation_rules(self):
        """Web UI: Test edge-case inputs when creating and editing products"""
        self.client.login(username="dist_val_one", password="Password@123")

        # 1. Missing fields
        res_empty = self.client.post(reverse("product_add"), {"name": ""})
        self.assertEqual(res_empty.status_code, 200)
        self.assertIn("error", res_empty.context)

        # 2. Product name < 2 chars
        res_name = self.client.post(reverse("product_add"), {
            "name": "A",
            "category": "Cat",
            "price": "100.00",
            "stock": "10",
            "gst_rate": "18.00"
        })
        self.assertEqual(res_name.status_code, 200)
        self.assertIn("error", res_name.context)

        # 3. Price <= 0 or non-numeric
        for bad_p in ["0", "-25.00", "not-a-price"]:
            res_p = self.client.post(reverse("product_add"), {
                "name": "Valid Product",
                "category": "Cat",
                "price": bad_p,
                "stock": "10",
                "gst_rate": "18.00"
            })
            self.assertEqual(res_p.status_code, 200)
            self.assertIn("error", res_p.context)

        # 4. Stock < 0 or non-integer
        for bad_s in ["-1", "5.5", "invalid"]:
            res_s = self.client.post(reverse("product_add"), {
                "name": "Valid Product",
                "category": "Cat",
                "price": "199.00",
                "stock": bad_s,
                "gst_rate": "18.00"
            })
            self.assertEqual(res_s.status_code, 200)
            self.assertIn("error", res_s.context)

        # 5. GST rate < 0 or > 100
        for bad_g in ["-5", "105", "xyz"]:
            res_g = self.client.post(reverse("product_add"), {
                "name": "Valid Product",
                "category": "Cat",
                "price": "199.00",
                "stock": "10",
                "gst_rate": bad_g
            })
            self.assertEqual(res_g.status_code, 200)
            self.assertIn("error", res_g.context)

        # 6. Valid creation succeeds
        res_ok = self.client.post(reverse("product_add"), {
            "name": "HD Webcam",
            "category": "Cameras",
            "price": "1499.00",
            "stock": "15",
            "gst_rate": "18.00",
            "description": "1080p full HD webcam"
        })
        self.assertEqual(res_ok.status_code, 302)
        prod = Product.objects.filter(name="HD Webcam").first()
        self.assertIsNotNone(prod)
        self.assertEqual(prod.distributor, self.distributor1)

        # 7. Edit with invalid zero price fails
        res_edit_bad = self.client.post(reverse("product_edit", kwargs={"pk": prod.pk}), {
            "name": "HD Webcam",
            "category": "Cameras",
            "price": "0.00",
            "stock": "15",
            "gst_rate": "18.00"
        })
        self.assertEqual(res_edit_bad.status_code, 200)
        self.assertIn("error", res_edit_bad.context)
        prod.refresh_from_db()
        self.assertEqual(prod.price, Decimal("1499.00"))

        # 8. Edit with valid values succeeds
        res_edit_ok = self.client.post(reverse("product_edit", kwargs={"pk": prod.pk}), {
            "name": "HD Webcam Pro 4K",
            "category": "Cameras",
            "price": "1999.00",
            "stock": "12",
            "gst_rate": "18.00",
            "description": "Updated 4K webcam"
        })
        self.assertEqual(res_edit_ok.status_code, 302)
        prod.refresh_from_db()
        self.assertEqual(prod.name, "HD Webcam Pro 4K")
        self.assertEqual(prod.price, Decimal("1999.00"))

    def test_product_web_security_and_delete(self):
        """Web UI: Test multi-tenant isolation on product views and safe delete method"""
        # 1. Distributor 2 cannot view or edit Distributor 1's product
        self.client.login(username="dist_val_two", password="Password@123")
        res_view = self.client.get(reverse("product_detail", kwargs={"pk": self.product1.pk}))
        self.assertEqual(res_view.status_code, 404)

        res_edit = self.client.get(reverse("product_edit", kwargs={"pk": self.product1.pk}))
        self.assertEqual(res_edit.status_code, 404)

        # 2. GET request to delete does NOT delete
        self.client.login(username="dist_val_one", password="Password@123")
        res_get_del = self.client.get(reverse("product_delete", kwargs={"pk": self.product1.pk}))
        self.assertEqual(res_get_del.status_code, 302)
        self.assertTrue(Product.objects.filter(pk=self.product1.pk).exists())

        # 3. Cross-distributor delete returns 404
        self.client.login(username="dist_val_two", password="Password@123")
        res_cross_del = self.client.post(reverse("product_delete", kwargs={"pk": self.product1.pk}))
        self.assertEqual(res_cross_del.status_code, 404)
        self.assertTrue(Product.objects.filter(pk=self.product1.pk).exists())

        # 4. Valid POST by owner deletes product
        self.client.login(username="dist_val_one", password="Password@123")
        res_del = self.client.post(reverse("product_delete", kwargs={"pk": self.product1.pk}))
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=self.product1.pk).exists())

    def test_product_api_validation_suite(self):
        """Product REST API: Test authentication, malformed payloads, field validations, and CRUD updates"""
        # 1. Unauthenticated -> 401
        res_unauth = self.client.post(reverse("api_products"), data={}, content_type="application/json")
        self.assertEqual(res_unauth.status_code, 401)

        self.client.login(username="dist_val_one", password="Password@123")

        # 2. Malformed JSON -> 400
        res_malformed = self.client.post(reverse("api_products"), data="{bad json", content_type="application/json")
        self.assertEqual(res_malformed.status_code, 400)

        # 3. Missing fields -> 400
        res_missing = self.client.post(reverse("api_products"), data=json.dumps({}), content_type="application/json")
        self.assertEqual(res_missing.status_code, 400)
        self.assertIn("errors", res_missing.json())

        # 4. Invalid fields (price <= 0, stock < 0, gst > 100) -> 400
        res_invalid = self.client.post(reverse("api_products"), data=json.dumps({
            "name": "Microphone",
            "category": "Audio",
            "price": "-10.00",
            "stock": -5,
            "gst_rate": 120.00
        }), content_type="application/json")
        self.assertEqual(res_invalid.status_code, 400)
        errs = res_invalid.json()["errors"]
        self.assertIn("price", errs)
        self.assertIn("stock", errs)
        self.assertIn("gst_rate", errs)

        # 5. Successful API create
        res_create = self.client.post(reverse("api_products"), data=json.dumps({
            "name": "Condenser Mic",
            "category": "Audio",
            "price": "2999.00",
            "stock": 25,
            "gst_rate": 18.00,
            "description": "Studio recording microphone"
        }), content_type="application/json")
        self.assertEqual(res_create.status_code, 201)
        new_prod_id = res_create.json()["data"]["id"]

        # 6. API Update with invalid price returns 400
        res_upd_bad = self.client.post(
            reverse("api_product_detail", kwargs={"pk": new_prod_id}),
            data=json.dumps({"price": "-50.00"}),
            content_type="application/json"
        )
        self.assertEqual(res_upd_bad.status_code, 400)

        # 7. Cross-distributor API access returns 404
        self.client.login(username="dist_val_two", password="Password@123")
        res_cross_get = self.client.get(reverse("api_product_detail", kwargs={"pk": new_prod_id}))
        self.assertEqual(res_cross_get.status_code, 404)

    # ---------------------------------------------------------
    # CROSS-MODULE INTEGRATION & TENANT INTEGRITY
    # ---------------------------------------------------------
    def test_both_modules_multi_tenant_isolation_integrity(self):
        """Verify that customer and product listings strictly isolate data between distributors"""
        # Create records for Distributor 2
        cust2 = Customer.objects.create(
            distributor=self.distributor2,
            name="Deepak Joshi",
            email="deepak@example.com",
            phone="9123456789",
            city="Surat",
            state="Gujarat",
            pincode="395002"
        )
        prod2 = Product.objects.create(
            distributor=self.distributor2,
            name="Laser Printer",
            category="Printers",
            price=Decimal("15999.00"),
            stock=8,
            gst_rate=Decimal("18.00")
        )

        # Logged in as Distributor 1
        self.client.login(username="dist_val_one", password="Password@123")

        # Customer List: should contain Customer 1 but NOT Customer 2
        res_cust_list = self.client.get(reverse("customer_list"))
        self.assertEqual(res_cust_list.status_code, 200)
        self.assertContains(res_cust_list, "Anand Sharma")
        self.assertNotContains(res_cust_list, "Deepak Joshi")

        # Product List: should contain Product 1 but NOT Product 2
        res_prod_list = self.client.get(reverse("product_list"))
        self.assertEqual(res_prod_list.status_code, 200)
        self.assertContains(res_prod_list, "Wireless Mouse")
        self.assertNotContains(res_prod_list, "Laser Printer")

        # Search isolation in both modules
        res_search_cust = self.client.get(reverse("customer_list") + "?q=Deepak")
        self.assertNotContains(res_search_cust, "Deepak Joshi")

        res_search_prod = self.client.get(reverse("product_list") + "?q=Printer")
        self.assertNotContains(res_search_prod, "Laser Printer")


class InvoiceReportGenerationFormTests(TestCase):
    """
    Task 43: Build a report generation form for filtering invoices by date range.
    Tests form validation, date range querying, multi-tenancy, and template elements.
    """
    def setUp(self):
        self.client = Client()

        self.distributor1 = User.objects.create_user(
            username="dist_report_one",
            email="distrep1@example.com",
            password="Password@123",
            first_name="Report Tester One"
        )
        self.distributor2 = User.objects.create_user(
            username="dist_report_two",
            email="distrep2@example.com",
            password="Password@123",
            first_name="Report Tester Two"
        )

        self.customer1 = Customer.objects.create(
            distributor=self.distributor1,
            name="Rahul Sharma",
            email="rahul@example.com",
            phone="9876501234",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001"
        )
        self.customer2 = Customer.objects.create(
            distributor=self.distributor2,
            name="Amit Shah",
            email="amit@example.com",
            phone="9876505678",
            city="Surat",
            state="Gujarat",
            pincode="395001"
        )

        self.product1 = Product.objects.create(
            distributor=self.distributor1,
            name="Wireless Barcode Scanner",
            category="Hardware",
            price=Decimal("2500.00"),
            stock=30,
            gst_rate=Decimal("18.00")
        )

        # Invoices for Distributor 1
        self.inv1 = Invoice.objects.create(
            invoice_number="INV-REP-001",
            distributor=self.distributor1,
            customer=self.customer1,
            subtotal=Decimal("2500.00"),
            gst_amount=Decimal("450.00"),
            total_amount=Decimal("2950.00"),
            status="Paid"
        )
        self.inv2 = Invoice.objects.create(
            invoice_number="INV-REP-002",
            distributor=self.distributor1,
            customer=self.customer1,
            subtotal=Decimal("5000.00"),
            gst_amount=Decimal("900.00"),
            total_amount=Decimal("5900.00"),
            status="Pending"
        )

        # Invoice for Distributor 2 (for multi-tenant isolation check)
        self.inv3 = Invoice.objects.create(
            invoice_number="INV-REP-003",
            distributor=self.distributor2,
            customer=self.customer2,
            subtotal=Decimal("1000.00"),
            gst_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            status="Paid"
        )

    def test_report_filter_form_validation(self):
        """Test InvoiceReportFilterForm valid range and invalid range (start > end)"""
        # Valid date range
        valid_form = InvoiceReportFilterForm(data={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "status": "Paid"
        }, distributor=self.distributor1)
        self.assertTrue(valid_form.is_valid())

        # Invalid date range: start_date > end_date
        invalid_form = InvoiceReportFilterForm(data={
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        }, distributor=self.distributor1)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("From Date cannot be later than To Date.", invalid_form.non_field_errors())

    def test_report_view_unauthenticated_redirect(self):
        """Unauthenticated user accessing invoice_report redirects to login"""
        res = self.client.get(reverse("invoice_report"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login/", res.url)

    def test_report_view_renders_form_elements(self):
        """Authenticated distributor sees the report generation form and inputs"""
        self.client.login(username="dist_report_one", password="Password@123")
        res = self.client.get(reverse("invoice_report"))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "billing/invoice_report.html")

        # Check form elements in response
        self.assertContains(res, "Invoice Report Generator")
        self.assertContains(res, 'name="start_date"')
        self.assertContains(res, 'name="end_date"')
        self.assertContains(res, 'name="status"')
        self.assertContains(res, 'name="customer"')
        self.assertContains(res, "Generate Filtered Report")
        self.assertContains(res, "Quick Presets")

    def test_report_filtering_by_date_range(self):
        """Filter invoices by valid date range"""
        self.client.login(username="dist_report_one", password="Password@123")
        self.inv1.refresh_from_db()
        inv_date_str = self.inv1.invoice_date.strftime("%Y-%m-%d")

        # Filter for invoice date: both inv1 and inv2 match
        res = self.client.get(reverse("invoice_report"), {
            "start_date": inv_date_str,
            "end_date": inv_date_str
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "INV-REP-001")
        self.assertContains(res, "INV-REP-002")

        # Filter for past date range: should return empty
        past_str = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")
        res_past = self.client.get(reverse("invoice_report"), {
            "start_date": past_str,
            "end_date": past_str
        })
        self.assertEqual(res_past.status_code, 200)
        self.assertContains(res_past, "No Invoices Found in Selected Range")

    def test_report_filtering_by_status_and_customer(self):
        """Filter invoices by payment status and customer"""
        self.client.login(username="dist_report_one", password="Password@123")

        # Filter status="Paid"
        res_paid = self.client.get(reverse("invoice_report"), {"status": "Paid"})
        self.assertEqual(res_paid.status_code, 200)
        self.assertContains(res_paid, "INV-REP-001")
        self.assertNotContains(res_paid, "INV-REP-002")

        # Filter status="Pending"
        res_pending = self.client.get(reverse("invoice_report"), {"status": "Pending"})
        self.assertEqual(res_pending.status_code, 200)
        self.assertContains(res_pending, "INV-REP-002")

    def test_report_multi_tenant_isolation(self):
        """Distributor 1 cannot see Distributor 2's invoices in generated report"""
        self.client.login(username="dist_report_one", password="Password@123")
        res = self.client.get(reverse("invoice_report"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "INV-REP-001")
        self.assertNotContains(res, "INV-REP-003")

    def test_report_summary_metrics_total_invoices_and_amount_collected(self):
        """Task 44: Verify display of total number of invoices and amount collected within selected range"""
        self.client.login(username="dist_report_one", password="Password@123")
        res = self.client.get(reverse("invoice_report"))
        self.assertEqual(res.status_code, 200)

        # Total 2 invoices for dist_report_one: inv1 (2950.00, Paid) + inv2 (5900.00, Pending) = 8850.00
        self.assertEqual(res.context["total_invoices_count"], 2)
        self.assertAlmostEqual(float(res.context["total_amount_collected"]), 8850.00)
        self.assertAlmostEqual(float(res.context["paid_amount"]), 2950.00)
        self.assertAlmostEqual(float(res.context["pending_amount"]), 5900.00)

        # Check rendered HTML
        self.assertContains(res, "Total Invoices")
        self.assertContains(res, "summaryTotalInvoices")
        self.assertContains(res, "Total Amount")
        self.assertContains(res, "8850.00")
        self.assertContains(res, "2950.00")

    def test_report_summary_metrics_update_with_date_range_filter(self):
        """Task 44: Verify metrics adapt when filtering by date range"""
        self.client.login(username="dist_report_one", password="Password@123")
        past_str = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")

        # Range in past with 0 invoices
        res = self.client.get(reverse("invoice_report"), {
            "start_date": past_str,
            "end_date": past_str,
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["total_invoices_count"], 0)
        self.assertEqual(res.context["total_amount_collected"], 0)
        self.assertEqual(res.context["paid_amount"], 0)
        self.assertEqual(res.context["pending_amount"], 0)
        self.assertContains(res, "0")

    def test_invoice_report_pdf_unauthenticated_redirect(self):
        """Task 45: Unauthenticated access to report PDF redirects to login"""
        res = self.client.get(reverse("invoice_report_pdf"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login/", res.url)

    def test_invoice_report_pdf_generation_success(self):
        """Task 45: Authenticated distributor can download report as PDF using xhtml2pdf"""
        self.client.login(username="dist_report_one", password="Password@123")
        res = self.client.get(reverse("invoice_report_pdf"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertIn("Invoice_Report_", res["Content-Disposition"])
        self.assertTrue(res.content.startswith(b"%PDF-"))

    def test_invoice_report_pdf_with_filters(self):
        """Task 45: Report PDF generation works with date range and status filters"""
        self.client.login(username="dist_report_one", password="Password@123")
        self.inv1.refresh_from_db()
        inv_date_str = self.inv1.invoice_date.strftime("%Y-%m-%d")

        res = self.client.get(reverse("invoice_report_pdf"), {
            "start_date": inv_date_str,
            "end_date": inv_date_str,
            "status": "Paid",
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertTrue(res.content.startswith(b"%PDF-"))

    # =========================================================================
    # TASK 46: Validation to prevent empty date selection or invalid ranges
    # =========================================================================

    def test_report_form_empty_date_selection_validation(self):
        """Task 46: Submitting date filter form with empty dates raises validation error"""
        form = InvoiceReportFilterForm({
            "start_date": "",
            "end_date": "",
            "status": "",
            "customer": "",
        }, distributor=self.distributor1)
        self.assertFalse(form.is_valid())
        self.assertIn("Please select both From Date and To Date", form.non_field_errors()[0])

    def test_report_form_missing_start_date_validation(self):
        """Task 46: Specifying To Date without From Date raises validation error"""
        form = InvoiceReportFilterForm({
            "start_date": "",
            "end_date": "2026-05-10",
        }, distributor=self.distributor1)
        self.assertFalse(form.is_valid())
        self.assertIn("From Date is required when To Date is provided", form.non_field_errors()[0])

    def test_report_form_missing_end_date_validation(self):
        """Task 46: Specifying From Date without To Date raises validation error"""
        form = InvoiceReportFilterForm({
            "start_date": "2026-05-01",
            "end_date": "",
        }, distributor=self.distributor1)
        self.assertFalse(form.is_valid())
        self.assertIn("To Date is required when From Date is provided", form.non_field_errors()[0])

    def test_report_form_invalid_date_range_validation(self):
        """Task 46: Specifying From Date later than To Date raises validation error"""
        form = InvoiceReportFilterForm({
            "start_date": "2026-05-20",
            "end_date": "2026-05-10",
        }, distributor=self.distributor1)
        self.assertFalse(form.is_valid())
        self.assertIn("From Date cannot be later than To Date", form.non_field_errors()[0])

    def test_report_view_renders_validation_error_on_invalid_range(self):
        """Task 46: GET request to invoice_report with inverted dates displays error banner"""
        self.client.login(username="dist_report_one", password="Password@123")
        res = self.client.get(reverse("invoice_report"), {
            "start_date": "2026-05-20",
            "end_date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "From Date cannot be later than To Date")
        self.assertContains(res, "report-form-error")

    def test_invoice_report_pdf_redirects_on_invalid_date_range(self):
        """Task 46: GET request to invoice_report_pdf with invalid range redirects to report page with error"""
        self.client.login(username="dist_report_one", password="Password@123")
        res = self.client.get(reverse("invoice_report_pdf"), {
            "start_date": "2026-05-20",
            "end_date": "2026-05-10",
        })
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse("invoice_report"))


class QRCodeDecoderTests(TestCase):
    """
    Task 47 & 48: Tests for QR code decoder endpoint and decoding functionality.
    """

    def setUp(self):
        import io
        import qrcode
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.distributor = User.objects.create_user(
            username="dist_qr_tester",
            email="qr@tester.com",
            password="Password@123"
        )
        self.customer = Customer.objects.create(
            distributor=self.distributor,
            name="Alpha Corp",
            phone="9876543210",
            email="alpha@corp.com"
        )
        self.invoice = Invoice.objects.create(
            invoice_number="INV-QR-TEST-001",
            distributor=self.distributor,
            customer=self.customer,
            subtotal=Decimal("1000.00"),
            gst_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            status="Paid"
        )

        # Generate a valid test QR image in memory
        qr_text = (
            f"Invoice: {self.invoice.invoice_number}\n"
            f"Customer: {self.customer.name}\n"
            f"Amount: 1180.00\n"
            f"Status: Paid"
        )
        img = qrcode.make(qr_text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self.valid_qr_bytes = buf.getvalue()

        self.valid_qr_uploaded_file = SimpleUploadedFile(
            "sample_qr.png",
            self.valid_qr_bytes,
            content_type="image/png"
        )

    def test_qr_decoder_view_unauthenticated_redirect(self):
        """Task 47: Unauthenticated access to /qr/decode/ redirects to login"""
        res = self.client.get(reverse("qr_decoder"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login/", res.url)

    def test_qr_decoder_view_authenticated_get(self):
        """Task 47: Authenticated distributor can access QR decoder page"""
        self.client.login(username="dist_qr_tester", password="Password@123")
        res = self.client.get(reverse("qr_decoder"))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "billing/qr_decoder.html")
        self.assertContains(res, "QR Code Decoder")
        self.assertContains(res, "Upload QR Code Image")

    def test_qr_decoder_view_post_no_image_error(self):
        """Task 47: Submitting QR decoder form without an image displays error message"""
        self.client.login(username="dist_qr_tester", password="Password@123")
        res = self.client.post(reverse("qr_decoder"), {})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Please select or upload a QR code image to decode.")

    def test_qr_decoder_view_post_valid_image(self):
        """Task 47 & 48: Submitting a valid QR code image successfully decodes and displays details"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        uploaded = SimpleUploadedFile("test_bill_qr.png", self.valid_qr_bytes, content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": uploaded})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "QR code decoded successfully")
        self.assertContains(res, "INV-QR-TEST-001")
        self.assertContains(res, "Alpha Corp")

    def test_qr_decoder_api_method_not_allowed(self):
        """Task 47: GET request to /api/qr/decode/ returns 405 Method Not Allowed"""
        res = self.client.get(reverse("qr_decoder_api"))
        self.assertEqual(res.status_code, 405)
        data = res.json()
        self.assertEqual(data["status"], "error")

    def test_qr_decoder_api_no_image_bad_request(self):
        """Task 47: POST request to /api/qr/decode/ without image returns 400 Bad Request"""
        res = self.client.post(reverse("qr_decoder_api"), {})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("No image file provided", data["message"])

    def test_qr_decoder_api_multipart_upload_success(self):
        """Task 47 & 48: Uploading QR code image via multipart/form-data decodes payload using pyzbar"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        uploaded = SimpleUploadedFile("bill_qr.png", self.valid_qr_bytes, content_type="image/png")

        res = self.client.post(reverse("qr_decoder_api"), {"file": uploaded})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("raw_text", data["data"])
        self.assertIn("INV-QR-TEST-001", data["data"]["raw_text"])
        self.assertEqual(data["data"]["code_type"], "QRCODE")

    def test_qr_decoder_api_base64_json_success(self):
        """Task 47 & 48: Uploading base64 image via JSON body decodes payload"""
        b64_str = base64.b64encode(self.valid_qr_bytes).decode("utf-8")
        payload = json.dumps({"image_base64": f"data:image/png;base64,{b64_str}"})

        res = self.client.post(
            reverse("qr_decoder_api"),
            data=payload,
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("INV-QR-TEST-001", data["data"]["raw_text"])

    def test_qr_decoder_api_invalid_image_format(self):
        """Task 47: Uploading non-image file returns 422 Unprocessable Entity"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad_file = SimpleUploadedFile("fake.txt", b"This is plain text, not an image.", content_type="text/plain")

        res = self.client.post(reverse("qr_decoder_api"), {"file": bad_file})
        self.assertEqual(res.status_code, 422)
        data = res.json()
        self.assertEqual(data["status"], "error")

    def test_read_qr_code_data_using_pyzbar_direct(self):
        """Task 48: Use pyzbar library to read QR code data from image bytes/file"""
        import io
        from billing.utils import read_qr_code_data

        buf = io.BytesIO(self.valid_qr_bytes)
        decode_res = read_qr_code_data(buf)

        self.assertTrue(decode_res["success"])
        self.assertIn("INV-QR-TEST-001", decode_res["raw_data"])
        self.assertEqual(decode_res["code_type"], "QRCODE")
        self.assertTrue(decode_res["parsed"]["is_invoice"])
        self.assertEqual(decode_res["parsed"]["invoice_data"]["invoice"], "INV-QR-TEST-001")

    def test_read_qr_code_data_upi_payload_using_pyzbar(self):
        """Task 48: Use pyzbar to read and decode a UPI payment QR code"""
        import io
        import qrcode
        from billing.utils import read_qr_code_data

        upi_string = "upi://pay?pa=store@icici&pn=SuperStore&am=2450.00&tn=INV-8899"
        img = qrcode.make(upi_string)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        decode_res = read_qr_code_data(buf)
        self.assertTrue(decode_res["success"])
        self.assertTrue(decode_res["parsed"]["is_upi"])
        self.assertEqual(decode_res["parsed"]["upi_data"]["payee_address"], "store@icici")
        self.assertEqual(decode_res["parsed"]["upi_data"]["amount"], "2450.00")

    def test_read_qr_code_data_blank_image_returns_error(self):
        """Task 48: Image without QR code returns graceful detection error"""
        from PIL import Image
        import io
        from billing.utils import read_qr_code_data

        blank = Image.new("RGB", (200, 200), color="white")
        buf = io.BytesIO()
        blank.save(buf, format="PNG")
        buf.seek(0)

        decode_res = read_qr_code_data(buf)
        self.assertFalse(decode_res["success"])
        self.assertIn("No QR code detected", decode_res["error"])

    def test_parse_and_render_invoice_information_on_page(self):
        """Task 49: Parse decoded data and render formatted invoice information card on the page"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        uploaded = SimpleUploadedFile("bill_qr.png", self.valid_qr_bytes, content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": uploaded})

        self.assertEqual(res.status_code, 200)
        # Check rendered parsed invoice section
        self.assertContains(res, "parsedInvoiceInfo")
        self.assertContains(res, "Parsed Invoice Information")
        self.assertContains(res, "INV-QR-TEST-001")
        self.assertContains(res, "Alpha Corp")
        self.assertContains(res, "1180.00")
        self.assertContains(res, "Linked with Database Record")
        self.assertContains(res, "View Full Invoice")

    def test_parse_and_render_external_invoice_qr(self):
        """Task 49: Parse external invoice QR payload and render clean data grid"""
        import io
        import qrcode
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        external_qr_text = (
            "Invoice: INV-EXT-9988\n"
            "Customer: Beta Ltd\n"
            "Total: 4500.00\n"
            "Date: 12 Oct 2026\n"
            "Status: Pending"
        )
        img = qrcode.make(external_qr_text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        uploaded = SimpleUploadedFile("external_qr.png", buf.getvalue(), content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": uploaded})

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "parsedInvoiceInfo")
        self.assertContains(res, "INV-EXT-9988")
        self.assertContains(res, "Beta Ltd")
        self.assertContains(res, "4500.00")

    def test_qr_decoder_empty_zero_byte_file(self):
        """Task 50: Uploading a 0-byte file displays error on view and returns 400 on API"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        empty_file = SimpleUploadedFile("empty.png", b"", content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": empty_file})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "The uploaded file is empty (0 bytes)")
        self.assertContains(res, "invalidQrErrorBox")

        # Also test API endpoint
        empty_file_api = SimpleUploadedFile("empty.png", b"", content_type="image/png")
        res_api = self.client.post(reverse("qr_decoder_api"), {"file": empty_file_api})
        self.assertEqual(res_api.status_code, 400)
        data = res_api.json()
        self.assertEqual(data["error_code"], "EMPTY_FILE")

    def test_qr_decoder_empty_qr_payload(self):
        """Task 50: Uploading a QR code that encodes empty or whitespace-only text returns proper error"""
        import io
        import qrcode
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        img = qrcode.make("   ")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        uploaded = SimpleUploadedFile("blank_payload.png", buf.getvalue(), content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": uploaded})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "The detected QR code contains empty or blank data payload")
        self.assertContains(res, "invalidQrErrorBox")

    def test_qr_decoder_invalid_scenery_image(self):
        """Task 50: Uploading an image with no QR code renders invalidQrErrorBox with tips"""
        from PIL import Image
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        scenery = Image.new("RGB", (300, 300), color="lightblue")
        buf = io.BytesIO()
        scenery.save(buf, format="PNG")
        buf.seek(0)

        uploaded = SimpleUploadedFile("scenery.png", buf.getvalue(), content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": uploaded})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "QR Code Detection Failed")
        self.assertContains(res, "invalidQrErrorBox")
        self.assertContains(res, "Helpful Tips to Scan Successfully")

    def test_toast_and_alert_on_success_outcome(self):
        """Task 51: Successful QR decode renders success alert banner and triggers success toast notification"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        uploaded = SimpleUploadedFile("bill_qr.png", self.valid_qr_bytes, content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": uploaded})

        self.assertEqual(res.status_code, 200)
        # Verify floating toast container and success alert banner
        self.assertContains(res, 'id="toastContainer"')
        self.assertContains(res, 'id="successAlertBanner"')
        self.assertContains(res, "qr-alert-success")
        self.assertContains(res, "Success Outcome")
        self.assertContains(res, "QR code decoded successfully")
        # Verify JavaScript showToast call
        self.assertContains(res, 'showToast(')
        self.assertContains(res, '"success"')

    def test_toast_and_alert_on_error_outcome(self):
        """Task 51: Failed QR decode renders error alert banner and triggers error toast notification"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.login(username="dist_qr_tester", password="Password@123")

        bad_file = SimpleUploadedFile("corrupted.png", b"not-a-valid-image", content_type="image/png")
        res = self.client.post(reverse("qr_decoder"), {"qr_image": bad_file})

        self.assertEqual(res.status_code, 200)
        # Verify floating toast container and error alert banner
        self.assertContains(res, 'id="toastContainer"')
        self.assertContains(res, 'id="errorAlertBanner"')
        self.assertContains(res, "qr-alert-error")
        self.assertContains(res, "Attention Required")
        # Verify JavaScript showToast call
        self.assertContains(res, 'showToast(')
        self.assertContains(res, '"error"')


class Task57InvoiceDatabaseExistenceTests(TestCase):
    """
    Task 57: Ensure that invoice data exists in the database
    (invoice ID, customer name, total amount, and date).
    """

    def setUp(self):
        self.distributor = User.objects.create_user(
            username="task57_dist",
            email="task57@billing.com",
            password="Password@123",
            first_name="Task57 Distributor"
        )
        self.customer = Customer.objects.create(
            distributor=self.distributor,
            name="Shree Ganesh Traders",
            email="ganesh@traders.in",
            phone="9876543210",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380015"
        )
        self.product = Product.objects.create(
            distributor=self.distributor,
            name="Industrial UPS 2KVA",
            category="Electronics",
            price=Decimal("12500.00"),
            stock=25,
            gst_rate=Decimal("18.00")
        )
        self.invoice = Invoice.objects.create(
            invoice_number="INV-20261026-0057",
            distributor=self.distributor,
            customer=self.customer,
            subtotal=Decimal("25000.00"),
            gst_amount=Decimal("4500.00"),
            total_amount=Decimal("29500.00"),
            status="Paid"
        )
        InvoiceItem.objects.create(
            invoice=self.invoice,
            product=self.product,
            quantity=2,
            unit_price=Decimal("12500.00"),
            gst_rate=Decimal("18.00"),
            subtotal=Decimal("25000.00"),
            total=Decimal("29500.00")
        )

    def test_invoice_data_exists_in_database_with_required_fields(self):
        """Task 57: Verify saved invoice record in DB has ID, customer name, total amount, and date"""
        db_invoice = Invoice.objects.select_related("customer").get(pk=self.invoice.pk)
        self.assertIsNotNone(db_invoice.id)
        self.assertEqual(db_invoice.invoice_number, "INV-20261026-0057")
        self.assertEqual(db_invoice.customer.name, "Shree Ganesh Traders")
        self.assertEqual(db_invoice.total_amount, Decimal("29500.00"))
        self.assertIsNotNone(db_invoice.invoice_date)

        summary = db_invoice.get_invoice_summary_data()
        self.assertEqual(summary["invoice_id"], db_invoice.id)
        self.assertEqual(summary["invoice_number"], "INV-20261026-0057")
        self.assertEqual(summary["customer_name"], "Shree Ganesh Traders")
        self.assertEqual(summary["total_amount"], Decimal("29500.00"))
        self.assertTrue(len(summary["date"]) > 0)

    def test_task_58_fetch_saved_invoice_data_and_generate_qr_encoding_values(self):
        """
        Task 58: Fetch data from the saved invoice model and generate a QR code
        encoding invoice ID, customer name, total amount, and date.
        """
        import io
        from PIL import Image
        from billing.views import get_invoice_qr_payload, generate_invoice_qr

        # 1. Verify payload fetched from saved invoice model
        payload = get_invoice_qr_payload(self.invoice)
        self.assertIn(f"Invoice ID: {self.invoice.id}", payload)
        self.assertIn("Invoice: INV-20261026-0057", payload)
        self.assertIn("Customer: Shree Ganesh Traders", payload)
        self.assertIn("Total: ₹29500.00", payload)
        self.assertIn(self.invoice.invoice_date.strftime("%d %b %Y"), payload)

        # 2. Generate QR code and verify valid PNG image output
        qr_b64 = generate_invoice_qr(self.invoice)
        self.assertIsInstance(qr_b64, str)
        self.assertTrue(len(qr_b64) > 100)

        qr_bytes = base64.b64decode(qr_b64)
        self.assertTrue(qr_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        img = Image.open(io.BytesIO(qr_bytes))
        self.assertEqual(img.format, "PNG")
        self.assertTrue(img.width > 100 and img.height > 100)

    def test_task_59_display_qr_code_dynamically_in_invoice_preview_template(self):
        """
        Task 59: Display the QR code dynamically in the invoice preview template.
        """
        self.client.login(username="task57_dist", password="Password@123")
        res = self.client.get(reverse("invoice_detail", kwargs={"pk": self.invoice.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "billing/invoice_detail.html")

        # Verify dynamic QR code context & HTML image element in template
        self.assertIn("qr_code", res.context)
        self.assertIn("qr_payload", res.context)
        qr_b64 = res.context["qr_code"]
        self.assertTrue(len(qr_b64) > 100)

        self.assertContains(res, 'id="invoicePreviewQrSection"')
        self.assertContains(res, 'id="dynamicInvoiceQrImage"')
        self.assertContains(res, f'src="data:image/png;base64,{qr_b64}"')
        self.assertContains(res, f"Invoice ID: #{self.invoice.id}")

    def test_task_60_qr_generation_during_invoice_save(self):
        """
        Task 60: Use qrcode library to handle QR generation automatically during invoice save.
        """
        new_inv = Invoice.objects.create(
            invoice_number="INV-20261026-0060",
            distributor=self.distributor,
            customer=self.customer,
            subtotal=Decimal("5000.00"),
            gst_amount=Decimal("900.00"),
            total_amount=Decimal("5900.00"),
            status="Paid"
        )
        new_inv.refresh_from_db()
        self.assertIsNotNone(new_inv.qr_code_data)
        self.assertTrue(len(new_inv.qr_code_data) > 100)

        qr_bytes = base64.b64decode(new_inv.qr_code_data)
        self.assertTrue(qr_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_task_61_preview_invoice_page_with_details_and_qr(self):
        """
        Task 61: Provide a 'Preview Invoice' page for each invoice that includes details and QR.
        """
        self.client.login(username="task57_dist", password="Password@123")

        # 1. Invoice list contains link to Preview Invoice page
        list_res = self.client.get(reverse("invoice_list"))
        self.assertEqual(list_res.status_code, 200)
        preview_url = reverse("invoice_preview", kwargs={"pk": self.invoice.pk})
        self.assertContains(list_res, preview_url)
        self.assertContains(list_res, "Preview Invoice")

        # 2. Preview Invoice page renders details and QR
        res = self.client.get(preview_url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Preview Invoice")
        self.assertContains(res, self.invoice.invoice_number)
        self.assertContains(res, self.customer.name)
        self.assertContains(res, "29500.00")
        self.assertContains(res, 'id="dynamicInvoiceQrImage"')

    def test_task_62_download_pdf_button_exports_invoice_with_qr(self):
        """
        Task 62: Add a 'Download PDF' button that exports the invoice (with QR) using xhtml2pdf.
        """
        self.client.login(username="task57_dist", password="Password@123")

        # 1. Verify 'Download PDF' button is present on the Preview Invoice page
        preview_res = self.client.get(reverse("invoice_preview", kwargs={"pk": self.invoice.pk}))
        self.assertEqual(preview_res.status_code, 200)
        pdf_url = reverse("invoice_pdf", kwargs={"pk": self.invoice.pk})
        self.assertContains(preview_res, 'id="btnDownloadInvoicePdf"')
        self.assertContains(preview_res, "Download PDF")
        self.assertContains(preview_res, f'href="{pdf_url}"')

        # 2. Follow the Download PDF link and verify xhtml2pdf exports valid PDF stream
        pdf_res = self.client.get(pdf_url)
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(pdf_res["Content-Type"], "application/pdf")
        self.assertIn(f'filename="{self.invoice.invoice_number}.pdf"', pdf_res["Content-Disposition"])
        self.assertTrue(pdf_res.content.startswith(b"%PDF"))

    def test_task_63_fetch_complete_invoice_details_from_database(self):
        """
        Task 63: Fetch complete invoice details (ID, customer name, total, date) from the database.
        """
        from billing.views import fetch_complete_invoice_details

        details = fetch_complete_invoice_details(self.invoice.pk, distributor=self.distributor)
        self.assertEqual(details["invoice_id"], self.invoice.id)
        self.assertEqual(details["invoice_number"], "INV-20261026-0057")
        self.assertEqual(details["customer_name"], "Shree Ganesh Traders")
        self.assertEqual(details["total_amount"], Decimal("29500.00"))
        self.assertEqual(details["invoice_date"], self.invoice.invoice_date.strftime("%d %b %Y"))
        self.assertEqual(len(details["items"]), 1)
        self.assertTrue(len(details["qr_code"]) > 100)

    def test_task_64_styled_invoice_template_html_css_for_pdf_export(self):
        """
        Task 64: Design styled invoice template in HTML/CSS for PDF export.
        """
        from django.template.loader import render_to_string
        from billing.views import fetch_complete_invoice_details

        context = fetch_complete_invoice_details(self.invoice.pk, distributor=self.distributor)
        rendered_html = render_to_string("billing/invoice_pdf.html", context)

        self.assertIn("TAX INVOICE", rendered_html)
        self.assertIn(f"#{self.invoice.id}", rendered_html)
        self.assertIn("INV-20261026-0057", rendered_html)
        self.assertIn("Shree Ganesh Traders", rendered_html)
        self.assertIn("Industrial UPS 2KVA", rendered_html)
        self.assertIn("Rs. 29500.00", rendered_html)
        self.assertIn("@page", rendered_html)
        self.assertIn("Authorized Signatory", rendered_html)

    def test_task_65_integrate_xhtml2pdf_reportlab_to_generate_pdf_from_template(self):
        """
        Task 65: Integrate xhtml2pdf/ReportLab to generate PDFs from invoice templates.
        """
        import reportlab
        from billing.utils import generate_invoice_pdf_bytes, render_to_pdf
        from billing.views import fetch_complete_invoice_details

        self.assertIsNotNone(reportlab.__version__)
        context = fetch_complete_invoice_details(self.invoice.pk, distributor=self.distributor)

        pdf_bytes = generate_invoice_pdf_bytes("billing/invoice_pdf.html", context)
        self.assertIsNotNone(pdf_bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"ReportLab Generated PDF document", pdf_bytes)

        response = render_to_pdf("billing/invoice_pdf.html", context)
        self.assertIsNotNone(response)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_task_66_embed_dynamically_generated_qr_code_into_pdf_layout(self):
        """
        Task 66: Embed dynamically generated QR code into the PDF layout.
        """
        from django.template.loader import render_to_string
        from billing.views import fetch_complete_invoice_details
        from billing.utils import generate_invoice_pdf_bytes

        context = fetch_complete_invoice_details(self.invoice.pk, distributor=self.distributor)
        qr_b64 = context["qr_code"]

        # 1. Verify QR code image is embedded in rendered PDF HTML layout even when upi_qr_code is present
        rendered_pdf_html = render_to_string("billing/invoice_pdf.html", context)
        self.assertIn('id="pdfEmbeddedInvoiceQr"', rendered_pdf_html)
        self.assertIn(f'src="data:image/png;base64,{qr_b64}"', rendered_pdf_html)
        self.assertIn("Invoice QR Verification", rendered_pdf_html)

        # 2. Verify compiled PDF binary stream succeeds with embedded QR image object
        pdf_bytes = generate_invoice_pdf_bytes("billing/invoice_pdf.html", context)
        self.assertIsNotNone(pdf_bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"/Subtype /Image", pdf_bytes)


















class Task81To85RoleBasedAndPaginationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="admin_role_tester",
            email="admin_role@example.com",
            password="AdminPassword@123"
        )
        self.distributor1 = User.objects.create_user(
            username="dist_role_1",
            email="dist1_role@example.com",
            password="Password@123"
        )
        self.distributor2 = User.objects.create_user(
            username="dist_role_2",
            email="dist2_role@example.com",
            password="Password@123"
        )
        for i in range(15):
            Customer.objects.create(
                distributor=self.distributor1,
                name=f"Customer PageTest {i+1}",
                phone=f"98765432{i:02d}",
                city="Surat",
                state="Gujarat",
                pincode="395001"
            )

    def test_task_85_customer_list_pagination(self):
        """Task 85: Verify customer list paginates records at 10 items per page"""
        self.client.login(username="dist_role_1", password="Password@123")
        res = self.client.get(reverse("customer_list"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context["customers"]), 10)
        self.assertTrue(res.context["page_obj"].has_next())
        self.assertEqual(res.context["page_obj"].paginator.num_pages, 2)
        self.assertContains(res, "Showing page <strong>1</strong> of <strong>2</strong>")

        res2 = self.client.get(reverse("customer_list") + "?page=2")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(len(res2.context["customers"]), 5)
        self.assertFalse(res2.context["page_obj"].has_next())
        self.assertTrue(res2.context["page_obj"].has_previous())

    def test_task_81_admin_add_customer_for_any_distributor(self):
        """Task 81: Admin can add new customer and assign to selected distributor"""
        self.client.login(username="admin_role_tester", password="AdminPassword@123")
        res = self.client.get(reverse("customer_add"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Assign to Distributor (Admin Role)")

        post_res = self.client.post(reverse("customer_add"), {
            "name": "Admin Assigned Customer",
            "phone": "9988776655",
            "city": "Vadodara",
            "state": "Gujarat",
            "pincode": "390001",
            "distributor_id": str(self.distributor2.id),
        })
        self.assertEqual(post_res.status_code, 302)
        new_cust = Customer.objects.filter(name="Admin Assigned Customer").first()
        self.assertIsNotNone(new_cust)
        self.assertEqual(new_cust.distributor, self.distributor2)

    def test_task_82_admin_add_product_for_any_distributor(self):
        """Task 82: Admin can add new product and assign to selected distributor"""
        self.client.login(username="admin_role_tester", password="AdminPassword@123")
        res = self.client.get(reverse("product_add"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Assign to Distributor (Admin Role)")

        post_res = self.client.post(reverse("product_add"), {
            "name": "Admin Assigned Product",
            "category": "Electronics",
            "price": "1500.00",
            "stock": "50",
            "gst_rate": "18.00",
            "description": "Added by admin for distributor2",
            "distributor_id": str(self.distributor2.id),
        })
        self.assertEqual(post_res.status_code, 302)
        new_prod = Product.objects.filter(name="Admin Assigned Product").first()
        self.assertIsNotNone(new_prod)
        self.assertEqual(new_prod.distributor, self.distributor2)

    def test_task_83_and_84_admin_can_view_edit_delete_all(self):
        """Task 83 and 84: Admin views all customers and products, and can edit/delete them"""
        cust = Customer.objects.filter(distributor=self.distributor1).first()
        prod = Product.objects.create(
            distributor=self.distributor1,
            name="Distributor 1 Exclusive Product",
            category="Hardware",
            price=Decimal("200.00"),
            stock=10,
            gst_rate=Decimal("12.00")
        )

        self.client.login(username="admin_role_tester", password="AdminPassword@123")

        res_c = self.client.get(reverse("customer_list"))
        self.assertContains(res_c, cust.name)

        res_p = self.client.get(reverse("product_list"))
        self.assertContains(res_p, prod.name)

        edit_c = self.client.post(reverse("customer_edit", kwargs={"pk": cust.pk}), {
            "name": "Customer Edited By Admin",
            "phone": cust.phone,
            "city": cust.city,
            "state": cust.state,
            "pincode": cust.pincode,
        })
        self.assertEqual(edit_c.status_code, 302)
        cust.refresh_from_db()
        self.assertEqual(cust.name, "Customer Edited By Admin")

        del_p = self.client.post(reverse("product_delete", kwargs={"pk": prod.pk}))
        self.assertEqual(del_p.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=prod.pk).exists())

    def test_invoice_toggle_status_and_isolation(self):
        """Verify 1-click invoice payment status toggle (Pending <-> Paid) and isolation"""
        cust = Customer.objects.filter(distributor=self.distributor1).first()
        inv = Invoice.objects.create(
            invoice_number="INV-STATUS-TEST-001",
            customer=cust,
            distributor=self.distributor1,
            subtotal=Decimal("100.00"),
            gst_amount=Decimal("18.00"),
            total_amount=Decimal("118.00"),
            status="Pending",
        )

        # Distributor 2 cannot toggle Distributor 1's invoice
        self.client.login(username="dist_role_2", password="Password@123")
        res_other = self.client.post(reverse("invoice_toggle_status", kwargs={"pk": inv.pk}))
        self.assertEqual(res_other.status_code, 404)

        # Distributor 1 can toggle Pending -> Paid -> Pending
        self.client.login(username="dist_role_1", password="Password@123")
        res_paid = self.client.post(reverse("invoice_toggle_status", kwargs={"pk": inv.pk}))
        self.assertEqual(res_paid.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "Paid")

        res_pending = self.client.post(reverse("invoice_toggle_status", kwargs={"pk": inv.pk}))
        self.assertEqual(res_pending.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "Pending")

        # Admin can also toggle any invoice
        self.client.login(username="admin_role_tester", password="AdminPassword@123")
        res_admin = self.client.post(reverse("invoice_toggle_status", kwargs={"pk": inv.pk}))
        self.assertEqual(res_admin.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "Paid")

    def test_customer_list_single_pagination_and_inactive_badge(self):
        """Verify customer_list renders pagination once and shows Inactive badge for inactive customers"""
        Customer.objects.create(
            distributor=self.distributor1,
            name="Inactive Client Test",
            phone="9998887776",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001",
            is_active=False,
        )
        self.client.login(username="dist_role_1", password="Password@123")
        res = self.client.get(reverse("customer_list"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        self.assertEqual(html.count('class="pagination-wrapper"'), 1)
        self.assertContains(res, "Inactive")


class SecurityFixesAndNewBillingFeaturesTests(TestCase):
    """Comprehensive tests for security hardening, bug fixes, stock deduction, cancel, GST split, and email sharing."""

    def setUp(self):
        from accounts.models import DistributorProfile
        self.client = Client()
        self.admin = User.objects.create_user(
            username="feat_admin",
            email="feat_admin@billing.local",
            password="AdminPassword@2026",
            is_staff=True,
            is_superuser=True,
        )
        self.dist1 = User.objects.create_user(
            username="feat_dist1",
            email="feat_dist1@billing.local",
            password="DistPassword@2026",
            first_name="Gujarat Traders",
        )
        DistributorProfile.objects.create(
            user=self.dist1,
            phone="9876543210",
            business_name="Gujarat Traders Pvt Ltd",
            gstin="24ABCDE1234F1Z5",
            state="Gujarat",
            upi_id="gujarattraders@okicici",
        )
        self.dist2 = User.objects.create_user(
            username="feat_dist2",
            email="feat_dist2@billing.local",
            password="DistPassword@2026",
            first_name="Mumbai Distributors",
        )
        DistributorProfile.objects.create(user=self.dist2, phone="9876500000", state="Maharashtra")

        self.cust_gj = Customer.objects.create(
            distributor=self.dist1,
            name="Ahmedabad Buyer",
            email="buyer.gj@example.com",
            phone="9825012345",
            gstin="24XYZAB1234C1Z2",
            city="Ahmedabad",
            state="Gujarat",
            pincode="380001",
        )
        self.cust_mh = Customer.objects.create(
            distributor=self.dist1,
            name="Mumbai Buyer",
            email="buyer.mh@example.com",
            phone="9825054321",
            city="Mumbai",
            state="Maharashtra",
            pincode="400001",
        )
        self.cust_d2 = Customer.objects.create(
            distributor=self.dist2,
            name="Pune Buyer",
            phone="9811122233",
            city="Pune",
            state="Maharashtra",
            pincode="411001",
        )
        self.prod1 = Product.objects.create(
            distributor=self.dist1,
            name="Industrial Router",
            sku="RTR-100",
            hsn_code="8517",
            category="Networking",
            price=Decimal("1000.00"),
            stock=10,
            gst_rate=Decimal("18.00"),
        )
        self.prod2 = Product.objects.create(
            distributor=self.dist2,
            name="Fiber Switch",
            category="Networking",
            price=Decimal("2000.00"),
            stock=5,
            gst_rate=Decimal("18.00"),
        )

    def test_product_api_blocks_unauthenticated_distributor_id_bypass(self):
        res_get = self.client.get(reverse("api_products") + f"?distributor_id={self.dist1.id}")
        self.assertEqual(res_get.status_code, 401)
        res_post = self.client.post(
            reverse("api_products") + f"?distributor_id={self.dist1.id}",
            data=json.dumps({
                "name": "Injected Item",
                "category": "Hack",
                "price": "100.00",
                "stock": 5,
                "gst_rate": "18.00",
            }),
            content_type="application/json",
        )
        self.assertEqual(res_post.status_code, 401)

    def test_qr_decoder_api_does_not_leak_invoice_to_anonymous(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        inv = Invoice.objects.create(
            invoice_number="INV-LEAK-TEST-01",
            customer=self.cust_gj,
            distributor=self.dist1,
            subtotal=Decimal("1000.00"),
            gst_amount=Decimal("180.00"),
            total_amount=Decimal("1180.00"),
            status="Paid",
        )
        qr_bytes = base64.b64decode(inv.qr_code_data)
        uploaded_anon = SimpleUploadedFile("inv.png", qr_bytes, content_type="image/png")
        res_anon = self.client.post(reverse("qr_decoder_api"), {"file": uploaded_anon})
        self.assertEqual(res_anon.status_code, 200)
        self.assertIsNone(res_anon.json()["data"]["matched_invoice"])

        # Authenticated owner receives matched_invoice
        self.client.login(username="feat_dist1", password="DistPassword@2026")
        uploaded_auth = SimpleUploadedFile("inv2.png", qr_bytes, content_type="image/png")
        res_auth = self.client.post(reverse("qr_decoder_api"), {"file": uploaded_auth})
        self.assertEqual(res_auth.status_code, 200)
        self.assertEqual(res_auth.json()["data"]["matched_invoice"]["invoice_number"], "INV-LEAK-TEST-01")

    def test_invoice_create_deducts_stock_persists_discount_and_splits_gst(self):
        self.client.login(username="feat_dist1", password="DistPassword@2026")

        # 1. Rejects insufficient stock
        res_over = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_gj.id,
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["25"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        self.assertEqual(res_over.status_code, 200)
        self.prod1.refresh_from_db()
        self.assertEqual(self.prod1.stock, 10)

        # 2. Rejects >100% discount
        res_bad_disc = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_gj.id,
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["150"],
        })
        self.assertEqual(res_bad_disc.status_code, 200)
        self.prod1.refresh_from_db()
        self.assertEqual(self.prod1.stock, 10)

        # 3. Intra-state (Gujarat -> Gujarat): CGST + SGST split & stock deduction & discount saved
        res_intra = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_gj.id,
            "status": "Paid",
            "payment_mode": "UPI",
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["2"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["10"],
        })
        self.assertEqual(res_intra.status_code, 302)
        self.prod1.refresh_from_db()
        self.assertEqual(self.prod1.stock, 8)
        inv_intra = Invoice.objects.filter(customer=self.cust_gj).latest("id")
        self.assertEqual(inv_intra.discount_total, Decimal("200.00"))
        self.assertEqual(inv_intra.subtotal, Decimal("1800.00"))
        self.assertEqual(inv_intra.gst_amount, Decimal("324.00"))
        self.assertFalse(inv_intra.is_interstate)
        self.assertEqual(inv_intra.cgst_amount, Decimal("162.00"))
        self.assertEqual(inv_intra.sgst_amount, Decimal("162.00"))
        self.assertEqual(inv_intra.igst_amount, Decimal("0.00"))
        self.assertEqual(inv_intra.payment_mode, "UPI")
        self.assertIsNotNone(inv_intra.paid_at)

        # 4. Inter-state (Gujarat -> Maharashtra): IGST split
        res_inter = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_mh.id,
            "status": "Pending",
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        self.assertEqual(res_inter.status_code, 302)
        inv_inter = Invoice.objects.filter(customer=self.cust_mh).latest("id")
        self.assertTrue(inv_inter.is_interstate)
        self.assertEqual(inv_inter.igst_amount, Decimal("180.00"))
        self.assertEqual(inv_inter.cgst_amount, Decimal("0.00"))
        self.assertEqual(inv_inter.sgst_amount, Decimal("0.00"))
        self.prod1.refresh_from_db()
        self.assertEqual(self.prod1.stock, 7)

        # 5. Cancel Invoice restores stock & blocks status toggle
        res_cancel = self.client.post(reverse("invoice_cancel", kwargs={"pk": inv_intra.pk}))
        self.assertRedirects(res_cancel, reverse("invoice_detail", kwargs={"pk": inv_intra.pk}))
        inv_intra.refresh_from_db()
        self.prod1.refresh_from_db()
        self.assertEqual(inv_intra.status, "Cancelled")
        self.assertEqual(self.prod1.stock, 9)

        # Toggling cancelled invoice must keep it Cancelled
        self.client.post(reverse("invoice_toggle_status", kwargs={"pk": inv_intra.pk}))
        inv_intra.refresh_from_db()
        self.assertEqual(inv_intra.status, "Cancelled")

    def test_multi_distributor_invoice_numbers_never_collide(self):
        self.client.login(username="feat_dist1", password="DistPassword@2026")
        r1 = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_gj.id,
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        self.assertEqual(r1.status_code, 302)

        self.client.logout()
        self.client.login(username="feat_dist2", password="DistPassword@2026")
        r2 = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_d2.id,
            "product[]": [str(self.prod2.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["2000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        self.assertEqual(r2.status_code, 302)
        nums = list(Invoice.objects.values_list("invoice_number", flat=True))
        self.assertEqual(len(nums), len(set(nums)))

    def test_protected_error_handled_on_customer_and_product_delete(self):
        self.client.login(username="feat_dist1", password="DistPassword@2026")
        self.client.post(reverse("invoice_create"), {
            "customer": self.cust_gj.id,
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        # Customer delete should redirect with error, not 500
        res_cust = self.client.post(reverse("customer_delete", kwargs={"pk": self.cust_gj.pk}))
        self.assertRedirects(res_cust, reverse("customer_list"))
        self.assertTrue(Customer.objects.filter(pk=self.cust_gj.pk).exists())

        # Product delete should redirect with error, not 500
        res_prod = self.client.post(reverse("product_delete", kwargs={"pk": self.prod1.pk}))
        self.assertRedirects(res_prod, reverse("product_list"))
        self.assertTrue(Product.objects.filter(pk=self.prod1.pk).exists())

        # Product API DELETE should return 409 Conflict, not 500
        res_api = self.client.delete(reverse("api_product_detail", kwargs={"pk": self.prod1.pk}))
        self.assertEqual(res_api.status_code, 409)

    def test_open_redirect_blocked_and_invoice_email_and_upi_id_used(self):
        from django.core import mail
        self.client.login(username="feat_dist1", password="DistPassword@2026")
        self.client.post(reverse("invoice_create"), {
            "customer": self.cust_gj.id,
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        inv = Invoice.objects.filter(customer=self.cust_gj).latest("id")

        # Open redirect blocked -> redirects safely to invoice_detail
        res_redir = self.client.post(
            reverse("invoice_toggle_status", kwargs={"pk": inv.pk}),
            {"next": "https://evil.example.com/phish"},
        )
        self.assertRedirects(res_redir, reverse("invoice_detail", kwargs={"pk": inv.pk}))

        # Detail page renders configured UPI ID and WhatsApp link
        res_detail = self.client.get(reverse("invoice_detail", kwargs={"pk": inv.pk}))
        self.assertContains(res_detail, "gujarattraders@okicici")
        self.assertContains(res_detail, "https://wa.me/919825012345")

        # Email Invoice PDF attaches PDF and sends
        mail.outbox.clear()
        res_email = self.client.post(reverse("invoice_send_email", kwargs={"pk": inv.pk}))
        self.assertRedirects(res_email, reverse("invoice_detail", kwargs={"pk": inv.pk}))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["buyer.gj@example.com"])
        self.assertEqual(len(mail.outbox[0].attachments), 1)

    def test_product_list_delete_url_fixed_and_admin_can_view_reports(self):
        self.client.login(username="feat_dist1", password="DistPassword@2026")
        res_list = self.client.get(reverse("product_list"))
        self.assertNotContains(res_list, "/billing/products/")
        self.assertContains(res_list, "/products/${encodeURIComponent(productId)}/delete/")

        self.client.post(reverse("invoice_create"), {
            "customer": self.cust_gj.id,
            "product[]": [str(self.prod1.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        self.client.logout()
        self.client.login(username="feat_admin", password="AdminPassword@2026")
        res_report = self.client.get(reverse("invoice_report"))
        self.assertEqual(res_report.status_code, 200)
        self.assertContains(res_report, "Ahmedabad Buyer")


class RealBusinessFivePhasesTests(TestCase):
    """Comprehensive tests covering Phases 1–5 real-business upgrades."""

    def setUp(self):
        from accounts.models import DistributorProfile
        self.client = Client()
        self.admin = User.objects.create_user(
            username="rb_admin",
            email="rb_admin@billing.local",
            password="AdminPassword@2026",
            is_staff=True,
            is_superuser=True,
        )
        self.dist1 = User.objects.create_user(
            username="rb_dist1",
            email="rb_dist1@billing.local",
            password="DistPassword@2026",
        )
        DistributorProfile.objects.create(
            user=self.dist1,
            phone="9876501234",
            business_name="Patel Agro & Distributors",
            gstin="24ABCDE1234F1Z5",
            address="SG Highway",
            city="Ahmedabad",
            state="Gujarat",
            upi_id="patelagro@okaxis",
        )
        self.dist2 = User.objects.create_user(
            username="rb_dist2",
            email="rb_dist2@billing.local",
            password="DistPassword@2026",
        )
        self.cust_b2b = Customer.objects.create(
            distributor=self.dist1,
            name="Surat Wholesale Mart",
            email="surat@example.com",
            phone="9825011111",
            gstin="24ZZZZZ9999Z1Z9",
            address="Ring Road",
            city="Surat",
            state="Gujarat",
            pincode="395002",
        )
        self.cust_b2c = Customer.objects.create(
            distributor=self.dist1,
            name="Mumbai Retail Buyer",
            email="mumbai@example.com",
            phone="9820022222",
            gstin="",
            address="Andheri",
            city="Mumbai",
            state="Maharashtra",
            pincode="400053",
        )
        self.prod = Product.objects.create(
            distributor=self.dist1,
            name="Solar Inverter 2kVA",
            sku="SOL-2000",
            hsn_code="8504",
            category="Electrical",
            price=Decimal("1000.00"),
            stock=25,
            gst_rate=Decimal("18.00"),
        )

    def test_phase1_amount_to_words_and_gst_compliant_pdf_and_preview(self):
        from .utils import amount_to_indian_words
        self.assertEqual(
            amount_to_indian_words(Decimal("12450.50")),
            "Rupees Twelve Thousand Four Hundred Fifty and Fifty Paise Only",
        )
        self.assertEqual(
            amount_to_indian_words(Decimal("100000.00")),
            "Rupees One Lakh Only",
        )
        self.assertEqual(
            amount_to_indian_words(Decimal("0.00")),
            "Rupees Zero Only",
        )

        self.client.login(username="rb_dist1", password="DistPassword@2026")
        res = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_b2b.id,
            "product[]": [str(self.prod.id)],
            "quantity[]": ["2"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["10.00"],
            "status": "Pending",
            "notes": "PO #7781",
        })
        self.assertEqual(res.status_code, 302)
        inv = Invoice.objects.filter(distributor=self.dist1).latest("id")

        detail = self.client.get(reverse("invoice_detail", kwargs={"pk": inv.pk}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Patel Agro &amp; Distributors")
        self.assertContains(detail, "8504")
        self.assertContains(detail, "10.0%")
        self.assertContains(detail, "Place of Supply:")
        self.assertContains(detail, "Rupees Two Thousand One Hundred Twenty Four Only")
        self.assertContains(detail, "HSN-Wise GST Tax Summary")
        self.assertContains(detail, "PO #7781")

        pdf_res = self.client.get(reverse("invoice_pdf", kwargs={"pk": inv.pk}))
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(pdf_res["Content-Type"], "application/pdf")
        self.assertTrue(pdf_res.content.startswith(b"%PDF"))

    def test_phase2_partial_payments_due_dates_overdue_and_customer_khata(self):
        from datetime import date, timedelta
        from .models import InvoicePayment

        self.client.login(username="rb_dist1", password="DistPassword@2026")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        res = self.client.post(reverse("invoice_create"), {
            "customer": self.cust_b2b.id,
            "product[]": [str(self.prod.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
            "status": "Partial",
            "payment_mode": "UPI",
            "initial_paid": "500.00",
            "payment_reference": "UTR12345",
            "due_date": yesterday,
        })
        self.assertEqual(res.status_code, 302)
        inv = Invoice.objects.filter(distributor=self.dist1).latest("id")
        self.assertEqual(inv.status, "Partial")
        self.assertEqual(inv.amount_paid, Decimal("500.00"))
        self.assertEqual(inv.balance_due, Decimal("680.00"))
        self.assertTrue(inv.is_overdue)
        self.assertEqual(inv.payments.count(), 1)

        # Overpayment rejected
        res_over = self.client.post(reverse("invoice_add_payment", kwargs={"pk": inv.pk}), {
            "amount": "900.00",
            "payment_mode": "Cash",
        })
        self.assertEqual(res_over.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal("500.00"))

        # Record remaining balance -> invoice becomes Paid
        res_settle = self.client.post(reverse("invoice_add_payment", kwargs={"pk": inv.pk}), {
            "amount": "680.00",
            "payment_mode": "Bank Transfer",
            "reference_number": "NEFT999",
        })
        self.assertEqual(res_settle.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "Paid")
        self.assertEqual(inv.balance_due, Decimal("0.00"))
        self.assertFalse(inv.is_overdue)

        # Delete second payment -> reverts to Partial
        second_pay = InvoicePayment.objects.filter(invoice=inv, reference_number="NEFT999").first()
        self.assertIsNotNone(second_pay)
        self.client.post(reverse("invoice_delete_payment", kwargs={"pk": inv.pk, "payment_id": second_pay.pk}))
        inv.refresh_from_db()
        self.assertEqual(inv.status, "Partial")
        self.assertEqual(inv.balance_due, Decimal("680.00"))

        # Customer Khata page + CSV export
        khata = self.client.get(reverse("customer_ledger", kwargs={"pk": self.cust_b2b.pk}))
        self.assertEqual(khata.status_code, 200)
        self.assertContains(khata, "Surat Wholesale Mart")
        self.assertContains(khata, "680.00")
        self.assertContains(khata, "https://wa.me/919825011111")

        khata_csv = self.client.get(reverse("customer_ledger", kwargs={"pk": self.cust_b2b.pk}) + "?export=csv")
        self.assertEqual(khata_csv.status_code, 200)
        self.assertIn("Running Balance", khata_csv.content.decode("utf-8"))

        # Cross-tenant isolation: dist2 cannot access dist1's customer ledger
        self.client.logout()
        self.client.login(username="rb_dist2", password="DistPassword@2026")
        res_denied = self.client.get(reverse("customer_ledger", kwargs={"pk": self.cust_b2b.pk}))
        self.assertEqual(res_denied.status_code, 404)

    def test_phase3_gstr1_exports_and_stock_ledger(self):
        from .models import StockMovement
        self.client.login(username="rb_dist1", password="DistPassword@2026")

        # Create 1 B2B invoice, 1 B2C invoice, and 1 Cancelled invoice (excluded from GSTR-1)
        self.client.post(reverse("invoice_create"), {
            "customer": self.cust_b2b.id,
            "product[]": [str(self.prod.id)],
            "quantity[]": ["2"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        self.client.post(reverse("invoice_create"), {
            "customer": self.cust_b2c.id,
            "product[]": [str(self.prod.id)],
            "quantity[]": ["3"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        self.client.post(reverse("invoice_create"), {
            "customer": self.cust_b2b.id,
            "product[]": [str(self.prod.id)],
            "quantity[]": ["1"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["0"],
        })
        cancelled_inv = Invoice.objects.filter(distributor=self.dist1).latest("id")
        self.client.post(reverse("invoice_cancel", kwargs={"pk": cancelled_inv.pk}))

        # GSTR-1 B2B includes GSTIN customer but excludes cancelled invoice & B2C
        b2b = self.client.get(reverse("gstr1_export_csv") + "?section=b2b")
        self.assertEqual(b2b.status_code, 200)
        b2b_text = b2b.content.decode("utf-8")
        self.assertIn("24ZZZZZ9999Z1Z9", b2b_text)
        self.assertNotIn(cancelled_inv.invoice_number, b2b_text)
        self.assertNotIn("Mumbai Retail Buyer", b2b_text)

        # GSTR-1 B2C includes Maharashtra interstate IGST
        b2c = self.client.get(reverse("gstr1_export_csv") + "?section=b2c")
        self.assertEqual(b2c.status_code, 200)
        b2c_text = b2c.content.decode("utf-8")
        self.assertIn("Maharashtra", b2c_text)
        self.assertIn("540.00", b2c_text)

        # GSTR-1 HSN aggregates 2 + 3 = 5 non-cancelled units under HSN 8504
        hsn = self.client.get(reverse("gstr1_export_csv") + "?section=hsn")
        self.assertEqual(hsn.status_code, 200)
        hsn_text = hsn.content.decode("utf-8")
        self.assertIn("8504", hsn_text)
        self.assertIn(",5,", hsn_text)

        # Stock-In restock + audit ledger
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, 20)  # 25 - 2 - 3 - 1 + 1 = 20
        res_restock = self.client.post(reverse("product_restock", kwargs={"pk": self.prod.pk}), {
            "movement_type": "RESTOCK",
            "quantity": "15",
            "reference": "PO-SUP-501",
            "notes": "Factory batch",
        })
        self.assertEqual(res_restock.status_code, 302)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, 35)
        self.assertTrue(
            StockMovement.objects.filter(product=self.prod, movement_type="RESTOCK", reference="PO-SUP-501").exists()
        )
        self.assertTrue(
            StockMovement.objects.filter(product=self.prod, movement_type="CANCEL_RESTORE").exists()
        )

        ledger_res = self.client.get(reverse("stock_ledger"))
        self.assertEqual(ledger_res.status_code, 200)
        self.assertContains(ledger_res, "PO-SUP-501")

    def test_phase4_quotation_create_pdf_and_convert_to_invoice(self):
        from .models import Quotation
        self.client.login(username="rb_dist1", password="DistPassword@2026")

        res = self.client.post(reverse("quotation_create"), {
            "customer": self.cust_b2b.id,
            "product[]": [str(self.prod.id)],
            "quantity[]": ["4"],
            "unit_price[]": ["1000.00"],
            "gst_rate[]": ["18.00"],
            "discount[]": ["5.00"],
            "notes": "Bulk order quote",
        })
        self.assertEqual(res.status_code, 302)
        quote = Quotation.objects.filter(distributor=self.dist1).latest("id")
        self.assertEqual(quote.total_amount, Decimal("4484.00"))
        # Quotation creation MUST NOT deduct stock
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, 25)

        pdf_res = self.client.get(reverse("quotation_pdf", kwargs={"pk": quote.pk}))
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(pdf_res["Content-Type"], "application/pdf")

        # Convert quotation -> real Tax Invoice deducts stock & links invoice
        conv_res = self.client.post(reverse("quotation_convert_to_invoice", kwargs={"pk": quote.pk}))
        self.assertEqual(conv_res.status_code, 302)
        quote.refresh_from_db()
        self.assertEqual(quote.status, "Converted")
        self.assertIsNotNone(quote.converted_invoice)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, 21)

    def test_phase5_database_url_parser_backup_command_smtp_and_admin_backup_endpoint(self):
        import tempfile
        from pathlib import Path
        from django.core.management import call_command
        from django.core import mail
        from config.settings import _parse_database_url

        pg_cfg = _parse_database_url("postgresql://billuser:SecPass@db.example.com:5433/prod_db?sslmode=require")
        self.assertEqual(pg_cfg["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(pg_cfg["NAME"], "prod_db")
        self.assertEqual(pg_cfg["USER"], "billuser")
        self.assertEqual(pg_cfg["PORT"], "5433")
        self.assertEqual(pg_cfg["OPTIONS"]["sslmode"], "require")

        with tempfile.TemporaryDirectory() as tmpdir:
            call_command("backup_db", format="json", output_dir=tmpdir, keep=5)
            files = list(Path(tmpdir).glob("advance_billing_*.json"))
            self.assertEqual(len(files), 1)
            self.assertGreater(files[0].stat().st_size, 10)

        mail.outbox.clear()
        call_command("test_smtp", "owner@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])

        # Non-staff distributor cannot download full DB backup
        self.client.login(username="rb_dist1", password="DistPassword@2026")
        res_dist = self.client.get(reverse("admin_backup_db"))
        self.assertNotEqual(res_dist.status_code, 200)

        # Admin can download JSON snapshot backup
        self.client.logout()
        self.client.login(username="rb_admin", password="AdminPassword@2026")
        res_adm = self.client.get(reverse("admin_backup_db") + "?format=json")
        self.assertEqual(res_adm.status_code, 200)
        self.assertIn("application/json", res_adm["Content-Type"])


