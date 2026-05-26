"""
حذف جميع الطلبات والمرتجعات والبيانات المرتبطة من قاعدة البيانات.
لا يمس حسابات المستخدمين (User) ولا الملفات الشخصية (UserProfile).
"""
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from store.models import Order, UserProfile


class Command(BaseCommand):
    help = (
        "حذف نهائي لجميع الطلبات والمرتجعات والشحن والبوالص والمحاولات المرتبطة. "
        "يُبقي المستخدمين وملفاتهم الشخصية. استخدم --dry-run للمعاينة فقط."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="تأكيد التنفيذ (إلزامي ما لم يُستخدم --dry-run).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="عرض الأعداد فقط دون حذف أي شيء.",
        )

    def handle(self, *args, **options):
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except (OSError, ValueError, AttributeError):
                pass

        dry_run = options["dry_run"]
        yes = options["yes"]

        user_count = get_user_model().objects.count()
        profile_count = UserProfile.objects.count()

        order_qs = Order.objects.all()
        n_orders = order_qs.count()

        if dry_run:
            self._print_counts_preview()
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"[معاينة] طلبات للحذف: {n_orders} | مستخدمون (يُبقون): {user_count} | ملفات شخصية (تُبقى): {profile_count}"
                )
            )
            self.stdout.write(
                "للتنفيذ الفعلي شغّل: python manage.py purge_orders --yes"
            )
            return

        if not yes:
            self.stdout.write(
                self.style.ERROR(
                    "تم الإلغاء: هذا الحذف لا يُرجع. أضف --yes للتنفيذ، أو --dry-run لعرض الأعداد."
                )
            )
            return

        self._print_counts_preview()

        with transaction.atomic():
            # حذف الطلب يزيل تلقائياً (CASCADE) كل ما يتبعه:
            # OrderItem، OrderStatusHistory، PaymentAttempt، Shipment (+ DeliveryOTP)،
            # LabelCode، ShippingWaybill، Return (+ ReturnItem، ReturnStatusHistory)، إلخ.
            deleted = order_qs.delete()

        # deleted = (عدد_إجمالي، {اسم_النموذج: عدد})
        total = deleted[0] if deleted else 0
        per_model = deleted[1] if len(deleted) > 1 else {}

        self.stdout.write(self.style.SUCCESS(f"تم الحذف. إجمالي السجلات المحذوفة: {total}"))
        if per_model:
            self.stdout.write("تفصيل حسب النموذج:")
            for label, cnt in sorted(per_model.items(), key=lambda x: x[0]):
                self.stdout.write(f"  - {label}: {cnt}")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"ما زال في النظام: {get_user_model().objects.count()} مستخدم، "
                f"{UserProfile.objects.count()} ملف شخصي."
            )
        )

    def _print_counts_preview(self):
        from store.models import (
            DeliveryOTP,
            LabelCode,
            Order,
            OrderItem,
            OrderStatusHistory,
            PaymentAttempt,
            Return,
            ReturnItem,
            ReturnStatusHistory,
            Shipment,
            ShippingWaybill,
        )

        self.stdout.write("أعداد قبل الحذف:")
        rows = [
            ("Order (طلب)", Order.objects.count()),
            ("OrderItem", OrderItem.objects.count()),
            ("OrderStatusHistory", OrderStatusHistory.objects.count()),
            ("PaymentAttempt", PaymentAttempt.objects.count()),
            ("Shipment", Shipment.objects.count()),
            ("DeliveryOTP", DeliveryOTP.objects.count()),
            ("LabelCode", LabelCode.objects.count()),
            ("ShippingWaybill", ShippingWaybill.objects.count()),
            ("Return (مرتجع)", Return.objects.count()),
            ("ReturnItem", ReturnItem.objects.count()),
            ("ReturnStatusHistory", ReturnStatusHistory.objects.count()),
        ]
        for name, c in rows:
            self.stdout.write(f"  - {name}: {c}")
