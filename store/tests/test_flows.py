"""
اختبارات تدفقات حرجة: إعادة تعيين كلمة المرور، التسجيل + OTP، صلاحيات بوابة الشحن.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store.models import (
    Category,
    Compartment,
    EmailOTP,
    PasswordResetOTP,
    Product,
    ProductVariant,
    Shelf,
    UserProfile,
)

# بدون Turnstile وبريد في الذاكرة حتى لا تعتمد الاختبارات على .env
FLOW_SETTINGS = dict(
    TURNSTILE_SITE_KEY='',
    TURNSTILE_SECRET_KEY='',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PASSWORD_RESET_EMAIL_MAX=50,
    PASSWORD_RESET_IP_MAX=200,
    REGISTER_OTP_EMAIL_MAX=50,
    REGISTER_OTP_IP_MAX=200,
    LOGIN_FAILURE_MAX=20,
    LOGIN_CAPTCHA_AFTER_FAILS=99,
)


@override_settings(**FLOW_SETTINGS)
class StoreForgotPasswordFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_forgot_password_full_flow_changes_password(self):
        user = User.objects.create_user(
            username='alice',
            email='alice@example.com',
            password='Initialpass1234',
        )
        url_forgot = reverse('forgot_password')
        url_otp = reverse('forgot_password_otp')
        url_new = reverse('forgot_password_new_password')

        r = self.client.post(url_forgot, {'email': 'alice@example.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, url_otp)

        otp = PasswordResetOTP.objects.get(user=user, is_used=False)
        r2 = self.client.post(url_otp, {'code': otp.code})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(r2.url, url_new)
        self.assertTrue(self.client.session.get('pw_reset_otp_verified'))

        r3 = self.client.post(
            url_new,
            {'password1': 'Brandnewpass1234', 'password2': 'Brandnewpass1234'},
        )
        self.assertEqual(r3.status_code, 302)
        self.assertEqual(r3.url, reverse('user_login'))

        otp.refresh_from_db()
        self.assertTrue(otp.is_used)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Brandnewpass1234'))

    def test_forgot_password_unknown_email_redirects_back(self):
        url_forgot = reverse('forgot_password')
        r = self.client.post(url_forgot, {'email': 'missing@example.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, url_forgot)
        self.assertEqual(PasswordResetOTP.objects.count(), 0)

    def test_forgot_password_wrong_otp_stays_on_otp_step(self):
        User.objects.create_user(
            username='bob',
            email='bob@example.com',
            password='Somepass123456',
        )
        self.client.post(reverse('forgot_password'), {'email': 'bob@example.com'})
        otp_url = reverse('forgot_password_otp')
        r = self.client.post(otp_url, {'code': '000000'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, otp_url)
        self.assertFalse(self.client.session.get('pw_reset_otp_verified'))


@override_settings(**FLOW_SETTINGS)
class RegistrationOtpFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_register_and_verify_creates_user(self):
        reg_url = reverse('user_register')
        verify_url = reverse('verify_otp')
        data = {
            'username': 'newshopuser',
            'email': 'newshop@example.com',
            'phone': '0500000000',
            'password1': 'Validpass1234',
            'password2': 'Validpass1234',
        }
        r = self.client.post(reg_url, data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, verify_url)
        self.assertEqual(self.client.session.get('otp_email'), 'newshop@example.com')

        rec = EmailOTP.objects.get(email='newshop@example.com', is_verified=False)
        r2 = self.client.post(
            verify_url,
            {'action': 'verify', 'otp_code': rec.code},
        )
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(r2.url, reverse('wardrobe'))
        self.assertTrue(User.objects.filter(username='newshopuser').exists())
        u = User.objects.get(username='newshopuser')
        self.assertTrue(u.check_password('Validpass1234'))
        prof = u.profile
        self.assertIsNotNone(prof.email_verified_at)


@override_settings(**FLOW_SETTINGS)
class ShippingPortalPermissionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_anonymous_redirected_from_dashboard(self):
        r = self.client.get(reverse('shipping:dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('shipping:login'), r.url)

    def test_regular_user_cannot_access_shipping_dashboard(self):
        user = User.objects.create_user(
            username='regular',
            email='reg@example.com',
            password='Longpassword1234',
        )
        UserProfile.objects.update_or_create(
            user=user,
            defaults={'account_type': UserProfile.ACCOUNT_REGULAR},
        )
        self.client.force_login(user)
        r = self.client.get(reverse('shipping:dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('shipping:login'), r.url)

    def test_courier_can_open_dashboard(self):
        courier = User.objects.create_user(
            username='courier1',
            email='c@example.com',
            password='Courierpass1234',
        )
        UserProfile.objects.update_or_create(
            user=courier,
            defaults={'account_type': UserProfile.ACCOUNT_COURIER},
        )
        self.client.force_login(courier)
        r = self.client.get(reverse('shipping:dashboard'))
        self.assertEqual(r.status_code, 200)


@override_settings(**FLOW_SETTINGS)
class ManageForgotPasswordSmokeTests(TestCase):
    """تدخين سريع لمسار نسيت كلمة المرور في الإدارة (موظف فقط)."""

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_staff_forgot_password_creates_otp(self):
        User.objects.create_user(
            username='adminx',
            email='adminx@example.com',
            password='Staffpass1234',
            is_staff=True,
        )
        url = reverse('manage:forgot_password')
        r = self.client.post(url, {'email': 'adminx@example.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('manage:forgot_password_otp'))
        self.assertTrue(
            PasswordResetOTP.objects.filter(email__iexact='adminx@example.com').exists()
        )


class StorefrontVariantRegressionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.compartment = Compartment.objects.create(name_ar='الدولاب', order=1, is_active=True)
        self.shelf = Shelf.objects.create(compartment=self.compartment, name_ar='الملابس', order=1, is_active=True)
        self.category = Category.objects.create(shelf=self.shelf, name_ar='تيشيرتات', order=1, is_active=True)

    def test_product_page_falls_back_to_main_product_when_only_placeholder_variant(self):
        product = Product.objects.create(
            category=self.category,
            sku='T-900',
            name_ar='تيشيرت أسود',
            price='2000.00',
            stock=12,
            is_active=True,
        )
        ProductVariant.objects.create(
            product=product,
            code='T-900-DEFAULT',
            title='النسخة الافتراضية',
            stock_quantity=0,
            price='300.00',
            is_active=True,
        )

        resp = self.client.get(reverse('product', args=[product.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['selected_variant'])
        self.assertEqual(str(resp.context['page_price']), '2000.00')
        self.assertEqual(resp.context['page_stock'], 12)

    def test_product_page_prefers_distinct_variant_when_color_is_defined(self):
        product = Product.objects.create(
            category=self.category,
            sku='T-901',
            name_ar='تيشيرت ألوان',
            price='90.00',
            stock=7,
            is_active=True,
        )
        variant = ProductVariant.objects.create(
            product=product,
            code='T-901-V001',
            title='أحمر',
            color_name='أحمر',
            color_hex='#FF0000',
            stock_quantity=5,
            price='120.00',
            is_active=True,
        )

        resp = self.client.get(reverse('product', args=[product.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['selected_variant'].id, variant.id)
        self.assertEqual(str(resp.context['page_price']), '120.00')
        self.assertEqual(resp.context['page_stock'], 5)
