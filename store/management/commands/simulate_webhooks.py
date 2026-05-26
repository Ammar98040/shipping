"""
أمر إدارة: محاكاة Webhooks لبوابة الدفع وشركة الشحن

أمثلة:
  python manage.py simulate_webhooks --order-id 1 --gateway success
  python manage.py simulate_webhooks --order-id 1 --shipping in_transit
  python manage.py simulate_webhooks --order-id 1 --shipping delivered
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'محاكاة Webhooks (fake gateway + fake shipping) لتحديث الطلبات تلقائياً'

    def add_arguments(self, parser):
        parser.add_argument('--order-id', type=int, required=True, help='رقم الطلب')
        parser.add_argument('--gateway', choices=['success', 'fail'], help='نتيجة بوابة الدفع')
        parser.add_argument('--shipping', choices=['created', 'picked_up', 'in_transit', 'out_for_delivery', 'delivered', 'failed'], help='حالة الشحن')
        parser.add_argument('--note', type=str, default='', help='ملاحظة/رسالة للشحن')

    def handle(self, *args, **options):
        from store.integrations.fake_gateway import apply_payment_result
        from store.integrations.fake_shipping import apply_shipping_update
        from store.models import Order, PaymentAttempt, Shipment

        order_id = options['order_id']
        order = Order.objects.get(pk=order_id)

        if options.get('gateway'):
            if order.payment_method != Order.PAYMENT_GATEWAY:
                self.stdout.write(self.style.WARNING('هذا الطلب ليس بوابة دفع. سيتم إنشاء محاولة دفع على أي حال (محاكاة).'))
            attempt = PaymentAttempt.objects.create(order=order, status=PaymentAttempt.STATUS_PENDING, amount=order.total)
            res = apply_payment_result(
                attempt=attempt,
                result=options['gateway'],
                reference=f"SIM-WEBHOOK-{attempt.id}",
                payload={'simulated': True},
                actor=None
            )
            self.stdout.write(self.style.SUCCESS(f"Gateway webhook applied: {res}"))

        if options.get('shipping'):
            shipment = getattr(order, 'shipment', None)
            if not shipment:
                import secrets
                shipment = Shipment.objects.create(
                    order=order,
                    tracking_number=f"FAKE-{secrets.randbelow(10**8):08d}",
                    status=Shipment.STATUS_CREATED,
                    last_event='تم إنشاء الشحنة عبر simulate_webhooks (محاكاة)',
                )
            res = apply_shipping_update(
                shipment=shipment,
                new_status=options['shipping'],
                message=options.get('note', '') or f"simulate_webhooks → {options['shipping']}",
                payload={'simulated': True},
                actor=None
            )
            self.stdout.write(self.style.SUCCESS(f"Shipping webhook applied: {res}"))

        if not options.get('gateway') and not options.get('shipping'):
            self.stdout.write(self.style.ERROR('اختر --gateway أو --shipping (أو الاثنين).'))

