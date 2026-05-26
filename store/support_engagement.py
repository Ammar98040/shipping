"""متى تُعتبر محادثة خدمة العملاء «مفتوحة» لدى الموظفين."""

from __future__ import annotations

from django.db.models import Q

from .models import SupportThread


def support_thread_customer_engaged(thread: SupportThread | None) -> bool:
    """محادثة حقيقية فقط بعد أول رسالة من العميل أو اختيار من الشات بوت."""
    return bool(thread and thread.last_customer_message_at)


def support_staff_visible_q() -> Q:
    return Q(last_customer_message_at__isnull=False)
