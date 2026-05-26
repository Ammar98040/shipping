from django.conf import settings


class FakeShippingError(Exception):
    pass


def verify_secret(secret: str) -> None:
    if secret != getattr(settings, 'FAKE_SHIPPING_WEBHOOK_SECRET', ''):
        raise FakeShippingError('Invalid shipping secret')


def apply_shipping_update(*, shipment, new_status: str, message: str = '', payload=None, actor=None):
    """
    Apply shipping status update coming from webhook.
    """
    from store.models import Order, Shipment
    from store.notifications import notify_order_status
    from store.order_engine import OrderTransitionError, advance_order

    new_status = (new_status or '').strip()
    if new_status not in dict(Shipment.STATUS_CHOICES):
        raise FakeShippingError('Unknown shipment status')

    shipment.status = new_status
    shipment.last_event = message or f'Webhook محاكاة: {shipment.get_status_display()}'
    shipment.save(update_fields=['status', 'last_event', 'updated_at'])

    order = shipment.order

    # ربط بسيط بين الشحن وحالة الطلب (محاكاة)
    try:
        # عند استلام المندوب للطلب من المتجر (picked_up) → تم الشحن
        if new_status == Shipment.STATUS_PICKED:
            if order.status == Order.STATUS_READY:
                advance_order(order, Order.STATUS_SHIPPED, actor=actor, note='تم استلام الطلب من المتجر بواسطة المندوب', is_auto=True)

        # عند بدء النقل/الخروج للتسليم → إن كان الطلب ما زال جاهز للشحن، انقله لشحن
        if new_status in [Shipment.STATUS_IN_TRANSIT, Shipment.STATUS_OUT_FOR_DELIVERY]:
            if order.status == Order.STATUS_READY:
                advance_order(order, Order.STATUS_SHIPPED, actor=actor, note='تحديث الشحن: الطلب أصبح في الطريق', is_auto=True)

        # عند التسليم → تم التوصيل
        if new_status == Shipment.STATUS_DELIVERED:
            if order.status == Order.STATUS_SHIPPED:
                advance_order(order, Order.STATUS_DELIVERED, actor=actor, note='تم تسليم الطلب للعميل بواسطة المندوب', is_auto=True)
    except OrderTransitionError:
        pass

    # إشعار العميل
    notify_order_status(
        order,
        title='تحديث حالة الشحن',
        extra=f"رقم التتبع: {shipment.tracking_number}\nالحالة: {shipment.get_status_display()}"
    )

    return {'ok': True, 'order_id': order.id, 'shipment_status': shipment.status}

