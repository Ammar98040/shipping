from django.conf import settings
from django.utils import timezone


class FakeGatewayError(Exception):
    pass


def verify_secret(secret: str) -> None:
    if secret != getattr(settings, 'FAKE_GATEWAY_WEBHOOK_SECRET', ''):
        raise FakeGatewayError('Invalid gateway secret')


def apply_payment_result(*, attempt, result: str, reference: str = '', payload=None, actor=None):
    """
    Apply payment result coming from webhook.
    result: success|fail
    """
    from store.models import Order, PaymentAttempt
    from store.order_engine import OrderTransitionError, advance_order, cancel_order, mark_payment

    result = (result or '').strip().lower()
    reference = (reference or '').strip() or f"FAKEPAY-{attempt.id:06d}"

    attempt.reference = reference
    attempt.raw_payload = payload or {}
    attempt.raw_payload.update({
        'result': result,
        'reference': reference,
        'received_at': timezone.now().isoformat(),
        'via': 'fake_gateway_webhook',
    })

    order = attempt.order

    if result == 'success':
        attempt.status = PaymentAttempt.STATUS_SUCCESS
        attempt.save(update_fields=['status', 'reference', 'raw_payload', 'updated_at'])

        mark_payment(order, Order.PAY_STATUS_PAID, actor=actor, note='نجاح الدفع (Webhook محاكاة)', is_auto=True)
        try:
            if order.status == Order.STATUS_PENDING:
                advance_order(order, Order.STATUS_CONFIRMED, actor=actor, note='تأكيد تلقائي بعد الدفع (Webhook)', is_auto=True)
        except OrderTransitionError:
            pass
        return {'ok': True, 'order_id': order.id, 'payment_status': order.payment_status}

    if result == 'fail':
        attempt.status = PaymentAttempt.STATUS_FAILED
        attempt.save(update_fields=['status', 'reference', 'raw_payload', 'updated_at'])

        mark_payment(order, Order.PAY_STATUS_FAILED, actor=actor, note='فشل الدفع (Webhook محاكاة)', is_auto=True)
        try:
            cancel_order(order, reason=Order.CANCEL_PAYMENT_FAIL, note='إلغاء تلقائي بسبب فشل الدفع (Webhook)', is_auto=True)
        except OrderTransitionError:
            pass
        return {'ok': True, 'order_id': order.id, 'payment_status': order.payment_status}

    raise FakeGatewayError('Unknown result, expected success|fail')

