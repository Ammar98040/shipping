"""بوليصة الشحن: تسجيل تلقائي عند الطباعة، استعادة من الإدارة."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store.models import Order, ShippingWaybill, UserProfile

FLOW_SETTINGS = dict(
    TURNSTILE_SITE_KEY='',
    TURNSTILE_SECRET_KEY='',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)


@override_settings(**FLOW_SETTINGS)
class ShippingWaybillAutoTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.packer = User.objects.create_user(
            username='packer_wb',
            email='p@example.com',
            password='Packerpass1234',
        )
        UserProfile.objects.update_or_create(
            user=self.packer,
            defaults={'account_type': UserProfile.ACCOUNT_PACKER},
        )
        self.order = Order.objects.create(
            customer_name='عميل',
            customer_phone='0500000000',
            address='الرياض',
            status=Order.STATUS_PROCESSING,
            packer=self.packer,
        )

    def test_opening_print_label_creates_unified_waybill(self):
        self.client.force_login(self.packer)
        url = reverse('warehouse:shipping_label', kwargs={'pk': self.order.pk})
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        wb = ShippingWaybill.objects.get(order=self.order)
        self.assertTrue(wb.waybill_number.startswith('DLBK-'))
        self.assertTrue(wb.barcode_value.startswith('DLBK:'))
        self.assertEqual(wb.linked_internal_code, wb.barcode_value.replace('DLBK:', ''))

    def test_warehouse_create_waybill_via_ajax(self):
        self.client.force_login(self.packer)
        url = reverse('warehouse:create_shipping_waybill', kwargs={'pk': self.order.pk})
        r = self.client.post(
            url,
            {},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get('success'))
        self.assertIn('html', data)
        self.assertIn('DLBK:', data['html'])
        wb = ShippingWaybill.objects.get(order=self.order)
        self.assertTrue(wb.barcode_value.startswith('DLBK:'))

    def test_staff_can_restore_waybill_from_manage(self):
        self.client.force_login(self.packer)
        self.client.get(reverse('warehouse:shipping_label', kwargs={'pk': self.order.pk}))

        staff = User.objects.create_user(
            username='mgr_wb',
            email='m@example.com',
            password='Staffpass1234',
            is_staff=True,
        )
        self.client.force_login(staff)
        detail = reverse('manage:order_detail', kwargs={'pk': self.order.pk})
        r = self.client.post(detail, {'action': 'waybill_restore'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(ShippingWaybill.objects.filter(order=self.order).exists())
