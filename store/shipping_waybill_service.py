"""
تسجيل بوليصة الشحن تلقائياً من كود الملصق (LabelCode) — بدون إدخال يدوي.
نفس المنطق يُستخدم عند طباعة البوليصة من المستودع وعند الاستعادة من لوحة الإدارة.
"""
from __future__ import annotations

import secrets

from django.utils import timezone
from django.utils.translation import gettext

from .models import LabelCode, ShippingWaybill


def get_or_create_label_for_order(order):
    """
    يضمن وجود LabelCode للطلب (نفس منطق صفحة طباعة البوليصة).
    يعيد (label, created_bool).
    """
    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None

    try:
        label = order.label_code
    except LabelCode.DoesNotExist:
        label = None

    if not label:
        while True:
            candidate = (
                secrets.token_urlsafe(9).replace('-', '').replace('_', '').upper()[:14]
            )
            if not LabelCode.objects.filter(code=candidate).exists():
                label = LabelCode.objects.create(
                    code=candidate, order=order, shipment=shipment
                )
                break
        return label, True

    if shipment and label.shipment_id != shipment.id:
        label.shipment = shipment
        label.save(update_fields=['shipment'])

    return label, False


def ensure_shipping_waybill_for_order(
    order, *, actor, source_line: str = ''
) -> tuple[ShippingWaybill, bool, LabelCode]:
    """
    ينشئ أو يحدّث بوليصة الشحن بقيم موحّدة من كود الملصق:
    - رقم البوليصة: DLBK-<CODE>
    - قيمة الباركود (نص المسح): DLBK:<CODE>
    - الكود الداخلي: نفس CODE

    source_line: سطر يُضاف إلى الملاحظات عند التحديث (سجل تدقيق).
    يعيد (ShippingWaybill, created, LabelCode).
    """
    label = get_or_create_label_for_order(order)[0]

    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None

    waybill_number = f'DLBK-{label.code}'
    barcode_value = f'DLBK:{label.code}'
    default_note = gettext('تم التسجيل تلقائياً عند طباعة/تجهيز البوليصة.')

    wb, created = ShippingWaybill.objects.get_or_create(
        order=order,
        defaults={
            'shipment': shipment,
            'waybill_number': waybill_number[:64],
            'barcode_value': barcode_value[:512],
            'linked_internal_code': label.code[:32],
            'notes': (source_line or default_note),
            'created_by': actor,
            'updated_by': actor,
        },
    )

    if not created:
        update_fields = [
            'shipment',
            'waybill_number',
            'barcode_value',
            'linked_internal_code',
            'updated_by',
            'updated_at',
        ]
        wb.shipment = shipment
        wb.waybill_number = waybill_number[:64]
        wb.barcode_value = barcode_value[:512]
        wb.linked_internal_code = label.code[:32]
        wb.updated_by = actor
        if source_line:
            prev = (wb.notes or '').strip()
            stamp = f'[{timezone.now().strftime("%Y-%m-%d %H:%M")}] {source_line}'
            if stamp not in prev and source_line not in prev:
                wb.notes = f'{prev}\n{stamp}'.strip() if prev else stamp
                update_fields.append('notes')
        wb.save(update_fields=update_fields)

    return wb, created, label
