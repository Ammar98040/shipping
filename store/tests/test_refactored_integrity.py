"""
اختبارات تكامل للأجزاء المُعاد هيكلتها: views، رفع صور الدردشة، mark-seen، الدردشة الداخلية، webhooks.
"""
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from store import views as views_aggregate
from store.internal_chat_service import apply_internal_chat_routing, create_internal_chat_messages
from store.models import (
    Category,
    Compartment,
    InternalSupportMessage,
    InternalSupportThread,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentAttempt,
    Product,
    ProductVariant,
    Return,
    Shelf,
    SupportMessage,
    SupportThread,
    UserProfile,
)
from store.money_display import format_sar_amount
from store.revenue_stats import get_revenue_stats_formatted


def _tiny_png():
    return (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
        b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )


FLOW_SETTINGS = dict(
    TURNSTILE_SITE_KEY='',
    TURNSTILE_SECRET_KEY='',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    CHAT_IMAGE_MAX_BYTES=500_000,
    CHAT_IMAGE_MAX_COUNT=10,
)


class MoneyDisplayTests(TestCase):
    """عرض المبالغ في الواجهة: بدون أصفار عشرية طويلة من float."""

    def test_format_sar_strips_float_noise(self):
        self.assertEqual(format_sar_amount(2582.2700000000004), '2582.27')

    def test_format_sar_handles_int_and_decimal_strings(self):
        self.assertEqual(format_sar_amount(100), '100')
        self.assertEqual(format_sar_amount('10.50'), '10.5')


class RevenueStatsTests(TestCase):
    """إيرادات: فيزا + كاش − مرتجعات (طلبات مُسلَّمة فقط)."""

    def setUp(self):
        self.compartment = Compartment.objects.create(name_ar='د', order=1, is_active=True)
        self.shelf = Shelf.objects.create(compartment=self.compartment, name_ar='ر', order=1, is_active=True)
        self.category = Category.objects.create(shelf=self.shelf, name_ar='ص', order=1, is_active=True)
        self.product = Product.objects.create(
            category=self.category,
            sku='RS-1',
            slug='rs-1',
            name_ar='منتج',
            price=Decimal('100.00'),
            stock=10,
            is_active=True,
        )

    def test_revenue_net_is_gateway_plus_cash_minus_refunds(self):
        o_gw = Order.objects.create(
            customer_name='أ',
            customer_phone='050',
            address='ع',
            status=Order.STATUS_DELIVERED,
            payment_method=Order.PAYMENT_GATEWAY,
        )
        OrderItem.objects.create(
            order=o_gw,
            product=self.product,
            quantity=2,
            price=Decimal('50.00'),
            product_name_snapshot='x',
        )
        o_cash = Order.objects.create(
            customer_name='ب',
            customer_phone='051',
            address='ع2',
            status=Order.STATUS_DELIVERED,
            payment_method=Order.PAYMENT_CASH,
        )
        OrderItem.objects.create(
            order=o_cash,
            product=self.product,
            quantity=1,
            price=Decimal('60.00'),
            product_name_snapshot='y',
        )
        Return.objects.create(
            order=o_gw,
            status=Return.STATUS_APPROVED,
            refund_amount=Decimal('25.00'),
        )

        s = get_revenue_stats_formatted()
        self.assertEqual(s['revenue_gateway'], '100')
        self.assertEqual(s['revenue_cash'], '60')
        self.assertEqual(s['revenue_gross'], '160')
        self.assertEqual(s['refunds_total'], '25')
        self.assertEqual(s['revenue_net'], '135')
        self.assertEqual(s['total_revenue'], '135')


@override_settings(**FLOW_SETTINGS)
class ViewsAggregationTests(TestCase):
    """التأكد أن store.views يجمّع الواجهات من الوحدات الفرعية."""

    def test_aggregate_exports_storefront_support_webhooks(self):
        self.assertTrue(callable(getattr(views_aggregate, 'wardrobe_view', None)))
        self.assertTrue(callable(getattr(views_aggregate, 'support_chat', None)))
        self.assertTrue(callable(getattr(views_aggregate, 'support_send', None)))
        self.assertTrue(callable(getattr(views_aggregate, 'fake_gateway_webhook', None)))

    def test_wardrobe_url_resolves_200(self):
        r = self.client.get(reverse('wardrobe'))
        self.assertEqual(r.status_code, 200)


@override_settings(**FLOW_SETTINGS)
class SupportSendValidationIntegrationTests(TestCase):
    """رفع صور الدعم: رفض النوع السيء وقبول النص أو الصورة الصالحة."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        session = self.client.session
        session['support_guest_phone'] = '0500000000'
        session.save()

    def test_rejects_non_image_upload(self):
        bad = SimpleUploadedFile('malware.exe', b'not an image', content_type='application/octet-stream')
        r = self.client.post(
            reverse('support_send'),
            {'message': 'x', 'image': bad},
        )
        self.assertEqual(r.status_code, 400)
        data = r.json()
        self.assertEqual(data.get('success'), False)
        self.assertEqual(data.get('error'), 'image_invalid_type')

    def test_guest_text_message_succeeds(self):
        r = self.client.post(
            reverse('support_send'),
            {'message': 'مرحباً بخدمة العملاء'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('success'))
        self.assertTrue(SupportMessage.objects.filter(text__icontains='مرحباً').exists())

    def test_valid_png_upload_succeeds(self):
        png = SimpleUploadedFile('ok.png', _tiny_png(), content_type='image/png')
        r = self.client.post(
            reverse('support_send'),
            {'message': '', 'image': png},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(SupportMessage.objects.filter(image__isnull=False).exists())


@override_settings(**FLOW_SETTINGS)
class ManageMarkSeenCsrfIntegrationTests(TestCase):
    """مسار mark-seen يعمل مع رأس CSRF (بدون csrf_exempt)."""

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_mark_seen_json_post_with_csrf_header(self):
        user = User.objects.create_user(
            username='superops',
            email='su@example.com',
            password='Superpass123456!',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(user)
        self.client.get(reverse('manage:dashboard'))
        token = self.client.cookies.get('csrftoken')
        self.assertIsNotNone(token)
        url = reverse('manage:mark_seen_json')
        r = self.client.post(
            url,
            data=json.dumps({'key': 'order:999'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token.value,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get('ok'), True)


class InternalChatServiceTests(TestCase):
    """منطق مشترك للدردشة الداخلية."""

    def test_manager_routing_sets_sender_manager(self):
        staff = User.objects.create_user('staff_ic', 'a@ic.com', 'Pass123456789!')
        mgr = User.objects.create_user('mgr_ic', 'b@ic.com', 'Pass123456789!')
        UserProfile.objects.update_or_create(
            user=staff,
            defaults={'account_type': UserProfile.ACCOUNT_COURIER},
        )
        thread = InternalSupportThread.objects.create(
            department=InternalSupportThread.DEPT_SHIPPING,
            staff_user=staff,
            status=InternalSupportThread.STATUS_WAITING,
        )
        sender = apply_internal_chat_routing(
            thread,
            user=mgr,
            is_manager=True,
            manager_account_type=UserProfile.ACCOUNT_SHIPPING_MANAGER,
        )
        self.assertEqual(sender, InternalSupportMessage.SENDER_MANAGER)
        # الخدمة تُحدّث الحقول في الذاكرة فقط؛ الحفظ يتم في الـ view عبر thread.save()
        self.assertEqual(thread.manager_user_id, mgr.id)

    def test_create_messages_text_only(self):
        u = User.objects.create_user('u1', 'u1@ic.com', 'Pass123456789!')
        thread = InternalSupportThread.objects.create(
            department=InternalSupportThread.DEPT_WAREHOUSE,
            staff_user=u,
            status=InternalSupportThread.STATUS_ACTIVE,
        )
        create_internal_chat_messages(
            thread,
            InternalSupportMessage.SENDER_STAFF,
            u,
            'نص تجريبي',
            [],
        )
        self.assertEqual(thread.messages.count(), 1)
        self.assertEqual(thread.messages.first().text, 'نص تجريبي')


@override_settings(**FLOW_SETTINGS)
class ShippingInternalChatPortalTests(TestCase):
    """صفحة الدردشة الداخلية للشحن تعرض السياق و portal_slug."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.courier = User.objects.create_user(
            username='cour_ic',
            email='c@ic.com',
            password='Courierpass1234!',
        )
        UserProfile.objects.update_or_create(
            user=self.courier,
            defaults={'account_type': UserProfile.ACCOUNT_COURIER},
        )
        self.client.force_login(self.courier)

    def test_internal_chat_get_200_and_portal_slug(self):
        r = self.client.get(reverse('shipping:internal_chat'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['portal_slug'], 'shipping')


@override_settings(**FLOW_SETTINGS)
class WarehouseInternalChatPortalTests(TestCase):
    """صفحة الدردشة الداخلية للمستودع تعرض portal_slug."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.packer = User.objects.create_user(
            username='pack_ic',
            email='p@ic.com',
            password='Packerpass1234!',
        )
        UserProfile.objects.update_or_create(
            user=self.packer,
            defaults={'account_type': UserProfile.ACCOUNT_PACKER},
        )
        self.client.force_login(self.packer)

    def test_internal_chat_get_portal_slug_warehouse(self):
        r = self.client.get(reverse('warehouse:internal_chat'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['portal_slug'], 'warehouse')


@override_settings(**FLOW_SETTINGS)
class FakeWebhookSecretTests(TestCase):
    """تكامل الوهمي: رفض سر خاطئ."""

    def test_fake_gateway_webhook_rejects_wrong_secret(self):
        from store.models import Order, PaymentAttempt

        user = User.objects.create_user('buyer', 'buyer@x.com', 'Pass123456789!')
        order = Order.objects.create(
            user=user,
            customer_name='عميل',
            customer_phone='050',
            address='عنوان',
            status=Order.STATUS_PENDING,
            payment_method=Order.PAYMENT_GATEWAY,
        )
        attempt = PaymentAttempt.objects.create(order=order, amount='100.00', status=PaymentAttempt.STATUS_PENDING)
        payload = {
            'secret': 'wrong-secret',
            'attempt_id': attempt.id,
            'result': 'success',
            'reference': 'r1',
        }
        r = self.client.post(
            reverse('fake_gateway_webhook'),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json().get('error'), 'Invalid gateway secret')


@override_settings(**FLOW_SETTINGS)
class StaffSupportThreadSendValidationTests(TestCase):
    """موظف الإدارة: إرسال مرفق غير صالح يُرفض."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.staff = User.objects.create_user(
            username='cs_staff',
            email='cs@example.com',
            password='Cspass123456!',
            is_staff=True,
            is_superuser=True,
        )
        self.thread = SupportThread.objects.create(
            guest_phone='050',
            status=SupportThread.STATUS_WAITING,
            is_archived=False,
            last_customer_message_at=timezone.now(),
        )

    def test_support_thread_send_rejects_bad_file(self):
        self.client.force_login(self.staff)
        bad = SimpleUploadedFile('x.exe', b'abc', content_type='application/octet-stream')
        url = reverse('manage:support_thread_send_json', args=[self.thread.id])
        r = self.client.post(
            url,
            {'message': 'hi', 'image': bad},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json().get('error'), 'image_invalid_type')


@override_settings(**FLOW_SETTINGS)
class SupportThreadClaimReadWorkflowTests(TestCase):
    """استلام المحادثة + قراءة إلزامية قبل الإرسال للمندوب."""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.agent = User.objects.create_user(
            username='cs_agent_claim',
            email='csc@example.com',
            password='Cspass123456!',
            is_staff=True,
        )
        UserProfile.objects.update_or_create(
            user=self.agent,
            defaults={'account_type': UserProfile.ACCOUNT_CUSTOMER_SERVICE},
        )
        self.agent_b = User.objects.create_user(
            username='cs_agent_other',
            email='cso@example.com',
            password='Cspass123456!',
            is_staff=True,
        )
        UserProfile.objects.update_or_create(
            user=self.agent_b,
            defaults={'account_type': UserProfile.ACCOUNT_CUSTOMER_SERVICE},
        )
        self.manager = User.objects.create_user(
            username='cs_mgr',
            email='csm@example.com',
            password='Mgrpass123456!',
            is_staff=True,
        )
        UserProfile.objects.update_or_create(
            user=self.manager,
            defaults={'account_type': UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER},
        )
        self.thread = SupportThread.objects.create(
            guest_phone='0511111111',
            status=SupportThread.STATUS_WAITING,
            is_archived=False,
            last_customer_message_at=timezone.now(),
        )
        SupportMessage.objects.create(
            thread=self.thread,
            sender_type=SupportMessage.SENDER_CUSTOMER,
            text='مرحبا',
        )

    def test_agent_send_without_claim_returns_must_claim_first(self):
        self.client.force_login(self.agent)
        url = reverse('manage:support_thread_send_json', args=[self.thread.id])
        r = self.client.post(url, {'message': 'رد'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json().get('error'), 'must_claim_first')

    def test_second_agent_claim_conflict(self):
        claim_url = reverse('manage:support_thread_claim_json', args=[self.thread.id])
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(claim_url).status_code, 200)
        self.client.force_login(self.agent_b)
        r = self.client.post(claim_url)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json().get('error'), 'claimed_by_another_agent')

    def test_claim_then_send_requires_reads_then_ok_after_mark_read(self):
        self.client.force_login(self.agent)
        claim_url = reverse('manage:support_thread_claim_json', args=[self.thread.id])
        self.client.post(claim_url)
        send_url = reverse('manage:support_thread_send_json', args=[self.thread.id])
        r = self.client.post(send_url, {'message': 'رد'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json().get('error'), 'must_read_customer_messages')

        mark_url = reverse('manage:support_thread_mark_read_json', args=[self.thread.id])
        self.client.post(mark_url, {'mark_all': '1'})
        r2 = self.client.post(send_url, {'message': 'رد'})
        self.assertEqual(r2.status_code, 200)

        self.thread.refresh_from_db()
        self.assertEqual(self.thread.status, SupportThread.STATUS_ACTIVE)
        self.assertEqual(self.thread.assigned_staff_id, self.agent.id)

    def test_second_agent_blocked_from_thread_detail(self):
        claim_url = reverse('manage:support_thread_claim_json', args=[self.thread.id])
        self.client.force_login(self.agent)
        self.client.post(claim_url)
        self.client.force_login(self.agent_b)
        r = self.client.get(reverse('manage:support_thread_detail', args=[self.thread.id]))
        self.assertEqual(r.status_code, 302)

    def test_manager_send_implicit_claim_without_prior_claim(self):
        self.client.force_login(self.manager)
        send_url = reverse('manage:support_thread_send_json', args=[self.thread.id])
        r = self.client.post(send_url, {'message': 'من المسؤول'})
        self.assertEqual(r.status_code, 200)
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.assigned_staff_id, self.manager.id)


@override_settings(**FLOW_SETTINGS)
class FakeGatewayCallbackSessionTests(TestCase):
    """
    الدفع الوهمي: يجب أن يُحدَّث الطلب إلى «مدفوع» عند نجاح الـ callback
    إذا كانت الجلسة تحتوي fake_gateway_attempt_id (كما بعد checkout)،
    حتى لو انقطعت جلسة تسجيل الدخول أو كان المستخدم مسجلاً أثناء طلب ضيف.
    """

    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_registered_order_paid_when_session_matches_but_user_not_logged_in(self):
        user = User.objects.create_user('buyer', 'buyer@x.com', 'Pass123456789!')
        order = Order.objects.create(
            user=user,
            customer_name='عميل',
            customer_phone='050',
            address='عنوان',
            status=Order.STATUS_PENDING,
            payment_method=Order.PAYMENT_GATEWAY,
        )
        attempt = PaymentAttempt.objects.create(order=order, amount='100.00', status=PaymentAttempt.STATUS_PENDING)
        session = self.client.session
        session['fake_gateway_attempt_id'] = attempt.id
        session.save()

        url = reverse('fake_gateway_callback', args=[attempt.id])
        r = self.client.post(url, {'result': 'success', 'reference': 'TEST-REF'})
        self.assertEqual(r.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PAY_STATUS_PAID)

    def test_guest_order_paid_when_session_matches_even_if_user_logged_in(self):
        other = User.objects.create_user('other', 'o@x.com', 'Pass123456789!')
        order = Order.objects.create(
            user=None,
            customer_type=Order.CUSTOMER_GUEST,
            customer_name='ضيف',
            customer_phone='051',
            address='عنوان',
            status=Order.STATUS_PENDING,
            payment_method=Order.PAYMENT_GATEWAY,
        )
        attempt = PaymentAttempt.objects.create(order=order, amount='50.00', status=PaymentAttempt.STATUS_PENDING)
        session = self.client.session
        session['fake_gateway_attempt_id'] = attempt.id
        session.save()
        self.client.force_login(other)

        url = reverse('fake_gateway_callback', args=[attempt.id])
        r = self.client.post(url, {'result': 'success', 'reference': 'TEST-REF-2'})
        self.assertEqual(r.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PAY_STATUS_PAID)


@override_settings(**FLOW_SETTINGS)
class CustomerServiceOrderEditTests(TestCase):
    """تعديل بيانات الطلب الأساسية لممثل خدمة العملاء قبل الشحن فقط."""

    def setUp(self):
        self.client = Client()
        self.agent = User.objects.create_user(
            username='cs_agent',
            email='agent@example.com',
            password='Agentpass1234!',
            is_staff=True,
        )
        UserProfile.objects.update_or_create(
            user=self.agent,
            defaults={'account_type': UserProfile.ACCOUNT_CUSTOMER_SERVICE},
        )
        self.order = Order.objects.create(
            customer_name='الاسم القديم',
            customer_phone='0500000000',
            address='العنوان القديم',
            notes='ملاحظة قديمة',
            status=Order.STATUS_PENDING,
            payment_method=Order.PAYMENT_GATEWAY,
        )

    def test_agent_can_edit_order_basics_before_shipping(self):
        self.client.force_login(self.agent)
        url = reverse('manage:order_detail', args=[self.order.id])
        r = self.client.post(
            url,
            {
                'action': 'edit_customer_basic',
                'customer_name': 'اسم جديد',
                'customer_phone': '0555555555',
                'address': 'عنوان جديد',
                'order_notes': 'ملاحظة جديدة',
            },
        )
        self.assertEqual(r.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.customer_name, 'اسم جديد')
        self.assertEqual(self.order.customer_phone, '0555555555')
        self.assertEqual(self.order.address, 'عنوان جديد')
        self.assertEqual(self.order.notes, 'ملاحظة جديدة')
        log = OrderStatusHistory.objects.filter(order=self.order, changed_by=self.agent).last()
        self.assertIsNotNone(log)
        self.assertIn('تعديل بيانات العميل الأساسية', log.note)
        self.assertIn('الاسم:', log.note)

    def test_agent_cannot_edit_order_basics_when_delivered(self):
        self.order.status = Order.STATUS_DELIVERED
        self.order.save(update_fields=['status'])
        self.client.force_login(self.agent)
        url = reverse('manage:order_detail', args=[self.order.id])
        r = self.client.post(
            url,
            {
                'action': 'edit_customer_basic',
                'customer_name': 'تعديل مرفوض',
                'customer_phone': '0511111111',
                'address': 'عنوان مرفوض',
                'order_notes': 'ملاحظة مرفوضة',
            },
        )
        self.assertEqual(r.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.customer_name, 'الاسم القديم')
        self.assertEqual(self.order.customer_phone, '0500000000')

    def test_superuser_cannot_edit_order_basics_when_delivered(self):
        admin = User.objects.create_superuser('adminx', 'adminx@example.com', 'Strongpass123!')
        self.order.status = Order.STATUS_DELIVERED
        self.order.save(update_fields=['status'])
        self.client.force_login(admin)
        url = reverse('manage:order_detail', args=[self.order.id])
        r = self.client.post(
            url,
            {
                'action': 'edit_customer_basic',
                'customer_name': 'AdminEdit',
                'customer_phone': '0522222222',
                'address': 'Admin Address',
                'order_notes': 'Admin note',
            },
        )
        self.assertEqual(r.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.customer_name, 'الاسم القديم')
        self.assertEqual(self.order.customer_phone, '0500000000')

    def test_agent_cannot_advance_status_from_order_detail(self):
        self.client.force_login(self.agent)
        url = reverse('manage:order_detail', args=[self.order.id])
        r = self.client.post(
            url,
            {
                'action': 'advance',
                'new_status': Order.STATUS_CONFIRMED,
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)


@override_settings(**FLOW_SETTINGS)
class OrderEditStockDeltaTests(TestCase):
    """تعديل الطلب: حذف/استبدال يطبّق فروقات المخزون بشكل صحيح."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser('adm_edit', 'adm_edit@example.com', 'Strongpass123!')
        comp = Compartment.objects.create(name_ar='دولاب', order=1, is_active=True)
        shelf = Shelf.objects.create(compartment=comp, name_ar='رف', order=1, is_active=True)
        cat = Category.objects.create(shelf=shelf, name_ar='تصنيف', order=1, is_active=True)
        self.p1 = Product.objects.create(category=cat, sku='P1', slug='p1', name_ar='منتج1', price=Decimal('10.00'), stock=8, is_active=True)
        self.v1 = ProductVariant.objects.create(product=self.p1, code='P1-V1', title='v1', stock_quantity=8, is_active=True)
        self.p2 = Product.objects.create(category=cat, sku='P2', slug='p2', name_ar='منتج2', price=Decimal('20.00'), stock=4, is_active=True)
        self.v2 = ProductVariant.objects.create(product=self.p2, code='P2-V1', title='v1', stock_quantity=4, is_active=True)
        self.order = Order.objects.create(
            customer_name='عميل',
            customer_phone='050',
            address='عنوان',
            status=Order.STATUS_PENDING,
            payment_method=Order.PAYMENT_GATEWAY,
        )
        snap = OrderItem.build_snapshots(self.p1, self.v1, None, image_url='')
        OrderItem.objects.create(order=self.order, product=self.p1, variant=self.v1, quantity=2, price=Decimal('10.00'), **snap)
        snap2 = OrderItem.build_snapshots(self.p2, self.v2, None, image_url='')
        OrderItem.objects.create(order=self.order, product=self.p2, variant=self.v2, quantity=1, price=Decimal('20.00'), **snap2)

    def test_remove_line_restores_stock(self):
        self.client.force_login(self.admin)
        url = reverse('manage:order_edit', args=[self.order.id])
        it = self.order.items.first()
        other = self.order.items.exclude(pk=it.pk).first()
        r = self.client.post(
            url,
            {
                'edit_action': 'apply',
                'item_id': [str(it.id), str(other.id)],
                f'remove_{it.id}': '1',
                f'qty_{other.id}': '1',
            },
        )
        self.assertEqual(r.status_code, 302)
        self.p1.refresh_from_db()
        self.v1.refresh_from_db()
        self.assertEqual(self.p1.stock, 10)
        self.assertEqual(self.v1.stock_quantity, 10)

    def test_replace_variant_restores_old_and_deducts_new(self):
        self.client.force_login(self.admin)
        url = reverse('manage:order_edit', args=[self.order.id])
        it = self.order.items.first()
        other = self.order.items.exclude(pk=it.pk).first()
        r = self.client.post(
            url,
            {
                'edit_action': 'apply',
                'item_id': [str(it.id), str(other.id)],
                f'qty_{it.id}': '2',
                f'repl_variant_{it.id}': str(self.v2.id),
                f'qty_{other.id}': '1',
            },
        )
        self.assertEqual(r.status_code, 302)
        self.p1.refresh_from_db()
        self.v1.refresh_from_db()
        self.p2.refresh_from_db()
        self.v2.refresh_from_db()
        self.assertEqual(self.p1.stock, 10)
        self.assertEqual(self.v1.stock_quantity, 10)
        self.assertEqual(self.p2.stock, 2)
        self.assertEqual(self.v2.stock_quantity, 2)

    def test_preview_shows_delta_without_applying_stock_change(self):
        self.client.force_login(self.admin)
        url = reverse('manage:order_edit', args=[self.order.id])
        it = self.order.items.first()
        r = self.client.post(
            url,
            {
                'edit_action': 'preview',
                'item_id': [str(it.id)],
                f'qty_{it.id}': '3',
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ملخص فرق السعر قبل الحفظ')
        self.assertContains(r, 'سجل التعديلات المقترحة')
        self.p1.refresh_from_db()
        self.v1.refresh_from_db()
        self.assertEqual(self.p1.stock, 8)
        self.assertEqual(self.v1.stock_quantity, 8)

    def test_order_edit_page_shows_persistent_edit_history(self):
        self.client.force_login(self.admin)
        it = self.order.items.first()
        self.client.post(
            reverse('manage:order_edit', args=[self.order.id]),
            {
                'edit_action': 'apply',
                'item_id': [str(it.id)],
                f'qty_{it.id}': '3',
            },
        )
        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=self.order,
                note__icontains='تفاصيل العمليات',
            ).exists()
        )
        r = self.client.get(reverse('manage:order_edit', args=[self.order.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'سجل تعديلات الطلب (دائم)')
        self.assertContains(r, 'المنتج الأصلي')
        self.assertContains(r, 'المنتج البديل / النتيجة')
