import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User
from django.test import Client
from decimal import Decimal

from store.models import Compartment, Shelf, Category, Product, Order, OrderItem, Return, PaymentAttempt


def ensure_catalog():
    comp, _ = Compartment.objects.get_or_create(name_ar="ملابس", defaults={"order": 1, "is_active": True})
    shelf, _ = Shelf.objects.get_or_create(compartment=comp, name_ar="صيفي", defaults={"order": 1, "is_active": True})
    cat, _ = Category.objects.get_or_create(shelf=shelf, name_ar="تيشيرتات", defaults={"order": 1, "is_active": True})
    prod, _ = Product.objects.get_or_create(
        category=cat,
        name_ar="تيشيرت تجريبي",
        defaults={"price": Decimal("99.00"), "stock": 10, "order": 1, "is_active": True},
    )
    if prod.stock < 10:
        prod.stock = 10
        prod.save(update_fields=["stock"])
    return prod


def ensure_users():
    user, created = User.objects.get_or_create(username="testuser", defaults={"email": "testuser@example.com"})
    if created:
        user.set_password("TestPass123!")
        user.save()
    staff, created2 = User.objects.get_or_create(username="staff1", defaults={"email": "staff1@example.com", "is_staff": True})
    if created2:
        staff.set_password("StaffPass123!")
        staff.is_staff = True
        staff.save()
    return user, staff


def main():
    # Clean any previous test user orders
    Order.objects.filter(user__username="testuser").delete()

    prod = ensure_catalog()
    user, staff = ensure_users()

    c = Client(HTTP_HOST="127.0.0.1")
    assert c.login(username="testuser", password="TestPass123!")

    # Add to cart via existing endpoint
    r = c.get(f"/cart/add/{prod.id}/")
    print("cart_add status:", r.status_code)

    # Checkout with fake gateway
    checkout_payload = {
        "customer_name": "Test User",
        "customer_phone": "0500000000",
        "customer_email": "testuser@example.com",
        "country": "SA",
        "city": "Riyadh",
        "district": "Test",
        "postal_code": "00000",
        "national_address": "NA",
        "street": "Street",
        "building_number": "10",
        "additional_info": "",
        "notes": "stage3 test",
        "payment_method": "payment_gateway",
    }
    r = c.post("/checkout/", data=checkout_payload, follow=False)
    print("checkout redirect:", r.status_code, r.get("Location"))
    assert r.status_code in (302, 303)

    # Should redirect to fake gateway pay
    pay_url = r["Location"]
    assert "/pay/fake/" in pay_url
    r = c.get(pay_url)
    print("fake_gateway_pay page:", r.status_code)

    # Simulate payment success
    # Deep stage3: use webhook endpoint instead of UI callback
    import json
    # Extract attempt_id from /pay/fake/<id>/
    attempt_id = int(pay_url.strip('/').split('/')[-1])
    r = c.post(
        "/webhooks/fake-gateway/",
        data=json.dumps({
            "secret": "dev-secret-gateway",
            "attempt_id": attempt_id,
            "result": "success",
            "reference": "SIM-WEBHOOK-OK"
        }),
        content_type="application/json",
    )
    print("gateway webhook:", r.status_code, r.json())
    assert r.status_code == 200

    # Fetch created order and attempt
    order = Order.objects.filter(user=user).order_by("-id").first()
    attempt = PaymentAttempt.objects.filter(order=order).order_by("-id").first()
    print("order:", order.id, order.status, order.payment_status, "attempt:", attempt.status)

    # Staff advances order to shipped and updates shipment statuses (via manage view + webhook shipping)
    c2 = Client(HTTP_HOST="127.0.0.1")
    assert c2.login(username="staff1", password="StaffPass123!")

    # Advance: confirmed -> processing
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "processing", "note": "prep"}, follow=True)
    # processing -> ready_to_ship
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "ready_to_ship", "note": "packed"}, follow=True)
    # ready_to_ship -> shipped (creates shipment)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "shipped", "note": "handed to carrier"}, follow=True)

    order.refresh_from_db()
    print("order after shipped:", order.status, "shipment exists:", hasattr(order, "shipment"))

    # Deep stage3: simulate shipping via webhook (out_for_delivery -> delivered)
    r = c2.post(
        "/webhooks/fake-shipping/",
        data=json.dumps({
            "secret": "dev-secret-shipping",
            "order_id": order.id,
            "shipment_status": "out_for_delivery",
            "message": "محاكاة: خرجت للتسليم"
        }),
        content_type="application/json",
    )
    print("shipping webhook out_for_delivery:", r.status_code, r.json())
    assert r.status_code == 200

    r = c2.post(
        "/webhooks/fake-shipping/",
        data=json.dumps({
            "secret": "dev-secret-shipping",
            "order_id": order.id,
            "shipment_status": "delivered",
            "message": "محاكاة: تم التسليم"
        }),
        content_type="application/json",
    )
    print("shipping webhook delivered:", r.status_code, r.json())
    assert r.status_code == 200
    order.refresh_from_db()
    print("order delivered:", order.status, order.payment_status)

    # Create a return for 1 item
    item = OrderItem.objects.filter(order=order).first()
    r = c.post(f"/return/create/{order.id}/", data={
        "reason": "changed_mind",
        "reason_details": "test return",
        "item_ids": [str(item.id)],
        f"quantity_{item.id}": "1",
    }, follow=False)
    print("create_return redirect:", r.status_code, r.get("Location"))
    ret = Return.objects.filter(order=order).first()
    print("return created:", ret.id, ret.status, ret.refund_status, ret.stock_status)

    # Staff advances return: requested -> reviewing -> approved -> received -> completed
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "reviewing", "note": "review"}, follow=True)
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "approved", "note": "approved"}, follow=True)
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "received", "note": "received"}, follow=True)
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "completed", "note": "completed"}, follow=True)
    ret.refresh_from_db()
    order.refresh_from_db()
    print("return completed:", ret.status, ret.refund_status, "order payment:", order.payment_status)

    print("Simulation finished OK.")


if __name__ == "__main__":
    main()

