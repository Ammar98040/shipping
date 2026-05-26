"""
خدمة مركزية لإدارة مخزون نسخ المنتجات (Variants).
"""
from django.db import transaction

from .models import InventoryMovement, Product, ProductVariant


def ensure_default_variant(product: Product) -> ProductVariant:
    """
    يضمن وجود نسخة افتراضية للمنتج الحالي.
    تستخدم للانتقال التدريجي من مخزون المنتج القديم إلى مخزون النسخ.
    """
    variant = product.variants.order_by('sort_order', 'id').first()
    if variant:
        return variant

    base_code = (product.sku or f"P{product.id}").strip() or f"P{product.id}"
    candidate = f"{base_code}-DEFAULT"
    idx = 2
    while ProductVariant.objects.filter(product=product, code=candidate).exists():
        candidate = f"{base_code}-DEFAULT-{idx}"
        idx += 1

    return ProductVariant.objects.create(
        product=product,
        code=candidate,
        title='النسخة الافتراضية',
        stock_quantity=product.stock or 0,
        price=product.price,
        sort_order=0,
        is_active=True,
    )


@transaction.atomic
def adjust_variant_stock(
    *,
    variant: ProductVariant,
    delta: int,
    movement_type: str,
    reference_type: str = '',
    reference_id: int | None = None,
    note: str = '',
    created_by=None,
):
    """
    تعديل مخزون نسخة المنتج مع تسجيل الحركة.
    delta موجب = إضافة، سالب = خصم.
    """
    if delta == 0:
        return

    current = ProductVariant.objects.select_for_update().get(pk=variant.pk)
    new_qty = (current.stock_quantity or 0) + int(delta)
    if new_qty < 0:
        raise ValueError('محاولة خصم مخزون أكبر من المتاح للنسخة.')

    ProductVariant.objects.filter(pk=current.pk).update(stock_quantity=new_qty)

    InventoryMovement.objects.create(
        variant=current,
        movement_type=movement_type,
        quantity=abs(int(delta)),
        reference_type=reference_type or '',
        reference_id=reference_id,
        note=note or '',
        created_by=created_by,
    )


def get_available_stock(product: Product, variant: ProductVariant | None = None) -> int:
    """قراءة المخزون المتاح؛ نسخة محددة أو إجمالي النسخ النشطة."""
    if variant is not None:
        return int(variant.stock_quantity or 0)
    variants = product.variants.filter(is_active=True)
    if variants.exists():
        return int(sum(v.stock_quantity for v in variants))
    return int(product.stock or 0)
