import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from django.core.management import call_command

from store.models import (
    Compartment, Shelf, Category, Product,
    Order, OrderItem, OrderStatusHistory,
    Return, ReturnStatusHistory,
    PaymentAttempt, Shipment,
)


HOST = "127.0.0.1"


def ensure_catalog():
    comp, _ = Compartment.objects.get_or_create(name_ar="ملابس", defaults={"order": 1, "is_active": True})
    shelf, _ = Shelf.objects.get_or_create(compartment=comp, name_ar="صيفي", defaults={"order": 1, "is_active": True})
    cat, _ = Category.objects.get_or_create(shelf=shelf, name_ar="تيشيرتات", defaults={"order": 1, "is_active": True})

    prod, _ = Product.objects.get_or_create(
        category=cat,
        name_ar="تيشيرت اختبار سيناريوهات",
        defaults={"price": Decimal("120.00"), "stock": 50, "order": 1, "is_active": True},
    )
    if prod.stock < 50:
        prod.stock = 50
        prod.save(update_fields=["stock"])
    return prod


def ensure_users():
    user, created = User.objects.get_or_create(username="scenario_user", defaults={"email": "scenario_user@example.com"})
    if created:
        user.set_password("TestPass123!")
        user.save()

    staff, created2 = User.objects.get_or_create(
        username="scenario_staff",
        defaults={"email": "scenario_staff@example.com", "is_staff": True},
    )
    if created2:
        staff.set_password("StaffPass123!")
        staff.is_staff = True
        staff.save()

    return user, staff


def clean_all_scenario_data():
    # Clean by username or by marker in notes
    ReturnStatusHistory.objects.filter(return_request__user__username="scenario_user").delete()
    Return.objects.filter(user__username="scenario_user").delete()

    OrderStatusHistory.objects.filter(order__user__username="scenario_user").delete()
    PaymentAttempt.objects.filter(order__user__username="scenario_user").delete()
    Shipment.objects.filter(order__user__username="scenario_user").delete()
    OrderItem.objects.filter(order__user__username="scenario_user").delete()
    Order.objects.filter(user__username="scenario_user").delete()

    # Guest orders created in these tests use this phone and marker notes
    ReturnStatusHistory.objects.filter(return_request__order__notes__icontains="SCENARIO_TEST").delete()
    Return.objects.filter(order__notes__icontains="SCENARIO_TEST").delete()
    OrderStatusHistory.objects.filter(order__notes__icontains="SCENARIO_TEST").delete()
    PaymentAttempt.objects.filter(order__notes__icontains="SCENARIO_TEST").delete()
    Shipment.objects.filter(order__notes__icontains="SCENARIO_TEST").delete()
    OrderItem.objects.filter(order__notes__icontains="SCENARIO_TEST").delete()
    Order.objects.filter(notes__icontains="SCENARIO_TEST").delete()


def add_to_cart(client, product):
    r = client.get(f"/cart/add/{product.id}/")
    assert r.status_code in (302, 303), f"cart_add failed: {r.status_code}"


def checkout(client, *, payment_method, email, notes="SCENARIO_TEST"):
    payload = {
        "customer_name": "Scenario Tester",
        "customer_phone": "0500000001",
        "customer_email": email,
        "country": "SA",
        "city": "Riyadh",
        "district": "Test",
        "postal_code": "00000",
        "national_address": "NA",
        "street": "Street",
        "building_number": "10",
        "additional_info": "",
        "notes": notes,
        "payment_method": payment_method,
    }
    r = client.post("/checkout/", data=payload, follow=False)
    assert r.status_code in (302, 303), f"checkout expected redirect, got {r.status_code}"
    return r["Location"]


def scenario_A_registered_gateway_success(product, user, staff):
    print("\n--- Scenario A: registered + gateway success ---")
    c = Client(HTTP_HOST=HOST)
    assert c.login(username=user.username, password="TestPass123!")

    add_to_cart(c, product)
    loc = checkout(c, payment_method="payment_gateway", email=user.email)
    assert "/pay/fake/" in loc

    attempt_id = int(loc.strip("/").split("/")[-1])
    import json
    r = c.post(
        "/webhooks/fake-gateway/",
        data=json.dumps({"secret": "dev-secret-gateway", "attempt_id": attempt_id, "result": "success", "reference": "A-OK"}),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content

    order = Order.objects.filter(user=user).order_by("-id").first()
    assert order.payment_status == Order.PAY_STATUS_PAID
    assert order.status == Order.STATUS_CONFIRMED
    assert OrderStatusHistory.objects.filter(order=order).exists(), "order history missing"

    # Staff continues to delivered via manage view
    c2 = Client(HTTP_HOST=HOST)
    assert c2.login(username=staff.username, password="StaffPass123!")
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "processing", "note": "A"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "ready_to_ship", "note": "A"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "shipped", "note": "A"}, follow=True)

    # Shipping delivered via webhook
    r = c2.post(
        "/webhooks/fake-shipping/",
        data=json.dumps({"secret": "dev-secret-shipping", "order_id": order.id, "shipment_status": "delivered", "message": "A delivered"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    order.refresh_from_db()
    assert order.status == Order.STATUS_DELIVERED
    assert order.payment_status == Order.PAY_STATUS_PAID
    assert hasattr(order, "shipment")
    return order


def scenario_B_registered_gateway_fail(product, user):
    print("\n--- Scenario B: registered + gateway fail ---")
    # ensure enough stock
    product.refresh_from_db()
    stock_before = product.stock

    c = Client(HTTP_HOST=HOST)
    assert c.login(username=user.username, password="TestPass123!")

    add_to_cart(c, product)
    loc = checkout(c, payment_method="payment_gateway", email=user.email)
    attempt_id = int(loc.strip("/").split("/")[-1])

    import json
    r = c.post(
        "/webhooks/fake-gateway/",
        data=json.dumps({"secret": "dev-secret-gateway", "attempt_id": attempt_id, "result": "fail", "reference": "B-FAIL"}),
        content_type="application/json",
    )
    assert r.status_code == 200

    order = Order.objects.filter(user=user).order_by("-id").first()
    order.refresh_from_db()
    assert order.payment_status == Order.PAY_STATUS_FAILED
    assert order.status == Order.STATUS_CANCELLED, f"expected cancelled, got {order.status}"

    product.refresh_from_db()
    assert product.stock == stock_before, "stock not restored after cancel"


def scenario_C_registered_cod(product, user, staff):
    print("\n--- Scenario C: registered + COD ---")
    c = Client(HTTP_HOST=HOST)
    assert c.login(username=user.username, password="TestPass123!")

    add_to_cart(c, product)
    loc = checkout(c, payment_method="cash_on_delivery", email=user.email)
    assert "/order/success/" in loc

    order = Order.objects.filter(user=user).order_by("-id").first()
    assert order.payment_method == Order.PAYMENT_CASH
    assert order.payment_status == Order.PAY_STATUS_PENDING

    c2 = Client(HTTP_HOST=HOST)
    assert c2.login(username=staff.username, password="StaffPass123!")
    # pending -> confirmed -> processing -> ready -> shipped -> delivered
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "confirmed", "note": "C"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "processing", "note": "C"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "ready_to_ship", "note": "C"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "shipped", "note": "C"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "delivered", "note": "C"}, follow=True)

    order.refresh_from_db()
    assert order.status == Order.STATUS_DELIVERED
    assert order.payment_status == Order.PAY_STATUS_PAID, "COD should be marked paid on delivered"


def scenario_D_guest_cod_only(product):
    print("\n--- Scenario D: guest + COD only ---")
    c = Client(HTTP_HOST=HOST)
    add_to_cart(c, product)

    # Attempt gateway as guest -> should be forced to COD (and redirect to success page)
    loc = checkout(c, payment_method="payment_gateway", email="guest@example.com", notes="SCENARIO_TEST_GUEST")
    assert "/order/success/" in loc

    order = Order.objects.filter(user__isnull=True).order_by("-id").first()
    assert order.customer_type == Order.CUSTOMER_GUEST
    assert order.payment_method == Order.PAYMENT_CASH

    # Track via token
    r = c.get(f"/order/track/?token={order.tracking_token}")
    assert r.status_code == 200


def scenario_E_auto_cancel(product):
    print("\n--- Scenario E: auto-cancel expired orders ---")
    product.refresh_from_db()
    stock_before = product.stock

    # Create 2 orders directly (old pending + old gateway pending)
    o1 = Order.objects.create(
        user=None,
        customer_type=Order.CUSTOMER_GUEST,
        customer_name="Expired Pending",
        customer_phone="0500000099",
        customer_email="expired@example.com",
        address="addr",
        notes="SCENARIO_TEST_EXPIRED",
        status=Order.STATUS_PENDING,
        payment_method=Order.PAYMENT_CASH,
        payment_status=Order.PAY_STATUS_PENDING,
        delivery_fee=Decimal("0"),
    )
    Order.objects.filter(pk=o1.pk).update(created_at=timezone.now() - timedelta(hours=100))
    OrderItem.objects.create(order=o1, product=product, quantity=1, price=product.price)
    product.stock -= 1
    product.save(update_fields=["stock"])

    o2 = Order.objects.create(
        user=None,
        customer_type=Order.CUSTOMER_GUEST,
        customer_name="Expired Gateway",
        customer_phone="0500000098",
        customer_email="expired2@example.com",
        address="addr",
        notes="SCENARIO_TEST_EXPIRED",
        status=Order.STATUS_PENDING,
        payment_method=Order.PAYMENT_GATEWAY,
        payment_status=Order.PAY_STATUS_PENDING,
        delivery_fee=Decimal("0"),
    )
    Order.objects.filter(pk=o2.pk).update(created_at=timezone.now() - timedelta(hours=10))
    OrderItem.objects.create(order=o2, product=product, quantity=1, price=product.price)
    product.stock -= 1
    product.save(update_fields=["stock"])

    # Run cancel command with small hours to catch both
    call_command("auto_cancel_expired_orders", pending_hours=1, payment_hours=1)

    o1.refresh_from_db()
    o2.refresh_from_db()
    assert o1.status == Order.STATUS_CANCELLED
    assert o2.status == Order.STATUS_CANCELLED

    product.refresh_from_db()
    assert product.stock == stock_before, "stock should be restored after auto-cancel"


def scenario_F_returns_flow(product, user, staff):
    print("\n--- Scenario F: returns workflow ---")
    # create delivered & paid order (gateway success)
    c = Client(HTTP_HOST=HOST)
    assert c.login(username=user.username, password="TestPass123!")
    add_to_cart(c, product)
    loc = checkout(c, payment_method="payment_gateway", email=user.email, notes="SCENARIO_TEST_RETURN")
    attempt_id = int(loc.strip("/").split("/")[-1])

    import json
    r = c.post(
        "/webhooks/fake-gateway/",
        data=json.dumps({"secret": "dev-secret-gateway", "attempt_id": attempt_id, "result": "success", "reference": "F-OK"}),
        content_type="application/json",
    )
    assert r.status_code == 200

    order = Order.objects.filter(user=user).order_by("-id").first()

    # staff deliver
    c2 = Client(HTTP_HOST=HOST)
    assert c2.login(username=staff.username, password="StaffPass123!")
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "processing", "note": "F"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "ready_to_ship", "note": "F"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "shipped", "note": "F"}, follow=True)
    c2.post(f"/manage/orders/{order.id}/", data={"action": "advance", "new_status": "delivered", "note": "F"}, follow=True)
    order.refresh_from_db()
    assert order.status == Order.STATUS_DELIVERED
    assert order.payment_status == Order.PAY_STATUS_PAID

    # user creates return
    item = OrderItem.objects.filter(order=order).first()
    r = c.post(f"/return/create/{order.id}/", data={
        "reason": "changed_mind",
        "reason_details": "F return",
        "item_ids": [str(item.id)],
        f"quantity_{item.id}": "1",
    }, follow=False)
    assert r.status_code in (302, 303)
    ret = Return.objects.filter(order=order).first()
    assert ret.status == Return.STATUS_REQUESTED
    assert ReturnStatusHistory.objects.filter(return_request=ret).exists()

    # staff advances return to completed
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "reviewing", "note": "F"}, follow=True)
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "approved", "note": "F"}, follow=True)
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "received", "note": "F"}, follow=True)
    c2.post(f"/manage/returns/{ret.id}/", data={"action": "advance", "new_status": "completed", "note": "F"}, follow=True)

    ret.refresh_from_db()
    order.refresh_from_db()
    assert ret.status == Return.STATUS_COMPLETED
    assert ret.refund_status == Return.REFUND_COMPLETED
    assert order.payment_status == Order.PAY_STATUS_REFUNDED, "paid order should be refunded after completed return"


def main():
    print("Cleaning previous scenario data...")
    ensure_users()
    clean_all_scenario_data()

    product = ensure_catalog()
    user, staff = ensure_users()

    scenario_A_registered_gateway_success(product, user, staff)
    scenario_B_registered_gateway_fail(product, user)
    scenario_C_registered_cod(product, user, staff)
    scenario_D_guest_cod_only(product)
    scenario_E_auto_cancel(product)
    scenario_F_returns_flow(product, user, staff)

    print("\nAll scenarios A-F passed successfully.")


if __name__ == "__main__":
    main()

