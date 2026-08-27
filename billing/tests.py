from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from decimal import Decimal
from .models import Customer, Product, Invoice, InvoiceItem


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





