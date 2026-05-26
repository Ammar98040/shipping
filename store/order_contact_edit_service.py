"""
تعديل بيانات التوصيل/الاتصال للطلب عبر مساعد الدردشة.
يسمح فقط بمراحل مبكرة من سير التنفيذ (قبل «جاهز للشحن»).
"""

from __future__ import annotations

from django.db import transaction

from .models import Order, OrderStatusHistory

# نفس فكرة «قابلية الإلغاء»: قبل تجهيز الشحن
EDITABLE_STATUSES: frozenset[str] = frozenset(
    {
        Order.STATUS_PENDING,
        Order.STATUS_CONFIRMED,
        Order.STATUS_PROCESSING,
    }
)


def can_edit_contact_info(order: Order) -> tuple[bool, str | None]:
    if order.status not in EDITABLE_STATUSES:
        return (
            False,
            "تعديل بيانات التوصيل غير متاحة لهذا الطلب لأن الطلب دخل مرحلة التجهيز/الشحن أو اكتمل. "
            "سنحوّلك لممثّل خدمة العملاء لمساعدتك حسب الحالة.",
        )
    return True, None


def _log_contact_change(
    order: Order,
    *,
    note: str,
) -> None:
    OrderStatusHistory.objects.create(
        order=order,
        old_status=order.status,
        new_status=order.status,
        old_payment_status=order.payment_status,
        new_payment_status=order.payment_status,
        changed_by=None,
        is_automatic=True,
        note=note,
    )


@transaction.atomic
def apply_customer_name(*, order: Order, new_name: str) -> None:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("الاسم فارغ.")
    if len(new_name) > 200:
        raise ValueError("الاسم أطول من المسموح.")
    old = (order.customer_name or "").strip()
    order.customer_name = new_name
    order.save(update_fields=["customer_name", "updated_at"])
    _log_contact_change(
        order,
        note=f"تعديل تلقائي (دردشة): الاسم. قبل: {old!r} → بعد: {new_name!r}.",
    )


@transaction.atomic
def apply_customer_phone(*, order: Order, new_phone: str) -> None:
    new_phone = (new_phone or "").strip()
    if not new_phone:
        raise ValueError("رقم الجوال فارغ.")
    if len(new_phone) > 20:
        raise ValueError("رقم الجوال أطول من المسموح.")
    old = (order.customer_phone or "").strip()
    order.customer_phone = new_phone
    order.save(update_fields=["customer_phone", "updated_at"])
    _log_contact_change(
        order,
        note=f"تعديل تلقائي (دردشة): الجوال. قبل: {old!r} → بعد: {new_phone!r}.",
    )


def build_address_text(parts: dict[str, str]) -> str:
    """تجميع العنوان من حقول منفصلة إلى نص واحد (حقل order.address)."""
    lines: list[str] = []
    labels = {
        "country": "البلد",
        "city": "المدينة",
        "district": "الحي/المنطقة",
        "street": "الشارع",
        "building": "المبنى/الشقة",
        "postal": "الرمز البريدي",
        "notes": "ملاحظات",
    }
    for key in ("country", "city", "district", "street", "building", "postal", "notes"):
        val = (parts.get(key) or "").strip()
        if not val or val in {"-", "—"}:
            continue
        lines.append(f"{labels.get(key, key)}: {val}")
    if not lines:
        raise ValueError("العنوان فارغ.")
    return "\n".join(lines)


@transaction.atomic
def apply_delivery_address(*, order: Order, address_text: str) -> None:
    address_text = (address_text or "").strip()
    if not address_text:
        raise ValueError("العنوان فارغ.")
    old = (order.address or "").strip()
    order.address = address_text
    order.save(update_fields=["address", "updated_at"])
    _log_contact_change(
        order,
        note="تعديل تلقائي (دردشة): العنوان.\nقبل:\n" + old + "\nبعد:\n" + address_text,
    )
