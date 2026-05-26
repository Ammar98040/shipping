"""
محرك خصومات تجريبي:
- خصومات المنتجات عبر عروض (Promotion): أفضل خصم بالقيمة على مستوى سطر السلة.
- خصومات الطلب عبر كوبون (Coupon): يخصم من الإجمالي بعد خصم عروض المنتجات.
- خصم Fixed يكون على "إجمالي السطر مرة واحدة" (Option 2).
- سياسة الكوبون: مرة واحدة لكل عميل (مسجل = user، ضيف = guest_phone من checkout).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db.models import Prefetch
from django.utils import timezone

from .models import Coupon, CouponRedemption, Promotion

CURRENCY_Q = Decimal("0.01")


def quantize_money(v: Decimal) -> Decimal:
    return v.quantize(CURRENCY_Q, rounding=ROUND_HALF_UP)


def normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D+", "", phone)
    # لو كان مكتوب بصيغة 966xxxxxxxx نزيل البادئة
    if digits.startswith("966") and len(digits) > 9:
        digits = digits[3:]
    # لو بدأ بـ 0 (مثل 05...) نتركه كما هو بعد إزالة غير الرقمية
    return digits


def _is_promotion_active(promo: Promotion) -> bool:
    now = timezone.now()
    if not promo.is_active:
        return False
    if promo.start_at and now < promo.start_at:
        return False
    if promo.end_at and now > promo.end_at:
        return False
    return True


def _compute_line_discount_amount(
    promo: Promotion,
    *,
    base_unit_price: Decimal,
    quantity: int,
) -> Decimal:
    """
    خصم Fixed محسوب على إجمالي السطر مرة واحدة:
      discount_fixed_line = min(promo.discount_value, base_unit_price * quantity)
    """
    if quantity < int(promo.min_quantity or 1):
        return Decimal("0")

    base_line_total = base_unit_price * Decimal(quantity)
    if base_line_total <= 0:
        return Decimal("0")

    if promo.discount_type == Promotion.DISCOUNT_PERCENT:
        discount = base_line_total * (promo.discount_value / Decimal("100"))
    elif promo.discount_type == Promotion.DISCOUNT_FIXED:
        discount = Decimal(promo.discount_value or 0)
    else:
        discount = Decimal("0")

    if discount <= 0:
        return Decimal("0")

    if discount > base_line_total:
        discount = base_line_total

    return quantize_money(discount)


def _promotion_applies_to_line(
    promo: Promotion,
    *,
    product,
    variant_id: int | None,
) -> bool:
    scope = (promo.scope or Promotion.SCOPE_ALL).strip() or Promotion.SCOPE_ALL
    if scope == Promotion.SCOPE_ALL:
        return True

    if scope == Promotion.SCOPE_COMPARTMENTS:
        if not promo.compartments.exists():
            return True
        return promo.compartments.filter(pk=product.category.shelf.compartment_id).exists()

    if scope == Promotion.SCOPE_SHELVES:
        if not promo.shelves.exists():
            return True
        return promo.shelves.filter(pk=product.category.shelf_id).exists()

    if scope == Promotion.SCOPE_CATEGORIES:
        if not promo.categories.exists():
            return True
        return promo.categories.filter(pk=product.category_id).exists()

    if scope == Promotion.SCOPE_PRODUCTS:
        if not promo.products.exists():
            return True
        return promo.products.filter(pk=product.id).exists()

    if scope == Promotion.SCOPE_VARIANTS:
        if not variant_id:
            return False
        if not promo.variants.exists():
            return True
        return promo.variants.filter(pk=variant_id).exists()

    return False


def price_cart(
    cart_items: list[dict[str, Any]],
    *,
    user=None,
    guest_phone: str | None = None,
    coupon_code: str | None = None,
) -> dict[str, Any]:
    """
    returns:
      - lines: list of dicts with pricing per line
      - subtotal_after_product_offers
      - product_discount_total
      - applied_coupon (optional)
      - coupon_discount_total
      - final_subtotal
    """
    now = timezone.now()

    promotions = list(
        Promotion.objects.filter(is_active=True)
        .prefetch_related(
            Prefetch("products"),
            Prefetch("variants"),
        )
    )
    promotions = [p for p in promotions if _is_promotion_active(p)]

    # 1) تطبيق عروض المنتجات (أفضل خصم بالقيمة على مستوى كل سطر)
    lines = []
    subtotal_after_offers = Decimal("0")
    product_discount_total = Decimal("0")

    for item in cart_items:
        product = item["product"]
        variant = item.get("variant")
        quantity = int(item.get("quantity") or 0)
        base_unit_price = Decimal(str(item.get("price") or 0))

        best_discount = Decimal("0")
        best_promo_id = None

        for promo in promotions:
            if not _promotion_applies_to_line(promo, product=product, variant_id=(int(variant.id) if variant else None)):
                continue
            discount_amount = _compute_line_discount_amount(promo, base_unit_price=base_unit_price, quantity=quantity)
            if discount_amount > best_discount:
                best_discount = discount_amount
                best_promo_id = promo.id

        base_line_total = base_unit_price * Decimal(quantity)
        line_total_after_offer = base_line_total - best_discount
        if line_total_after_offer < 0:
            line_total_after_offer = Decimal("0")

        # وحدة بعد الخصم
        unit_after_offer = quantize_money(line_total_after_offer / Decimal(max(quantity, 1)))

        subtotal_after_offers += quantize_money(line_total_after_offer)
        product_discount_total += quantize_money(best_discount)

        lines.append(
            {
                "product_id": int(product.id),
                "variant_id": int(variant.id) if variant else None,
                "quantity": quantity,
                "base_unit_price": quantize_money(base_unit_price),
                "unit_price_after_offer": unit_after_offer,
                "offer_discount_allocated": quantize_money(best_discount),
                "line_total_after_offer": quantize_money(unit_after_offer * Decimal(quantity)),
                "best_promo_id": best_promo_id,
            }
        )

    subtotal_after_offers = quantize_money(subtotal_after_offers)
    product_discount_total = quantize_money(product_discount_total)

    # 2) كوبون على الإجمالي بعد خصم العروض
    coupon_discount_total = Decimal("0")
    coupon = None
    applied_coupon_code = None

    guest_phone_norm = normalize_phone(guest_phone) if guest_phone else ""

    if coupon_code:
        code = (coupon_code or "").strip()
        if code:
            coupon = None
            # كوبونات الخصم للحسابات المسجّلة فقط (لا ضيوف بدون حساب)
            if user and getattr(user, "is_authenticated", False):
                coupon = Coupon.objects.filter(code__iexact=code, is_active=True).first()
                if coupon and not _coupon_is_active_now(coupon, now=now):
                    coupon = None

                if coupon:
                    # حد الاستخدام الإجمالي (0 = بدون حد أعلى)
                    used_count = CouponRedemption.objects.filter(coupon=coupon).count()
                    max_uses = int(coupon.max_uses_total or 0)
                    if max_uses and used_count >= max_uses:
                        if coupon.is_active:
                            Coupon.objects.filter(pk=coupon.pk, is_active=True).update(is_active=False)
                            coupon.is_active = False
                        coupon = None
                    elif CouponRedemption.objects.filter(coupon=coupon, user=user).exists():
                        coupon = None

            if coupon:
                applied_coupon_code = coupon.code
                if coupon.discount_type == Coupon.DISCOUNT_PERCENT:
                    coupon_discount_total = subtotal_after_offers * (coupon.discount_value / Decimal("100"))
                else:
                    coupon_discount_total = Decimal(coupon.discount_value or 0)

                if coupon_discount_total > subtotal_after_offers:
                    coupon_discount_total = subtotal_after_offers
                if coupon_discount_total < 0:
                    coupon_discount_total = Decimal("0")
                coupon_discount_total = quantize_money(coupon_discount_total)
            else:
                coupon_discount_total = Decimal("0")

    # 3) توزيع خصم الكوبون على الأسطر تناسبيًا ليكون سعر OrderItem مطابق (المرجّعات تعتمد على سعر السطر)
    final_subtotal = subtotal_after_offers - coupon_discount_total
    final_subtotal = quantize_money(max(final_subtotal, Decimal("0")))

    if coupon_discount_total > 0 and subtotal_after_offers > 0:
        allocated_sum = Decimal("0")
        last_idx = len(lines) - 1
        for idx, line in enumerate(lines):
            line_total_after_offer = line["line_total_after_offer"]
            if idx == last_idx:
                allocated = coupon_discount_total - allocated_sum
            else:
                share = (line_total_after_offer / subtotal_after_offers) if subtotal_after_offers > 0 else Decimal("0")
                allocated = quantize_money(coupon_discount_total * share)
                allocated = min(allocated, line_total_after_offer)

            allocated = quantize_money(max(allocated, Decimal("0")))
            allocated_sum += allocated

            final_line_total = line_total_after_offer - allocated
            if final_line_total < 0:
                final_line_total = Decimal("0")

            quantity = int(line["quantity"] or 0)
            unit_final = quantize_money(final_line_total / Decimal(max(quantity, 1)))

            line["coupon_discount_allocated"] = allocated
            line["unit_price_final"] = unit_final
            line["line_total_final"] = quantize_money(unit_final * Decimal(quantity))
    else:
        for line in lines:
            line["coupon_discount_allocated"] = Decimal("0")
            line["unit_price_final"] = line["unit_price_after_offer"]
            line["line_total_final"] = line["line_total_after_offer"]

    return {
        "lines": lines,
        "subtotal_after_product_offers": subtotal_after_offers,
        "product_discount_total": product_discount_total,
        "coupon_discount_total": quantize_money(coupon_discount_total),
        "applied_coupon_code": applied_coupon_code,
        "final_subtotal": final_subtotal,
        "coupon_obj": coupon,
        "guest_phone_norm": guest_phone_norm,
    }


def _coupon_is_active_now(coupon: Coupon, *, now) -> bool:
    if not coupon.is_active:
        return False
    if coupon.start_at and now < coupon.start_at:
        return False
    if coupon.end_at and now > coupon.end_at:
        return False
    return True


def preview_best_unit_price_for_product(
    *,
    product,
    variant_id: int | None,
    base_unit_price: Decimal,
    quantity: int = 1,
) -> dict[str, Any]:
    """
    للعرض في بطاقات المنتجات/السلة:
    - يعيد أفضل خصم بالقيمة (Offers فقط) بدون كوبون.
    - quantity افتراضي 1 للعرض في القوائم.
    """
    promotions = list(
        Promotion.objects.filter(is_active=True).prefetch_related(
            Prefetch("products"),
            Prefetch("variants"),
        )
    )
    promotions = [p for p in promotions if _is_promotion_active(p)]

    best_discount = Decimal("0")
    best_promo_id = None
    best_promo = None
    for promo in promotions:
        if not _promotion_applies_to_line(promo, product=product, variant_id=variant_id):
            continue
        discount_amount = _compute_line_discount_amount(promo, base_unit_price=base_unit_price, quantity=quantity)
        if discount_amount > best_discount:
            best_discount = discount_amount
            best_promo_id = promo.id
            best_promo = promo

    base_line_total = base_unit_price * Decimal(max(1, quantity))
    final_line_total = base_line_total - best_discount
    if final_line_total < 0:
        final_line_total = Decimal("0")
    unit_final = quantize_money(final_line_total / Decimal(max(1, quantity)))

    discount_label = None
    if best_promo and best_discount > 0:
        if best_promo.discount_type == Promotion.DISCOUNT_PERCENT:
            # quantity=1 للعرض في القوائم، لذا القيمة هنا تعكس خصم الوحدة.
            discount_label = f"خصم {best_promo.discount_value}%"
        else:
            discount_label = f"خصم {best_discount} ر.س"

    return {
        "best_promo_id": best_promo_id,
        "discount_amount": quantize_money(best_discount),
        "unit_price_final": unit_final,
        "discount_label": discount_label,
    }

