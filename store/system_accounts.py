"""حساب المدير الرئيسي التابع للنظام (محمي من الواجهة والنسخ الاحتياطي)."""

from __future__ import annotations

import logging
import os

from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


def primary_admin_username() -> str:
    return os.getenv('PRIMARY_ADMIN_USERNAME', 'ammar').strip() or 'ammar'


def primary_admin_password() -> str:
    return os.getenv('PRIMARY_ADMIN_PASSWORD', 'Thepest**1')


def system_immutable_username_ci() -> set[str]:
    return {
        str(u).strip().lower()
        for u in getattr(settings, 'SYSTEM_IMMUTABLE_USERNAMES', ())
        if str(u).strip()
    }


def is_system_immutable_username(username: str) -> bool:
    return (username or '').strip().lower() in system_immutable_username_ci()


def ensure_system_primary_admin() -> bool:
    """
  يضمن وجود حساب المدير الرئيسي للنظام بصلاحيات كاملة.
  كلمة المرور تُضبط عند الإنشاء فقط — لا تُعاد كتابتها عند كل تشغيل.
  """
    username = primary_admin_username()
    if not is_system_immutable_username(username):
        logger.warning('primary_admin_not_in_system_immutable_list', extra={'username': username})
        return False

    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
            'email': '',
        },
    )

    update_fields: list[str] = []
    if not user.is_staff:
        user.is_staff = True
        update_fields.append('is_staff')
    if not user.is_superuser:
        user.is_superuser = True
        update_fields.append('is_superuser')
    if not user.is_active:
        user.is_active = True
        update_fields.append('is_active')
    if created:
        user.set_password(primary_admin_password())
        update_fields.append('password')

    if update_fields:
        user.save(update_fields=update_fields)
    return created
