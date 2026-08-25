from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

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
