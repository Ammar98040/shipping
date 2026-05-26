"""
محرك انتقال حالات المرتجعات — Return State Engine
كل تغيير في حالة مرتجع يجب أن يمر من هنا.
يضمن:
  - صحة الانتقالات (لا تخطٍّ بين الحالات)
  - تسجيل سجل زمني لكل تغيير
  - إعادة المخزون تلقائياً عند الإتمام
  - تحديث حالة الاسترداد المالي تبعاً للإجراء
  - تحديث الطلب الأصلي (payment_status) عند الاسترداد
"""
from django.utils import timezone


class ReturnTransitionError(Exception):
    """خطأ عند محاولة انتقال غير مسموح في المرتجع"""
    pass


def _log_return_change(return_obj, old_status, new_status, actor, is_auto, note):
    """تسجيل تغيير الحالة في السجل الزمني"""
    from .models import ReturnStatusHistory
    ReturnStatusHistory.objects.create(
        return_request=return_obj,
        old_status=old_status or '',
        new_status=new_status,
        changed_by=actor,
        is_automatic=is_auto,
        note=note or '',
    )


def _restock_return_items(return_obj):
    """إعادة كميات المنتجات للمخزون"""
    for item in return_obj.items.select_related('product', 'variant').all():
        product = item.product
        if item.variant_id:
            variant = item.variant
            variant.stock_quantity = (variant.stock_quantity or 0) + item.quantity
            variant.save(update_fields=['stock_quantity', 'updated_at'])
        product.stock = (product.stock or 0) + item.quantity
        product.save(update_fields=['stock', 'updated_at'])


def advance_return(return_obj, new_status, actor=None, note='', is_auto=False):
    """
    ينقل المرتجع إلى حالة جديدة بعد التحقق من صحة الانتقال.

    return_obj : كائن Return
    new_status : الحالة المستهدفة (من Return.STATUS_*)
    actor      : المستخدم الذي أجرى التغيير (None = تلقائي)
    note       : ملاحظة اختيارية
    is_auto    : هل التغيير تلقائي؟
    """
    from .models import Order, Return
    from .order_engine import mark_payment

    allowed = return_obj.get_allowed_next_statuses()
    if new_status not in allowed:
        raise ReturnTransitionError(
            f"لا يمكن الانتقال من '{return_obj.get_status_display()}' "
            f"إلى '{dict(Return.STATUS_CHOICES).get(new_status, new_status)}'"
        )

    old_status = return_obj.status

    # ── تأثيرات جانبية حسب الانتقال ──────────────────────────────────

    if new_status == Return.STATUS_APPROVED:
        # الموافقة: احسب مبلغ الاسترداد إذا لم يكن محدداً
        if return_obj.refund_amount == 0:
            return_obj.refund_amount = sum(item.subtotal for item in return_obj.items.all())
        return_obj.refund_status = Return.REFUND_PENDING

    elif new_status == Return.STATUS_REJECTED:
        # الرفض: لا استرداد
        return_obj.refund_status = Return.REFUND_NOT_REQUIRED

    elif new_status == Return.STATUS_RECEIVED:
        # استُلم المنتج → أعد المخزون
        _restock_return_items(return_obj)
        return_obj.stock_status = Return.STOCK_RESTOCKED

    elif new_status == Return.STATUS_COMPLETED:
        # اكتمل → سجّل وقت الإكمال + حدّث الطلب الأصلي
        return_obj.completed_at = timezone.now()
        return_obj.refund_status = Return.REFUND_COMPLETED
        # حدّث payment_status للطلب الأصلي إذا كان مدفوعاً
        order = return_obj.order
        if order.payment_status == Order.PAY_STATUS_PAID:
            mark_payment(
                order,
                Order.PAY_STATUS_REFUNDED,
                actor=actor,
                note=f'استرداد مرتجع #{return_obj.id}',
                is_auto=True
            )

    # ── حفظ التغييرات ────────────────────────────────────────────────
    return_obj.status = new_status
    return_obj.save()

    _log_return_change(return_obj, old_status, new_status, actor, is_auto, note)

    return return_obj


def reject_return(return_obj, note='', actor=None):
    """رفض المرتجع مع ملاحظة"""
    from .models import Return
    if return_obj.status not in [Return.STATUS_REQUESTED, Return.STATUS_REVIEWING]:
        raise ReturnTransitionError(
            f"لا يمكن رفض مرتجع في حالة '{return_obj.get_status_display()}'"
        )
    return advance_return(return_obj, Return.STATUS_REJECTED, actor=actor, note=note)


def create_initial_return_history(return_obj, actor=None):
    """يُستدعى مرة واحدة عند إنشاء المرتجع"""
    _log_return_change(return_obj, '', return_obj.status, actor, True, 'تم إنشاء طلب المرتجع')


# ── تسميات بصرية ─────────────────────────────────────────────────────

RETURN_STATUS_ICONS = {
    'requested':  ('📝', '#f59e0b'),
    'reviewing':  ('🔍', '#3b82f6'),
    'approved':   ('✅', '#10b981'),
    'rejected':   ('❌', '#ef4444'),
    'received':   ('📦', '#8b5cf6'),
    'completed':  ('🎉', '#2c5f4f'),
}

REFUND_STATUS_ICONS = {
    'not_required': ('—',  '#94a3b8'),
    'pending':      ('⏳', '#f59e0b'),
    'completed':    ('✅', '#10b981'),
    'partial':      ('↩️',  '#8b5cf6'),
}

def build_return_timeline(return_obj):
    """
    يبني مساراً واحداً للعرض في واجهة العميل ولوحة الإدارة:
    حالات من السجل الزمني + موضع الحالية (نشط / منجز / قادم / متخطى / مرفوض نهائي).
    """
    from .models import Return, ReturnStatusHistory

    # استعلام مباشر (وليس prefetch فقط) لضمان صحة البيانات بعد refresh_from_db / JSON
    history = list(
        ReturnStatusHistory.objects.filter(return_request=return_obj)
        .select_related('changed_by')
        .order_by('created_at')
    )
    first_at = {}
    for h in history:
        if h.new_status and h.new_status not in first_at:
            first_at[h.new_status] = h.created_at
    if Return.STATUS_REQUESTED not in first_at:
        first_at[Return.STATUS_REQUESTED] = return_obj.created_at

    labels = dict(Return.STATUS_CHOICES)
    linear = [
        Return.STATUS_REQUESTED,
        Return.STATUS_REVIEWING,
        Return.STATUS_APPROVED,
        Return.STATUS_RECEIVED,
        Return.STATUS_COMPLETED,
    ]

    def _at_for(code):
        if code == Return.STATUS_COMPLETED and return_obj.completed_at:
            return return_obj.completed_at
        return first_at.get(code)

    def _step_dict(code, state):
        icon, color = RETURN_STATUS_ICONS.get(code, ('•', '#64748b'))
        return {
            'code': code,
            'label': labels.get(code, code),
            'icon': icon,
            'color': color,
            'state': state,
            'at': _at_for(code),
        }

    steps = []
    cur = return_obj.status

    if cur == Return.STATUS_REJECTED:
        old_before = Return.STATUS_REQUESTED
        for h in reversed(history):
            if h.new_status == Return.STATUS_REJECTED:
                old_before = (h.old_status or Return.STATUS_REQUESTED).strip() or Return.STATUS_REQUESTED
                break
        try:
            idx_old = linear.index(old_before)
        except ValueError:
            idx_old = 0
        for i, code in enumerate(linear):
            if i < idx_old:
                st = 'done'
            elif i == idx_old:
                st = 'done'
            else:
                st = 'skipped'
            steps.append(_step_dict(code, st))
        rej = _step_dict(Return.STATUS_REJECTED, 'rejected_terminal')
        rej['at'] = first_at.get(Return.STATUS_REJECTED)
        steps.append(rej)
    else:
        try:
            idx_cur = linear.index(cur)
        except ValueError:
            idx_cur = 0
        for i, code in enumerate(linear):
            if i < idx_cur:
                st = 'done'
            elif i == idx_cur:
                st = 'active'
            else:
                st = 'pending'
            steps.append(_step_dict(code, st))

    return {'steps': steps}


def render_return_timeline_html(return_obj):
    """HTML جاهز للحقن في استجابة JSON (لوحة الإدارة)."""
    from django.template.loader import render_to_string

    return render_to_string(
        'store/partials/return_timeline.html',
        {'return_timeline': build_return_timeline(return_obj)},
    )
