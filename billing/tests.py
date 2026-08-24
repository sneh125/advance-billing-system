from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from .models import Customer


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
