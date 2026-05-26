"""تسلسل بوليصة المندوب: استلام من المتجر قبل تسليم العميل."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store.models import LabelCode, Order, Shipment, UserProfile

FLOW_SETTINGS = dict(
    TURNSTILE_SITE_KEY='',
    TURNSTILE_SECRET_KEY='',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)


@override_settings(**FLOW_SETTINGS)
class ShippingScanSequenceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.courier = User.objects.create_user(
            username='courier_seq',
            email='c@example.com',
            password='Courierpass1234',
        )
        UserProfile.objects.update_or_create(
            user=self.courier,
            defaults={'account_type': UserProfile.ACCOUNT_COURIER},
        )
        self.order = Order.objects.create(
            customer_name='عميل',
            customer_phone='0500000001',
            address='الرياض',
            status=Order.STATUS_READY,
            customer_email='cust@example.com',
        )
        self.shipment = Shipment.objects.create(
            order=self.order,
            courier=self.courier,
            status=Shipment.STATUS_CREATED,
            tracking_number='TRK-SEQ-1',
        )
        self.label = LabelCode.objects.create(
            code='SEQTESTCODE12',
            order=self.order,
            shipment=self.shipment,
        )

    def test_deliver_before_pickup_rejected(self):
        self.client.force_login(self.courier)
        url = reverse('shipping:scan_consume')
        r = self.client.post(
            url,
            {'action': 'deliver', 'code': self.label.code},
            follow=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('shipping:scan_deliver'))
        self.assertNotIn('deliver_code', self.client.session)

    def test_pickup_then_deliver_opens_otp(self):
        self.client.force_login(self.courier)
        consume = reverse('shipping:scan_consume')
        r1 = self.client.post(
            consume,
            {'action': 'pickup', 'code': self.label.code},
            follow=False,
        )
        self.assertEqual(r1.status_code, 302)
        self.shipment.refresh_from_db()
        # بعد الاستلام يُحدَّث الطلب إلى «شُحِن» فيُعاد ضبط الشحنة إلى in_transit (order_engine).
        self.assertIn(
            self.shipment.status,
            (Shipment.STATUS_PICKED, Shipment.STATUS_IN_TRANSIT),
        )

        r2 = self.client.post(
            consume,
            {'action': 'deliver', 'code': self.label.code},
            follow=False,
        )
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(r2.url, reverse('shipping:deliver_otp'))
        self.assertEqual(self.client.session.get('deliver_code'), self.label.code)

    def test_deliver_otp_requires_pickup_even_with_session(self):
        """منع فتح OTP إذا تلاعب أحدهم بالجلسة دون استلام من المتجر."""
        self.client.force_login(self.courier)
        session = self.client.session
        session['deliver_code'] = self.label.code
        session.save()

        r = self.client.get(reverse('shipping:deliver_otp'), follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('shipping:scan_deliver'))
        self.assertNotIn('deliver_code', self.client.session)
