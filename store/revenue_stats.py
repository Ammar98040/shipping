"""
إحصاءات الإيرادات: تُحسب من طلبات حالتها «تم التوصيل» فقط، حسب طريقة الدفع،
ثم يُخصم مجموع المرتجعات المعتمدة/المكتملة للحصول على الصافي.
"""

from decimal import Decimal

from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce

from .models import Order, OrderItem, Return
from .money_display import format_sar_amount

_DEC = DecimalField(max_digits=14, decimal_places=2)
_ZERO = Value(0, output_field=_DEC)


def _sum_line_items(qs):
    return qs.aggregate(
        t=Coalesce(
            Sum(F('price') * F('quantity'), output_field=_DEC),
            _ZERO,
        )
    )['t']


def get_revenue_stats_formatted():
    """
    يعيد قيماً جاهزة للعرض (نصوص مُنسَّقة بالريال).

    - revenue_gateway: طلبات مُسلَّمة دُفعت بالبطاقة (فيزا/مدى).
    - revenue_cash: طلبات مُسلَّمة بالدفع عند الاستلام.
    - refunds_total: مجموع مبالغ المرتجعات (معتمد + مكتمل).
    - revenue_net: (فيزا + كاش) − مرتجعات.
    - total_revenue: نفس revenue_net (للتوافق مع الكود القديم).
    """
    delivered_items = OrderItem.objects.filter(order__status=Order.STATUS_DELIVERED)

    gw_raw = _sum_line_items(
        delivered_items.filter(order__payment_method=Order.PAYMENT_GATEWAY)
    )
    cash_raw = _sum_line_items(
        delivered_items.filter(order__payment_method=Order.PAYMENT_CASH)
    )
    refunds_raw = Return.objects.filter(
        status__in=[Return.STATUS_APPROVED, Return.STATUS_COMPLETED]
    ).aggregate(Sum('refund_amount'))['refund_amount__sum'] or 0

    gw = Decimal(str(gw_raw or 0))
    cash = Decimal(str(cash_raw or 0))
    ref = Decimal(str(refunds_raw or 0))
    gross = gw + cash
    net = gross - ref

    return {
        'revenue_gateway': format_sar_amount(gw),
        'revenue_cash': format_sar_amount(cash),
        'revenue_gross': format_sar_amount(gross),
        'refunds_total': format_sar_amount(ref),
        'revenue_net': format_sar_amount(net),
        'total_revenue': format_sar_amount(net),
    }
