"""اختبارات مساعد دردشة خدمة العملاء (قواعد + أزرار سريعة)."""

from decimal import Decimal

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store.models import (
    Category,
    Compartment,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    Shelf,
    SupportMessage,
    SupportThread,
)
from store.support_bot import (
    BOT_KIND,
    EDIT_NAME,
    FOLLOWUP_TEXT,
    LABEL_END,
    LABEL_MORE,
    SUPPORT_AUTO_WAITING_REPLY,
    WELCOME_TEXT,
)

FLOW_SETTINGS = dict(
    TURNSTILE_SITE_KEY='',
    TURNSTILE_SECRET_KEY='',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    CHAT_IMAGE_MAX_BYTES=500_000,
    CHAT_IMAGE_MAX_COUNT=10,
)


@override_settings(**FLOW_SETTINGS)
class SupportChatBotIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        s = self.client.session
        s['support_guest_phone'] = '0500000000'
        s.save()

    def test_open_chat_shows_bot_without_creating_thread(self):
        r = self.client.get(reverse('support_chat'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(
            SupportThread.objects.filter(guest_phone='0500000000', is_archived=False).exists()
        )
        poll = self.client.get(reverse('support_poll'))
        self.assertEqual(poll.status_code, 200)
        data = poll.json()
        self.assertTrue(data.get('success'))
        self.assertTrue(any(m.get('is_bot') for m in data.get('messages') or []))
        self.assertFalse(
            SupportMessage.objects.filter(metadata__kind=BOT_KIND, text__icontains='اختر').exists()
        )

    def test_first_customer_action_creates_thread_and_welcome(self):
        self.client.post(reverse('support_send'), {'message': 'تتبع الطلب'})
        t = SupportThread.objects.filter(guest_phone='0500000000', is_archived=False).order_by('-id').first()
        self.assertIsNotNone(t)
        self.assertIsNotNone(t.last_customer_message_at)
        w = SupportMessage.objects.filter(thread=t, metadata__kind=BOT_KIND).order_by('id').first()
        self.assertIsNotNone(w)
        self.assertIn(WELCOME_TEXT[:12], w.text)
        self.assertTrue(len((w.metadata or {}).get('quick_replies') or []) >= 1)

    def test_menu_first_message_does_not_add_auto_waiting(self):
        r = self.client.post(reverse('support_send'), {'message': 'تتبع الطلب'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('success'))
        self.assertFalse(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000',
                text=SUPPORT_AUTO_WAITING_REPLY,
            ).exists()
        )
        self.assertTrue(
            SupportMessage.objects.filter(thread__guest_phone='0500000000', text__icontains='رقم الطلب').exists()
        )

    def test_free_text_first_message_adds_auto_waiting(self):
        r = self.client.post(reverse('support_send'), {'message': 'أريد استفساراً عاماً عن الطلبات'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000',
                text=SUPPORT_AUTO_WAITING_REPLY,
            ).exists()
        )

    def test_guest_resolves_order_id_in_track_flow(self):
        comp = Compartment.objects.create(name_ar='د', order=1, is_active=True)
        shelf = Shelf.objects.create(compartment=comp, name_ar='ر', order=1, is_active=True)
        cat = Category.objects.create(shelf=shelf, name_ar='ت', order=1, is_active=True)
        p = Product.objects.create(
            category=cat, sku='SB', slug='sb', name_ar='م', price=Decimal('5.00'), stock=1, is_active=True
        )
        v = ProductVariant.objects.create(product=p, code='V1', title='v', stock_quantity=1, is_active=True)
        order = Order.objects.create(
            customer_name='x',
            customer_phone='0500000000',
            address='a',
            status=Order.STATUS_SHIPPED,
            customer_type=Order.CUSTOMER_GUEST,
        )
        snap = OrderItem.build_snapshots(p, v, None, image_url='')
        OrderItem.objects.create(order=order, product=p, variant=v, quantity=1, price=Decimal('5.00'), **snap)

        self.client.get(reverse('support_chat'))
        self.client.post(reverse('support_send'), {'message': 'تتبع الطلب'})
        self.client.post(reverse('support_send'), {'message': str(order.id)})

        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000',
                text__icontains=f'#{order.id}',
                metadata__kind=BOT_KIND,
            ).exists()
        )
        summary = SupportMessage.objects.filter(
            thread__guest_phone='0500000000',
            text__icontains=f'#{order.id}',
            metadata__kind=BOT_KIND,
        ).first()
        self.assertIsNotNone(summary)
        self.assertIn(FOLLOWUP_TEXT, summary.text)

    def test_human_intent_sends_waiting_reply_not_bot(self):
        self.client.get(reverse('support_chat'))
        r = self.client.post(reverse('support_send'), {'message': 'أريد التحدث مع موظف'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('success'))
        w = SupportMessage.objects.filter(
            thread__guest_phone='0500000000',
            text=SUPPORT_AUTO_WAITING_REPLY,
        )
        self.assertTrue(w.exists())
        self.assertFalse(w.filter(metadata__kind=BOT_KIND).exists())
        # لا تضاعف لرسالة الانتظار التلقائية عند نفس الرسالة الأولى
        self.assertEqual(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000', text=SUPPORT_AUTO_WAITING_REPLY
            ).count(),
            1,
        )

    def test_escalation_sends_waiting_reply(self):
        self.client.get(reverse('support_chat'))
        r = self.client.post(reverse('support_send'), {'message': 'عندي شكوى قانونية على المتجر'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000',
                text=SUPPORT_AUTO_WAITING_REPLY,
            ).exists()
        )

    def test_fuzzy_typo_mowadef_sends_waiting(self):
        """ض بدل ظ في موظف — مطابقة تفاضلية."""
        self.client.get(reverse('support_chat'))
        r = self.client.post(reverse('support_send'), {'message': 'التحدث مع موضف'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000', text=SUPPORT_AUTO_WAITING_REPLY
            ).exists()
        )

    def test_fuzzy_khedma_single_word_sends_waiting(self):
        self.client.get(reverse('support_chat'))
        r = self.client.post(reverse('support_send'), {'message': 'خدمه'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000', text=SUPPORT_AUTO_WAITING_REPLY
            ).exists()
        )

    def test_end_chat_by_followup_label(self):
        self.client.get(reverse('support_chat'))
        r = self.client.post(reverse('support_send'), {'message': LABEL_END})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('success'))
        t = SupportThread.objects.filter(guest_phone='0500000000', is_archived=False).order_by('-id').first()
        self.assertIsNotNone(t)
        t.refresh_from_db()
        self.assertEqual(t.status, SupportThread.STATUS_ENDED)

    def test_auto_waiting_reply_after_customer_ends_and_resends(self):
        self.client.post(reverse('support_send'), {'message': 'أريد مساعدة من الموظف'})
        self.client.post(reverse('support_send'), {'message': LABEL_END})
        ended = SupportThread.objects.filter(
            guest_phone='0500000000',
            status=SupportThread.STATUS_ENDED,
        ).order_by('-id').first()
        self.assertIsNotNone(ended)

        r = self.client.post(reverse('support_send'), {'message': 'مرحباً مرة أخرى'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('success'))

        active = SupportThread.objects.filter(
            guest_phone='0500000000',
            status=SupportThread.STATUS_WAITING,
        ).order_by('-id').first()
        self.assertIsNotNone(active)
        self.assertNotEqual(active.id, ended.id)
        self.assertTrue(
            SupportMessage.objects.filter(
                thread=active,
                text=SUPPORT_AUTO_WAITING_REPLY,
            ).exists()
        )

    def test_more_help_reshows_welcome(self):
        self.client.get(reverse('support_chat'))
        r = self.client.post(reverse('support_send'), {'message': LABEL_MORE})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000', text=WELCOME_TEXT, metadata__kind=BOT_KIND
            ).exists()
        )

    def test_guest_edit_order_name_flow(self):
        comp = Compartment.objects.create(name_ar='د', order=1, is_active=True)
        shelf = Shelf.objects.create(compartment=comp, name_ar='ر', order=1, is_active=True)
        cat = Category.objects.create(shelf=shelf, name_ar='ت', order=1, is_active=True)
        p = Product.objects.create(
            category=cat, sku='SB2', slug='sb2', name_ar='م', price=Decimal('5.00'), stock=1, is_active=True
        )
        v = ProductVariant.objects.create(product=p, code='V2', title='v', stock_quantity=1, is_active=True)
        order = Order.objects.create(
            customer_name='قديم',
            customer_phone='0500000000',
            address='عنوان قديم',
            status=Order.STATUS_PENDING,
            customer_type=Order.CUSTOMER_GUEST,
        )
        snap = OrderItem.build_snapshots(p, v, None, image_url='')
        OrderItem.objects.create(order=order, product=p, variant=v, quantity=1, price=Decimal('5.00'), **snap)

        self.client.get(reverse('support_chat'))
        self.client.post(reverse('support_send'), {'message': 'تعديل بيانات الطلب'})
        self.client.post(reverse('support_send'), {'message': str(order.id)})
        self.client.post(reverse('support_send'), {'message': EDIT_NAME})
        self.client.post(reverse('support_send'), {'message': 'اسم جديد للاختبار'})

        order.refresh_from_db()
        self.assertEqual(order.customer_name, 'اسم جديد للاختبار')
        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000',
                text__icontains='تم حفظ الاسم',
                metadata__kind=BOT_KIND,
            ).exists()
        )

    def test_guest_cannot_edit_shipped_order(self):
        comp = Compartment.objects.create(name_ar='د2', order=1, is_active=True)
        shelf = Shelf.objects.create(compartment=comp, name_ar='ر2', order=1, is_active=True)
        cat = Category.objects.create(shelf=shelf, name_ar='ت2', order=1, is_active=True)
        p = Product.objects.create(
            category=cat, sku='SB3', slug='sb3', name_ar='م', price=Decimal('5.00'), stock=1, is_active=True
        )
        v = ProductVariant.objects.create(product=p, code='V3', title='v', stock_quantity=1, is_active=True)
        order = Order.objects.create(
            customer_name='x',
            customer_phone='0500000000',
            address='a',
            status=Order.STATUS_SHIPPED,
            customer_type=Order.CUSTOMER_GUEST,
        )
        snap = OrderItem.build_snapshots(p, v, None, image_url='')
        OrderItem.objects.create(order=order, product=p, variant=v, quantity=1, price=Decimal('5.00'), **snap)

        self.client.get(reverse('support_chat'))
        self.client.post(reverse('support_send'), {'message': 'تعديل بيانات الطلب'})
        self.client.post(reverse('support_send'), {'message': str(order.id)})

        self.assertTrue(
            SupportMessage.objects.filter(
                thread__guest_phone='0500000000',
                text=SUPPORT_AUTO_WAITING_REPLY,
            ).exists()
        )
        order.refresh_from_db()
        self.assertEqual(order.customer_name, 'x')
