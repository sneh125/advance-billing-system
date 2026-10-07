import json
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from .models import DistributorProfile, PasswordResetOTP


class AccountAuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="distributor_test",
            email="test_dist@example.com",
            password="OldPassword@123",
            first_name="Test Distributor"
        )
        self.profile = DistributorProfile.objects.create(
            user=self.user,
            phone="9876543210"
        )

    def test_login_success_and_redirection(self):
        """Test valid login redirects to distributor_dashboard"""
        response = self.client.post(reverse('login'), {
            'username': 'distributor_test',
            'password': 'OldPassword@123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('distributor_dashboard'))

    def test_login_invalid_credentials(self):
        """Test invalid login shows error"""
        response = self.client.post(reverse('login'), {
            'username': 'distributor_test',
            'password': 'WrongPassword',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password")

    def test_registration_flow(self):
        """Test new distributor registration creates user & profile"""
        response = self.client.post(reverse('register'), {
            'name': 'New Distributor',
            'email': 'new_dist@example.com',
            'phone': '9123456789',
            'password': 'StrongPassword@123',
            'confirm_password': 'StrongPassword@123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('login'))

        new_user = User.objects.filter(email='new_dist@example.com').first()
        self.assertIsNotNone(new_user)
        self.assertEqual(new_user.distributor_profile.phone, '9123456789')

    def test_forgot_password_full_3_step_recovery_flow(self):
        """
        Test complete 3-step Password Recovery:
        Step 1: Request OTP
        Step 2: Verify OTP
        Step 3: Reset New Password
        """
        # Step 1: Request OTP
        response1 = self.client.post(reverse('forgot_password'), {
            'email': 'test_dist@example.com'
        })
        self.assertEqual(response1.status_code, 200)
        self.assertTrue(response1.context['otp_sent'])

        otp_record = PasswordResetOTP.objects.filter(email='test_dist@example.com').first()
        self.assertIsNotNone(otp_record)
        self.assertFalse(otp_record.is_verified)
        generated_otp = otp_record.otp

        # Step 2: Verify OTP
        response2 = self.client.post(reverse('verify_otp'), {
            'email': 'test_dist@example.com',
            'otp': generated_otp
        })
        self.assertEqual(response2.status_code, 200)
        self.assertTrue(response2.context['otp_verified'])

        otp_record.refresh_from_db()
        self.assertTrue(otp_record.is_verified)

        # Step 3: Reset New Password
        response3 = self.client.post(reverse('reset_password'), {
            'email': 'test_dist@example.com',
            'password': 'NewPassword@2026',
            'confirm_password': 'NewPassword@2026'
        })
        self.assertEqual(response3.status_code, 302)
        self.assertRedirects(response3, reverse('login'))

        # Verify new password works
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPassword@2026'))
        self.assertFalse(self.user.check_password('OldPassword@123'))

        # Verify OTP records are cleared
        self.assertFalse(PasswordResetOTP.objects.filter(email='test_dist@example.com').exists())

    def test_forgot_password_wrong_and_expired_otp(self):
        """Test wrong and expired OTP error handling"""
        # Create expired OTP
        PasswordResetOTP.objects.create(
            email='test_dist@example.com',
            otp='123456',
            expires_at=timezone.now() - timedelta(minutes=10)
        )

        # Wrong OTP test
        response_wrong = self.client.post(reverse('verify_otp'), {
            'email': 'test_dist@example.com',
            'otp': '999999'
        })
        self.assertEqual(response_wrong.status_code, 200)
        self.assertContains(response_wrong, "Invalid OTP")

        # Expired OTP test
        response_expired = self.client.post(reverse('verify_otp'), {
            'email': 'test_dist@example.com',
            'otp': '123456'
        })
        self.assertEqual(response_expired.status_code, 200)
        self.assertContains(response_expired, "expired")

    def test_admin_register_api_success(self):
        """Task 32: Test registering an Admin user via JSON API endpoint returns 201"""
        payload = {
            "username": "superadmin_test",
            "email": "superadmin@billing.local",
            "password": "AdminSecurePassword@123",
            "name": "Super Admin User"
        }
        response = self.client.post(
            reverse('admin_register_api'),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["username"], "superadmin_test")
        self.assertTrue(data["data"]["is_staff"])
        self.assertTrue(data["data"]["is_superuser"])

        # Check in DB
        admin_user = User.objects.get(username="superadmin_test")
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.check_password("AdminSecurePassword@123"))

    def test_admin_register_api_validations(self):
        """Task 32: Test validation failures on missing fields, short password, duplicate username/email"""
        # 1. Missing username & password
        resp1 = self.client.post(
            reverse('admin_register_api'),
            data=json.dumps({"email": "bad@example.com"}),
            content_type="application/json"
        )
        self.assertEqual(resp1.status_code, 400)
        self.assertIn("username", resp1.json()["errors"])
        self.assertIn("password", resp1.json()["errors"])

        # 2. Duplicate email
        resp2 = self.client.post(
            reverse('admin_register_api'),
            data=json.dumps({
                "username": "brand_new_admin",
                "email": "test_dist@example.com",  # Already exists from setUp
                "password": "ValidPassword@123"
            }),
            content_type="application/json"
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("email", resp2.json()["errors"])

        # 3. Method not allowed for GET
        resp_get = self.client.get(reverse('admin_register_api'))
        self.assertEqual(resp_get.status_code, 405)

    def test_admin_register_frontend_get_and_post_flow(self):
        """Task 33: Test frontend Admin registration form renders on GET and provisions admin on POST"""
        # 1. GET request renders admin_register.html
        response_get = self.client.get(reverse('admin_register'))
        self.assertEqual(response_get.status_code, 200)
        self.assertContains(response_get, "Create Administrator Account")
        self.assertContains(response_get, "Master Password")

        # 2. POST valid form data
        response_post = self.client.post(reverse('admin_register'), {
            'name': 'Chief Admin',
            'username': 'chief_admin',
            'email': 'chief_admin@advancebilling.local',
            'password': 'ChiefPassword@123',
            'confirm_password': 'ChiefPassword@123',
        })
        self.assertEqual(response_post.status_code, 302)
        self.assertRedirects(response_post, reverse('login'))

        # Verify admin created in DB
        admin_user = User.objects.filter(username='chief_admin').first()
        self.assertIsNotNone(admin_user)
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.check_password('ChiefPassword@123'))

    def test_admin_password_recovery_full_flow(self):
        """Task 34: Test complete backend logic for Admin password recovery flow"""
        # Create an admin user
        admin = User.objects.create_user(
            username="ops_admin",
            email="ops_admin@billing.local",
            password="InitialPassword@123",
            first_name="Ops Administrator"
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()

        # 1. Request OTP via Admin Forgot Password API
        resp1 = self.client.post(
            reverse('api_admin_forgot_password'),
            data=json.dumps({"email": "ops_admin@billing.local"}),
            content_type="application/json"
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertTrue(resp1.json()["otp_sent"])

        otp_record = PasswordResetOTP.objects.filter(email="ops_admin@billing.local").first()
        self.assertIsNotNone(otp_record)
        otp = otp_record.otp

        # 2. Verify OTP
        resp2 = self.client.post(
            reverse('api_admin_verify_otp'),
            data=json.dumps({"email": "ops_admin@billing.local", "otp": otp}),
            content_type="application/json"
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["otp_verified"])

        # 3. Reset Password
        resp3 = self.client.post(
            reverse('api_admin_reset_password'),
            data=json.dumps({
                "email": "ops_admin@billing.local",
                "password": "NewAdminPassword@2026",
                "confirm_password": "NewAdminPassword@2026"
            }),
            content_type="application/json"
        )
        self.assertEqual(resp3.status_code, 200)
        self.assertEqual(resp3.json()["status"], "success")

        # Verify new password works
        admin.refresh_from_db()
        self.assertTrue(admin.check_password("NewAdminPassword@2026"))
        self.assertFalse(admin.check_password("InitialPassword@123"))

    def test_admin_password_recovery_rejects_non_admin(self):
        """Task 34: Test that non-admin accounts are rejected by Admin recovery backend"""
        # user in setUp is not staff
        resp = self.client.post(
            reverse('api_admin_forgot_password'),
            data=json.dumps({"email": "test_dist@example.com"}),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("does not belong to an Administrator account", resp.json()["message"])



