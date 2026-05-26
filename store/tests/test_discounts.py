from decimal import Decimal

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase
from django.utils import timezone

from store.discount_engine import price_cart
from store.models import (
    Category,
    Compartment,
    Coupon,
    CouponRedemption,
    Product,
    Promotion,
    Shelf,
)


class DiscountEngineTests(TestCase):
    def setUp(self):
        self.compartment = Compartment.objects.create(name_ar='الدولاب', order=1, is_active=True)
        self.shelf = Shelf.objects.create(compartment=self.compartment, name_ar='الملابس', order=1, is_active=True)
        self.category = Category.objects.create(shelf=self.shelf, name_ar='تيشيرتات', order=1, is_active=True)

        self.product = Product.objects.create(
            category=self.category,
            sku='T-800',
            slug='t-800',
            name_ar='تيشيرت 1',
            price=Decimal('100.00'),
            stock=50,
            is_active=True,
        )

    def test_best_offer_by_value_percent_vs_fixed(self):
        # عرض 1: 20% على السطر => 100*2*20% = 40
        promo_percent = Promotion.objects.create(
            name='خصم 20%',
            discount_type=Promotion.DISCOUNT_PERCENT,
            discount_value=Decimal('20.00'),
            is_active=True,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=1),
        )
        promo_percent.products.add(self.product)

        # عرض 2: Fixed على السطر => min(50, 200) = 50 (الأكبر)
        promo_fixed = Promotion.objects.create(
            name='خصم 50 ثابت',
            discount_type=Promotion.DISCOUNT_FIXED,
            discount_value=Decimal('50.00'),
            is_active=True,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=1),
        )
        promo_fixed.products.add(self.product)

        cart_items = [
            {
                'product': self.product,
                'variant': None,
                'quantity': 2,
                'price': '100.00',
                'name': self.product.name_ar,
                'selected_gallery_image': None,
            }
        ]

        pricing = price_cart(cart_items, user=None, guest_phone=None, coupon_code=None)
        self.assertEqual(pricing['product_discount_total'], Decimal('50.00'))
        # (200 - 50) / 2 = 75
        self.assertEqual(pricing['lines'][0]['unit_price_after_offer'], Decimal('75.00'))

    def test_coupon_applies_on_final_subtotal_and_blocks_logged_user_reuse(self):
        promo_fixed = Promotion.objects.create(
            name='خصم 25 ثابت',
            discount_type=Promotion.DISCOUNT_FIXED,
            discount_value=Decimal('25.00'),
            is_active=True,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=1),
        )
        promo_fixed.products.add(self.product)

        Coupon.objects.create(
            code='SALE10',
            is_active=True,
            discount_type=Coupon.DISCOUNT_PERCENT,
            discount_value=Decimal('10.00'),
            max_uses_total=99,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=1),
        )

        cart_items = [
            {
                'product': self.product,
                'variant': None,
                'quantity': 2,
                'price': '100.00',
                'name': self.product.name_ar,
                'selected_gallery_image': None,
            }
        ]

        user = User.objects.create_user(username='coupon_user_engine', password='testpass123')
        pricing1 = price_cart(cart_items, user=user, guest_phone=None, coupon_code='SALE10')
        self.assertEqual(pricing1['applied_coupon_code'], 'SALE10')

        c = Coupon.objects.get(code__iexact='SALE10')
        CouponRedemption.objects.create(coupon=c, user=user, guest_phone=None)

        pricing2 = price_cart(cart_items, user=user, guest_phone=None, coupon_code='SALE10')
        self.assertIsNone(pricing2['applied_coupon_code'])

    def test_guest_cannot_use_coupon_even_with_phone(self):
        promo_fixed = Promotion.objects.create(
            name='خصم 25 ثابت',
            discount_type=Promotion.DISCOUNT_FIXED,
            discount_value=Decimal('25.00'),
            is_active=True,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=1),
        )
        promo_fixed.products.add(self.product)

        Coupon.objects.create(
            code='GUESTX',
            is_active=True,
            discount_type=Coupon.DISCOUNT_PERCENT,
            discount_value=Decimal('5.00'),
            max_uses_total=99,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=1),
        )

        cart_items = [
            {
                'product': self.product,
                'variant': None,
                'quantity': 1,
                'price': '100.00',
                'name': self.product.name_ar,
                'selected_gallery_image': None,
            }
        ]

        pricing = price_cart(cart_items, user=AnonymousUser(), guest_phone='0500000000', coupon_code='GUESTX')
        self.assertIsNone(pricing.get('applied_coupon_code'))

