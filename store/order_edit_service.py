"""خدمة تعديل بنود الطلب مع تطبيق فروقات المخزون (Delta) بشكل آمن."""

import json
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from .discount_engine import price_cart
from .models import InventoryMovement, Order, OrderItem, Product, ProductGalleryImage, ProductVariant


def _line_key(product_id, variant_id, gallery_id):
    return (int(product_id), int(variant_id or 0), int(gallery_id or 0))


def _build_cart_items_for_pricing(lines):
    cart_items = []
    for ln in lines:
        product = ln["product"]
        variant = ln.get("variant")
        selected_gallery_image = ln.get("selected_gallery_image")
        qty = int(ln["quantity"])
        if qty <= 0:
            continue
        base_price = (
            variant.effective_price if variant else (
                selected_gallery_image.effective_price if selected_gallery_image else product.price
            )
        )
        cart_items.append(
            {
                "product": product,
                "variant": variant,
                "selected_gallery_image": selected_gallery_image,
                "quantity": qty,
                "price": str(base_price),
                "name": product.name_ar,
            }
        )
    return cart_items


def preview_order_edit(*, order: Order, edited_lines: list[dict], include_line_details: bool = False):
    """حساب قبل/بعد للتعديل بدون تطبيقه فعلياً على الطلب أو المخزون."""
    cleaned_lines = []
    for ln in edited_lines:
        product = ln["product"]
        variant = ln.get("variant")
        selected_gallery_image = ln.get("selected_gallery_image")
        qty = int(ln["quantity"] or 0)
        if qty <= 0:
            continue
        cleaned_lines.append(
            {
                "product": product,
                "variant": variant,
                "selected_gallery_image": selected_gallery_image,
                "quantity": qty,
            }
        )
    if not cleaned_lines:
        raise ValueError("يجب أن يحتوي الطلب على منتج واحد على الأقل بعد التعديل.")

    cart_items = _build_cart_items_for_pricing(cleaned_lines)
    pricing = price_cart(
        cart_items,
        user=order.user if order.user_id else None,
        guest_phone=(order.customer_phone or None),
        coupon_code=None,
    )
    old_total = Decimal(str(order.total or 0))
    new_total = Decimal(str(pricing["final_subtotal"] or 0)) + Decimal(str(order.delivery_fee or 0))
    delta = new_total - old_total
    payload = {
        "old_total": old_total,
        "new_total": new_total,
        "delta": delta,
        "delta_abs": abs(delta),
        "direction": "up" if delta > 0 else ("down" if delta < 0 else "same"),
    }
    if include_line_details:
        payload["line_details"] = pricing["lines"]
    return payload


@transaction.atomic
def apply_order_edit(*, order: Order, edited_lines: list[dict], actor, edit_log_lines: list[dict] | None = None):
    """
    edited_lines: list of dicts
      - product (required Product)
      - quantity (required int > 0)
      - variant (optional ProductVariant)
      - selected_gallery_image (optional ProductGalleryImage)
    """
    if order.status in [Order.STATUS_DELIVERED, Order.STATUS_CANCELLED]:
        raise ValueError("لا يمكن تعديل الطلب بعد اكتماله أو إلغائه.")

    locked_order = Order.objects.select_for_update().get(pk=order.pk)
    existing_items = list(
        OrderItem.objects.select_for_update()
        .filter(order=locked_order)
        .select_related("product", "variant", "selected_gallery_image")
    )
    if not existing_items:
        raise ValueError("لا توجد بنود حالية للطلب لتعديلها.")

    old_by_key = defaultdict(int)
    old_product_totals = defaultdict(int)
    affected_product_ids = set()
    affected_variant_ids = set()
    affected_gallery_ids = set()

    for it in existing_items:
        k = _line_key(it.product_id, it.variant_id, it.selected_gallery_image_id)
        old_by_key[k] += int(it.quantity or 0)
        old_product_totals[it.product_id] += int(it.quantity or 0)
        affected_product_ids.add(it.product_id)
        if it.variant_id:
            affected_variant_ids.add(it.variant_id)
        if it.selected_gallery_image_id:
            affected_gallery_ids.add(it.selected_gallery_image_id)

    new_by_key = defaultdict(int)
    new_product_totals = defaultdict(int)
    cleaned_lines = []
    for ln in edited_lines:
        product = ln["product"]
        variant = ln.get("variant")
        selected_gallery_image = ln.get("selected_gallery_image")
        qty = int(ln["quantity"] or 0)
        if qty <= 0:
            continue
        if variant and variant.product_id != product.id:
            raise ValueError("النسخة المختارة لا تتبع المنتج.")
        if selected_gallery_image and selected_gallery_image.product_id != product.id:
            raise ValueError("الصورة المختارة لا تتبع المنتج.")
        key = _line_key(product.id, variant.id if variant else None, selected_gallery_image.id if selected_gallery_image else None)
        new_by_key[key] += qty
        new_product_totals[product.id] += qty
        affected_product_ids.add(product.id)
        if variant:
            affected_variant_ids.add(variant.id)
        if selected_gallery_image:
            affected_gallery_ids.add(selected_gallery_image.id)
        cleaned_lines.append(
            {
                "product": product,
                "variant": variant,
                "selected_gallery_image": selected_gallery_image,
                "quantity": qty,
            }
        )

    if not cleaned_lines:
        raise ValueError("يجب أن يحتوي الطلب على منتج واحد على الأقل بعد التعديل.")

    locked_products = {
        p.id: p
        for p in Product.objects.select_for_update().filter(id__in=affected_product_ids)
    }
    locked_variants = {
        v.id: v
        for v in ProductVariant.objects.select_for_update().filter(id__in=affected_variant_ids)
    }
    locked_gallery = {
        g.id: g
        for g in ProductGalleryImage.objects.select_for_update().filter(id__in=affected_gallery_ids)
    }

    # تحقق توافر المخزون للخصومات المطلوبة
    all_keys = set(old_by_key.keys()) | set(new_by_key.keys())
    for key in all_keys:
        product_id, variant_id, gallery_id = key
        old_qty = old_by_key.get(key, 0)
        new_qty = new_by_key.get(key, 0)
        delta_stock = old_qty - new_qty  # >0 restore, <0 deduct
        if delta_stock >= 0:
            continue
        need = abs(delta_stock)
        if variant_id:
            v = locked_variants.get(variant_id)
            if not v or int(v.stock_quantity or 0) < need:
                raise ValueError("لا يوجد مخزون كافٍ للنسخة المطلوبة.")
        elif gallery_id:
            g = locked_gallery.get(gallery_id)
            if not g or int(g.stock_quantity or 0) < need:
                raise ValueError("لا يوجد مخزون كافٍ للصورة/الخيار المطلوب.")
        else:
            p = locked_products.get(product_id)
            if not p or int(p.stock or 0) < need:
                raise ValueError("لا يوجد مخزون كافٍ للمنتج المطلوب.")

    # تطبيق فروقات المخزون على المستوى التفصيلي
    for key in all_keys:
        product_id, variant_id, gallery_id = key
        old_qty = old_by_key.get(key, 0)
        new_qty = new_by_key.get(key, 0)
        delta_stock = old_qty - new_qty
        if delta_stock == 0:
            continue
        if variant_id:
            v = locked_variants[variant_id]
            v.stock_quantity = int(v.stock_quantity or 0) + delta_stock
            if v.stock_quantity < 0:
                raise ValueError("مخزون النسخة أصبح سالباً بشكل غير متوقع.")
            v.save(update_fields=["stock_quantity", "updated_at"])
            InventoryMovement.objects.create(
                variant=v,
                movement_type=InventoryMovement.MOVE_CANCEL_RESTORE if delta_stock > 0 else InventoryMovement.MOVE_SALE,
                quantity=abs(int(delta_stock)),
                reference_type="order_edit",
                reference_id=locked_order.id,
                note="تعديل بنود الطلب",
                created_by=actor,
            )
        elif gallery_id:
            g = locked_gallery[gallery_id]
            g.stock_quantity = int(g.stock_quantity or 0) + delta_stock
            if g.stock_quantity < 0:
                raise ValueError("مخزون خيار الصورة أصبح سالباً بشكل غير متوقع.")
            g.save(update_fields=["stock_quantity"])

    # تطبيق فروقات المخزون على مستوى product.stock
    for pid in set(old_product_totals.keys()) | set(new_product_totals.keys()):
        p = locked_products[pid]
        delta = int(old_product_totals.get(pid, 0)) - int(new_product_totals.get(pid, 0))
        if delta == 0:
            continue
        p.stock = int(p.stock or 0) + delta
        if p.stock < 0:
            raise ValueError("مخزون المنتج أصبح سالباً بشكل غير متوقع.")
        p.save(update_fields=["stock", "updated_at"])

    # إعادة التسعير
    cart_items = _build_cart_items_for_pricing(cleaned_lines)
    pricing = price_cart(
        cart_items,
        user=locked_order.user if locked_order.user_id else None,
        guest_phone=(locked_order.customer_phone or None),
        coupon_code=None,
    )
    line_pricing = pricing["lines"]

    # إعادة بناء البنود
    OrderItem.objects.filter(order=locked_order).delete()
    for idx, ln in enumerate(cleaned_lines):
        product = locked_products[ln["product"].id]
        variant = locked_variants.get(ln["variant"].id) if ln.get("variant") else None
        selected_gallery_image = locked_gallery.get(ln["selected_gallery_image"].id) if ln.get("selected_gallery_image") else None
        quantity = int(ln["quantity"])
        unit_final = Decimal(str(line_pricing[idx]["unit_price_final"]))
        snap = OrderItem.build_snapshots(
            product,
            variant,
            selected_gallery_image if (not variant and selected_gallery_image) else None,
            image_url='',
        )
        OrderItem.objects.create(
            order=locked_order,
            product=product,
            variant=variant,
            selected_gallery_image=selected_gallery_image if (not variant and selected_gallery_image) else None,
            quantity=quantity,
            price=unit_final,
            **snap,
        )

    from .models import OrderStatusHistory

    note_lines = ["تعديل شامل لبنود الطلب + إعادة تسعير + تسوية مخزون (Delta)."]
    if edit_log_lines:
        note_lines.append("تفاصيل العمليات:")
        for idx, row in enumerate(edit_log_lines, start=1):
            ctype = row.get("change_type", "")
            if ctype == "remove":
                action_label = "حذف"
            elif ctype == "replace":
                action_label = "استبدال"
            else:
                action_label = "تعديل كمية"
            note_lines.append(
                (
                    f"{idx}) {action_label} | "
                    f"قبل: {row.get('before_name', '-')}"
                    f" ({row.get('before_variant', '-')}) x{row.get('before_qty', 0)} | "
                    f"بعد: {row.get('after_name', '-')}"
                    f" ({row.get('after_variant', '-')}) x{row.get('after_qty', 0)}"
                )
            )

    json_marker = "ORDER_EDIT_LOG_JSON::"
    note = "\n".join(note_lines)
    if edit_log_lines:
        note = f"{note}\n{json_marker}{json.dumps(edit_log_lines, ensure_ascii=False)}"

    OrderStatusHistory.objects.create(
        order=locked_order,
        old_status=locked_order.status,
        new_status=locked_order.status,
        old_payment_status=locked_order.payment_status,
        new_payment_status=locked_order.payment_status,
        changed_by=actor,
        is_automatic=False,
        note=note,
    )

    return locked_order

