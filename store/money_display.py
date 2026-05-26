"""تنسيق عرض المبالغ بالريال في الواجهة (بدون أصفار عشرية زائدة من float/Decimal)."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def format_sar_amount(value) -> str:
    """
    يعرض المبلغ بحدّ أقصى رقمان عشريان، بدون سلسلة أصفار طويلة.
    الحسابات تبقى دقيقة في الـ ORM؛ هذا للعرض فقط.
    """
    if value is None:
        return '0'
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return '0'
    d = d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    s = format(d, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s if s else '0'
