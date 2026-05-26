"""Webhooks وهمية للتكامل والاختبار — التحقق بالسر في body."""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
def fake_gateway_webhook(request):
    """
    Webhook وهمي لبوابة الدفع.
    Body (JSON):
      {
        "secret": "...",
        "attempt_id": 123,
        "result": "success" | "fail",
        "reference": "..."
      }
    """
    from .integrations.fake_gateway import FakeGatewayError, apply_payment_result, verify_secret
    from .models import PaymentAttempt

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)

    try:
        verify_secret(payload.get('secret', ''))
        attempt_id = int(payload.get('attempt_id'))
        attempt = PaymentAttempt.objects.select_related('order').get(pk=attempt_id)
        result = apply_payment_result(
            attempt=attempt,
            result=payload.get('result'),
            reference=payload.get('reference', ''),
            payload=payload,
            actor=None
        )
        return JsonResponse(result)
    except (ValueError, PaymentAttempt.DoesNotExist):
        return JsonResponse({'ok': False, 'error': 'attempt_not_found'}, status=404)
    except FakeGatewayError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=403)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': 'server_error', 'detail': str(e)}, status=500)


@csrf_exempt
@require_POST
def fake_shipping_webhook(request):
    """
    Webhook وهمي لشركة الشحن.
    Body (JSON):
      {
        "secret": "...",
        "order_id": 10,
        "shipment_status": "in_transit" | "out_for_delivery" | "delivered" | ...,
        "message": "..."
      }
    """
    import secrets

    from .integrations.fake_shipping import FakeShippingError, apply_shipping_update, verify_secret
    from .models import Order, Shipment

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)

    try:
        verify_secret(payload.get('secret', ''))
        order_id = int(payload.get('order_id'))
        order = Order.objects.get(pk=order_id)
        shipment = getattr(order, 'shipment', None)
        if not shipment:
            shipment = Shipment.objects.create(
                order=order,
                tracking_number=f"FAKE-{secrets.randbelow(10**8):08d}",
                status=Shipment.STATUS_CREATED,
                last_event='تم إنشاء الشحنة عبر Webhook (محاكاة)',
            )
        result = apply_shipping_update(
            shipment=shipment,
            new_status=payload.get('shipment_status'),
            message=payload.get('message', ''),
            payload=payload,
            actor=None
        )
        return JsonResponse(result)
    except (ValueError, Order.DoesNotExist):
        return JsonResponse({'ok': False, 'error': 'order_not_found'}, status=404)
    except FakeShippingError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=403)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': 'server_error', 'detail': str(e)}, status=500)
