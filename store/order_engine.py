"""
محرك انتقال حالات الطلبات — Order State Engine
كل تغيير في حالة طلب يجب أن يمر من هنا.
يضمن:
  - صحة الانتقالات (لا يمكن الرجوع أو التخطي)
  - تسجيل سجل زمني لكل تغيير
  - تحديث المخزون تلقائياً عند الإلغاء
  - تحديث حالة الدفع تبعاً للإجراء
"""
from .notifications import notify_order_status


class OrderTransitionError(Exception):
    """خطأ عند محاولة انتقال غير مسموح"""
    pass


def _log_change(order, old_status, new_status, actor, is_auto, note,
                old_pay=None, new_pay=None):
    """تسجيل تغيير حالة في السجل الزمني"""
    from .models import OrderStatusHistory
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status or '',
        new_status=new_status,
        old_payment_status=old_pay or '',
        new_payment_status=new_pay or '',
        changed_by=actor,
        is_automatic=is_auto,
        note=note or '',
    )


def _restore_stock(order):
    """إعادة كميات المنتجات للمخزون عند إلغاء الطلب"""
    for item in order.items.select_related('product', 'variant').all():
        product = item.product
        if item.variant_id:
            variant = item.variant
            variant.stock_quantity = (variant.stock_quantity or 0) + item.quantity
            variant.save(update_fields=['stock_quantity', 'updated_at'])
        product.stock = (product.stock or 0) + item.quantity
        product.save(update_fields=['stock', 'updated_at'])


def advance_order(order, new_status, actor=None, note='', is_auto=False):
    """
    ينقل الطلب إلى حالة جديدة بعد التحقق من صحة الانتقال.

    order     : كائن Order
    new_status: الحالة المستهدفة (من Order.STATUS_*)
    actor     : المستخدم الذي أجرى التغيير (None = تلقائي)
    note      : ملاحظة اختيارية
    is_auto   : هل التغيير تلقائي؟
    """
    from .models import Order, Shipment

    allowed = order.get_allowed_next_statuses()
    if new_status not in allowed:
        raise OrderTransitionError(
            f"لا يمكن الانتقال من '{order.get_status_display()}' "
            f"إلى '{dict(Order.STATUS_CHOICES).get(new_status, new_status)}'"
        )

    old_status = order.status
    old_pay    = order.payment_status

    # ── تأثيرات جانبية حسب الانتقال ──────────────────────────────────
    new_pay = old_pay  # افتراضياً لا تتغير حالة الدفع

    if new_status == Order.STATUS_CANCELLED:
        # إلغاء → أعد المخزون
        _restore_stock(order)
        # بوابة الدفع:
        # - paid  -> refunded (محاكاة/مستقبلاً: يحتاج Refund)
        # - pending -> cancelled
        # - failed -> يبقى failed (لا تُحوّله إلى cancelled حتى لا نفقد سبب الفشل)
        if order.payment_method == Order.PAYMENT_GATEWAY:
            if order.payment_status == Order.PAY_STATUS_PAID:
                new_pay = Order.PAY_STATUS_REFUNDED
            elif order.payment_status == Order.PAY_STATUS_PENDING:
                new_pay = Order.PAY_STATUS_CANCELLED
            elif order.payment_status == Order.PAY_STATUS_FAILED:
                new_pay = Order.PAY_STATUS_FAILED

    elif new_status == Order.STATUS_DELIVERED:
        # تسليم + دفع عند الاستلام → علّم الدفع كـ "مدفوع"
        if order.payment_method == Order.PAYMENT_CASH:
            new_pay = Order.PAY_STATUS_PAID

    elif new_status == Order.STATUS_READY:
        # عند جاهز للشحن: أنشئ شحنة إن لم تكن موجودة (لتظهر في بوابة المندوب)
        if not hasattr(order, 'shipment'):
            import secrets
            Shipment.objects.create(
                order=order,
                tracking_number=f"FAKE-{secrets.randbelow(10**8):08d}",
                status=Shipment.STATUS_CREATED,
                last_event="تم تجهيز الطلب وأصبح جاهزاً للشحن (محاكاة)",
            )

    elif new_status == Order.STATUS_SHIPPED:
        # عند الشحن: إن كانت الشحنة موجودة، حدّثها إلى in_transit (إن لم تكن وصلت بعد)
        if hasattr(order, 'shipment'):
            try:
                sh = order.shipment
                if sh.status in [Shipment.STATUS_CREATED, Shipment.STATUS_PICKED]:
                    sh.status = Shipment.STATUS_IN_TRANSIT
                    sh.last_event = "تم استلام الطلب من المتجر وبدأ الشحن (محاكاة)"
                    sh.save(update_fields=['status', 'last_event', 'updated_at'])
            except Exception:
                pass

    # ── حفظ التغييرات ────────────────────────────────────────────────
    order.status = new_status
    order.payment_status = new_pay
    order.save(update_fields=['status', 'payment_status', 'updated_at'])

    _log_change(
        order, old_status, new_status, actor, is_auto, note,
        old_pay, new_pay
    )

    # إشعار Email (يظهر في Terminal)
    notify_order_status(
        order,
        title="تحديث حالة الطلب",
        extra=f"تم تحديث الحالة إلى: {order.get_status_display()}\n{note}".strip()
    )

    return order


def cancel_order(order, reason='', note='', actor=None, is_auto=False):
    """
    إلغاء الطلب مع حفظ السبب.
    يُستدعى من: طلب العميل / قرار إداري / انتهاء مهلة الدفع
    """
    from .models import Order

    if order.status == Order.STATUS_CANCELLED:
        raise OrderTransitionError('الطلب ملغي مسبقاً.')

    if order.status not in [
        Order.STATUS_PENDING, Order.STATUS_CONFIRMED, Order.STATUS_PROCESSING
    ]:
        raise OrderTransitionError(
            f"لا يمكن إلغاء طلب في حالة '{order.get_status_display()}'."
        )

    old_status = order.status
    _restore_stock(order)

    old_pay = order.payment_status
    new_pay = old_pay
    if (order.payment_method == Order.PAYMENT_GATEWAY
            and order.payment_status == Order.PAY_STATUS_PAID):
        new_pay = Order.PAY_STATUS_REFUNDED
    elif order.payment_method == Order.PAYMENT_GATEWAY and order.payment_status == Order.PAY_STATUS_PENDING:
        new_pay = Order.PAY_STATUS_CANCELLED

    order.status         = Order.STATUS_CANCELLED
    order.payment_status = new_pay
    order.cancel_reason  = reason
    order.cancel_note    = note
    order.save(update_fields=[
        'status', 'payment_status', 'cancel_reason', 'cancel_note', 'updated_at'
    ])

    _log_change(
        order, old_status, Order.STATUS_CANCELLED,
        actor, is_auto,
        note or f"سبب الإلغاء: {dict(order.CANCEL_REASON_CHOICES).get(reason, reason)}",
        old_pay, new_pay
    )

    notify_order_status(
        order,
        title="تم إلغاء الطلب",
        extra=note or f"سبب الإلغاء: {dict(order.CANCEL_REASON_CHOICES).get(reason, reason)}"
    )
    return order


def mark_payment(order, new_pay_status, actor=None, note='', is_auto=False):
    """
    تحديث حالة الدفع فقط دون تغيير حالة الطلب.
    يُستدعى من: webhook بوابة الدفع، أو قرار يدوي
    """
    old_pay = order.payment_status
    order.payment_status = new_pay_status
    order.save(update_fields=['payment_status', 'updated_at'])

    _log_change(
        order, order.status, order.status,
        actor, is_auto,
        note or f'تحديث حالة الدفع: {old_pay} → {new_pay_status}',
        old_pay, new_pay_status
    )
    notify_order_status(
        order,
        title="تحديث حالة الدفع",
        extra=note or f"تم تحديث حالة الدفع إلى: {order.get_payment_status_display()}"
    )
    return order


def create_initial_history(order, actor=None):
    """
    يُستدعى مرة واحدة عند إنشاء الطلب لتسجيل نقطة البداية في السجل.
    """
    _log_change(
        order, '', order.status,
        actor, True,
        'تم إنشاء الطلب',
        '', order.payment_status
    )


# ── قيود نوع العميل ───────────────────────────────────────────────────

def validate_order_creation(customer_type, payment_method):
    """
    يتحقق أن نوع العميل يتوافق مع طريقة الدفع.
    الضيف: مسموح COD أو محاكاة بوابة الدفع (Gateway).
    المستخدم المسجل: COD أو Gateway.
    يرفع ValueError عند المخالفة.
    """
    from .models import Order
    if customer_type == Order.CUSTOMER_GUEST:
        allowed_guest_methods = {Order.PAYMENT_CASH, Order.PAYMENT_GATEWAY}
        if payment_method not in allowed_guest_methods:
            raise ValueError(
                'الطلبات بدون حساب مسجل تدعم الدفع عند الاستلام أو بوابة الدفع (محاكاة).'
            )


# ── تسميات بصرية لواجهات المستخدم ────────────────────────────────────

STATUS_ICONS = {
    'pending':       ('⏳', '#f59e0b', 'warning'),
    'confirmed':     ('✅', '#3b82f6', 'info'),
    'processing':    ('⚙️',  '#8b5cf6', 'purple'),
    'ready_to_ship': ('📦', '#06b6d4', 'cyan'),
    'shipped':       ('🚚', '#10b981', 'success'),
    'delivered':     ('🎉', '#2c5f4f', 'delivered'),
    'cancelled':     ('❌', '#ef4444', 'danger'),
}

PAY_STATUS_ICONS = {
    'pending':              ('💳', '#f59e0b'),
    'paid':                 ('✅', '#10b981'),
    'failed':               ('❌', '#ef4444'),
    'cancelled':            ('⛔', '#6b7280'),
    'refunded':             ('↩️',  '#3b82f6'),
    'partially_refunded':   ('↩️',  '#8b5cf6'),
}
