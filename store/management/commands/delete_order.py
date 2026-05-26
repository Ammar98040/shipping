"""حذف طلب واحد بالمعرّف (مع CASCADE للبنود والمرتبطات)."""

import sys

from django.core.management.base import BaseCommand
from django.db import transaction

from store.models import Order


class Command(BaseCommand):
    help = (
        "حذف طلب واحد برقم الـ pk. يُزال من إحصاء الإيرادات تلقائياً "
        "(الإيرادات تُحسب من بنود الطلبات «تم التوصيل» فقط). أضف --yes للتنفيذ."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--order-id",
            type=int,
            required=True,
            dest="order_id",
            help="رقم الطلب (Order.pk)",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="تأكيد الحذف النهائي",
        )

    def handle(self, *args, **options):
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except (OSError, ValueError, AttributeError):
                pass

        pk = options["order_id"]
        if not options["yes"]:
            self.stdout.write(
                self.style.ERROR(
                    "Cancelled: pass --yes to confirm. "
                    f"Example: python manage.py delete_order --order-id {pk} --yes"
                )
            )
            return

        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"No order with id={pk}."))
            return

        with transaction.atomic():
            deleted = order.delete()

        n = deleted[0]
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted order #{pk} and related rows (total records removed: {n})."
            )
        )
