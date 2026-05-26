"""علامات «جديد / مُحدَّث» لصفوف لوحة الإدارة."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import ManageSeenMarker


def _max_age():
    return timedelta(days=int(getattr(settings, 'MANAGE_NEW_ROW_MAX_AGE_DAYS', 30)))


def _created_ts(obj):
    return getattr(obj, 'created_at', None) or getattr(obj, 'date_joined', None)


def _updated_ts(obj):
    u = getattr(obj, 'updated_at', None)
    if u is not None:
        return u
    return _created_ts(obj)


def get_row_alert_state(user, obj, kind: str) -> str:
    """
    يُرجع حالة الصف:
    - "new": عنصر جديد غير مُطّلع عليه بعد
    - "updated": عنصر كان مُطّلعاً عليه ثم تغيّر لاحقاً
    - "none": لا توجد علامة

    معيار الظهور:
    - لم يُسجَّل اطلاع بعد والعنصر حديث ضمن نافذة العمر؛ أو
    - سُجِّل اطلاع لكن updated_at أحدث من seen_at (تغيّرت الحالة/البيانات).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return "none"
    if not getattr(user, 'is_staff', False):
        return "none"
    if obj is None:
        return "none"

    key = f'{kind}:{obj.pk}'
    marker = ManageSeenMarker.objects.filter(user=user, key=key).first()
    created = _created_ts(obj)
    updated = _updated_ts(obj)
    now = timezone.now()

    if not marker:
        if created and created >= now - _max_age():
            return "new"
        return "none"

    if updated and updated > marker.seen_at:
        return "updated"
    return "none"


def should_show_new_flag(user, obj, kind: str) -> bool:
    # توافق خلفي مع القوالب القديمة
    return get_row_alert_state(user, obj, kind) in ("new", "updated")


def mark_seen_key(user, key: str) -> None:
    """تسجيل اطلاع بمفتاح كامل مثل order:5."""
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_staff', False):
        return
    if not key or ':' not in key:
        return
    ManageSeenMarker.objects.update_or_create(
        user=user,
        key=key.strip()[:120],
        defaults={'seen_at': timezone.now()},
    )


def mark_seen_kind_pk(user, kind: str, pk) -> None:
    mark_seen_key(user, f'{kind}:{pk}')
