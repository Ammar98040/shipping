from django.core.management.base import BaseCommand
from django.db.models import Q

from store.models import ProductVariant


class Command(BaseCommand):
    help = "تنظيف النسخ الافتراضية القديمة غير المستخدمة (يدعم dry-run افتراضياً)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="تنفيذ الحذف فعلياً. بدون هذا الخيار سيتم عرض تقرير فقط (dry-run).",
        )
        parser.add_argument(
            "--product-id",
            type=int,
            default=None,
            help="حصر العملية على منتج واحد (اختياري).",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options.get("apply"))
        product_id = options.get("product_id")

        qs = ProductVariant.objects.select_related("product").filter(
            Q(title__in=["النسخة الافتراضية", "Default"])
            | Q(color_name__in=["النسخة الافتراضية", "Default"])
        )
        if product_id:
            qs = qs.filter(product_id=product_id)

        scanned = 0
        candidates = []
        protected = []

        for variant in qs.order_by("product_id", "id"):
            scanned += 1
            # أي نسخة ظاهرة للعميل لا تُعتبر Placeholder.
            if variant.is_distinct_customer_choice:
                continue
            in_use = (
                variant.order_items.exists()
                or variant.return_items.exists()
                or variant.cart_share_items.exists()
                or variant.movements.exists()
            )
            if in_use:
                protected.append(variant)
                continue
            candidates.append(variant)

        self.stdout.write(f"Scanned variants: {scanned}")
        self.stdout.write(f"Protected (in use): {len(protected)}")
        self.stdout.write(f"Deletable candidates: {len(candidates)}")

        for variant in candidates[:30]:
            self.stdout.write(
                f"- product={variant.product_id} sku={variant.product.sku or '-'} variant={variant.id} code={variant.code}"
            )
        if len(candidates) > 30:
            self.stdout.write(f"... and {len(candidates) - 30} more")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run only. Use --apply to delete candidates."))
            return

        deleted = 0
        for variant in candidates:
            variant.delete()
            deleted += 1
        self.stdout.write(self.style.SUCCESS(f"Deleted placeholder variants: {deleted}"))
