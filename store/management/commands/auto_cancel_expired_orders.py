"""
أمر إدارة: إلغاء الطلبات التي انتهت صلاحيتها تلقائياً

الحالات المعالجة:
  - طلبات pending أكثر من N ساعة بدون تأكيد  → ملغي
  - طلبات بوابة دفع payment_status=pending أكثر من M ساعة → ملغي (فشل دفع)

التشغيل:
  python manage.py auto_cancel_expired_orders
  python manage.py auto_cancel_expired_orders --pending-hours 48 --payment-hours 2 --dry-run
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'يلغي تلقائياً الطلبات المنتهية أو غير المدفوعة بعد مرور المدة المحددة'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pending-hours', type=int, default=48,
            help='عدد الساعات قبل إلغاء طلبات pending بدون تأكيد (افتراضي: 48)'
        )
        parser.add_argument(
            '--payment-hours', type=int, default=2,
            help='عدد الساعات قبل إلغاء طلبات بوابة دفع غير مكتملة (افتراضي: 2)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='معاينة فقط بدون تنفيذ فعلي'
        )

    def handle(self, *args, **options):
        from store.models import Order
        from store.order_engine import OrderTransitionError, cancel_order

        pending_hours  = options['pending_hours']
        payment_hours  = options['payment_hours']
        dry_run        = options['dry_run']
        now            = timezone.now()

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN: no changes will be applied'))

        cancelled_count = 0

        # ── 1. طلبات pending تجاوزت مدة الانتظار ────────────────────────
        cutoff_pending = now - timedelta(hours=pending_hours)
        expired_pending = Order.objects.filter(
            status=Order.STATUS_PENDING,
            created_at__lt=cutoff_pending
        )

        self.stdout.write(f'\nExpired pending orders ({pending_hours}h): {expired_pending.count()}')
        for order in expired_pending:
            age_hours = (now - order.created_at).total_seconds() / 3600
            self.stdout.write(
                f'  - Order #{order.id} | {order.customer_name} | '
                f'age_hours={age_hours:.1f} | '
                f'customer_type={order.customer_type} | payment_method={order.payment_method}'
            )
            if not dry_run:
                try:
                    cancel_order(
                        order,
                        reason=Order.CANCEL_OTHER,
                        note=f'إلغاء تلقائي: تجاوز {pending_hours} ساعة بدون تأكيد',
                        is_auto=True
                    )
                    cancelled_count += 1
                    self.stdout.write(self.style.SUCCESS('    cancelled'))
                except OrderTransitionError as e:
                    self.stdout.write(self.style.ERROR(f'    error: {e}'))

        # ── 2. طلبات بوابة دفع لم تُكتمل بعد المدة ─────────────────────
        cutoff_payment = now - timedelta(hours=payment_hours)
        expired_payment = Order.objects.filter(
            status=Order.STATUS_PENDING,
            payment_method=Order.PAYMENT_GATEWAY,
            payment_status=Order.PAY_STATUS_PENDING,
            created_at__lt=cutoff_payment
        )

        self.stdout.write(f'\nExpired gateway pending payments ({payment_hours}h): {expired_payment.count()}')
        for order in expired_payment:
            age_hours = (now - order.created_at).total_seconds() / 3600
            self.stdout.write(
                f'  - Order #{order.id} | {order.customer_name} | age_hours={age_hours:.1f}'
            )
            if not dry_run:
                try:
                    cancel_order(
                        order,
                        reason=Order.CANCEL_PAYMENT_FAIL,
                        note=f'إلغاء تلقائي: لم يتم إكمال الدفع خلال {payment_hours} ساعة',
                        is_auto=True
                    )
                    cancelled_count += 1
                    self.stdout.write(self.style.SUCCESS('    cancelled'))
                except OrderTransitionError as e:
                    self.stdout.write(self.style.ERROR(f'    error: {e}'))

        # ── ملخص ────────────────────────────────────────────────────────
        if dry_run:
            total = expired_pending.count() + expired_payment.count()
            self.stdout.write(self.style.WARNING(
                f'\nDRY RUN summary: would cancel {total} orders.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nDone: cancelled {cancelled_count} orders and restored stock.'
            ))
