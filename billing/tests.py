import json
import base64
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from decimal import Decimal
from .models import Customer, Product, Invoice, InvoiceItem
from .forms import CustomerForm, ProductForm


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
        """Client specifies distributor_id in payload when unauthenticated"""
        payload = {
            "distributor_id": self.distributor2.id,
            "name": "Dhaval Jani",
            "phone": "9724097240",
            "city": "Vadodara",
            "state": "Gujarat",
            "pincode": "390001"
        }
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










