"""منطق مشترك للدردشة الداخلية (شحن / مستودع)."""
from django.contrib.auth.models import User
from django.utils import timezone

from .models import InternalSupportMessage, InternalSupportThread


def apply_internal_chat_routing(
    thread: InternalSupportThread,
    *,
    user,
    is_manager: bool,
    manager_account_type: str,
) -> str:
    """
    يحدّث حقول المحادثة (مدير، حالة، توقيتات) ويعيد قيمة sender_type لرسالة InternalSupportMessage.
    """
    if is_manager:
        if thread.manager_user_id is None:
            thread.manager_user = user
        sender_type = InternalSupportMessage.SENDER_MANAGER
        thread.status = InternalSupportThread.STATUS_ACTIVE
        thread.last_manager_message_at = timezone.now()
        thread.waiting_notice_sent_at = None
        return sender_type

    if thread.manager_user_id is None:
        manager = User.objects.filter(
            is_active=True,
            profile__account_type=manager_account_type,
            profile__is_available=True,
        ).order_by('id').first()
        if manager:
            thread.manager_user = manager
            thread.status = InternalSupportThread.STATUS_ACTIVE
    sender_type = InternalSupportMessage.SENDER_STAFF
    thread.last_staff_message_at = timezone.now()
    return sender_type


def create_internal_chat_messages(thread, sender_type: str, user, text: str, images):
    """ينشئ رسالة/رسائل (صورة لكل ملف عند تعدد المرفقات)."""
    if images:
        for idx, image in enumerate(images):
            InternalSupportMessage.objects.create(
                thread=thread,
                sender_type=sender_type,
                sender_user=user,
                text=text if idx == 0 else '',
                image=image,
            )
    else:
        InternalSupportMessage.objects.create(
            thread=thread,
            sender_type=sender_type,
            sender_user=user,
            text=text,
            image=None,
        )
