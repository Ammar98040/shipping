"""
Context processors for store app.
المشروع عربي فقط — اتجاه RTL ثابت.
"""
from django.conf import settings

from .cart import Cart
from .models import Wishlist
from .security_services import login_needs_turnstile, turnstile_configured


def lang_direction(request):
    return {'lang_direction': 'rtl', 'current_lang': 'ar'}


def security_context(request):
    """مفاتيح Turnstile وعرض الكابتشا على تسجيل الدخول عند الحاجة."""
    site_key = getattr(settings, 'TURNSTILE_SITE_KEY', '') or ''
    portal = getattr(request, '_security_portal', None)
    show_login_turnstile = False
    if portal and site_key:
        show_login_turnstile = login_needs_turnstile(portal, request)
    return {
        'turnstile_site_key': site_key,
        'turnstile_enabled': turnstile_configured(),
        'show_login_turnstile': show_login_turnstile,
    }


def manage_config(request):
    """إعدادات لوحة الإدارة المتاحة في كل قوالبها."""
    return {
        'MANAGE_NOTIFICATIONS_POLL_MS': int(getattr(settings, 'MANAGE_NOTIFICATIONS_POLL_MS', 8000)),
    }


def cart_context(request):
    """إتاحة السلة والمفضلة في كل الصفحات."""
    cart = Cart(request)

    # عدد المفضلات للمستخدم المسجل
    wishlist_count = 0
    if request.user.is_authenticated:
        wishlist_count = Wishlist.objects.filter(user=request.user).count()

    return {
        'cart': cart,
        'cart_items_count': len(cart),
        'cart_total': cart.get_total(),
        'wishlist_count': wishlist_count,
    }
