"""أدوار صلاحيات لوحة الإدارة — خدمة العملاء وغيرها."""

from .models import UserProfile


def _is_customer_service_manager(user) -> bool:
    """هل المستخدم مسؤول خدمة العملاء؟"""
    try:
        account_type = getattr(getattr(user, 'profile', None), 'account_type', '') or ''
    except Exception:
        account_type = ''
    return account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER


def _is_support_admin(user) -> bool:
    return bool(user and (user.is_superuser or _is_customer_service_manager(user)))
