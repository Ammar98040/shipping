"""
التحقق من ملفات الصور المرفوعة في الدردشة وخدمة العملاء.
"""
import os

from django.conf import settings
from django.utils.translation import gettext_lazy as _


def _max_bytes():
    return int(getattr(settings, 'CHAT_IMAGE_MAX_BYTES', 5 * 1024 * 1024))


def _max_count():
    return int(getattr(settings, 'CHAT_IMAGE_MAX_COUNT', 10))


_ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
_ALLOWED_CT = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}


def validate_chat_image_files(files):
    """
    يتحقق من عدد/حجم/نوع الملفات.

    Returns:
        (list, None) عند النجاح — نفس القائمة (قد تكون فارغة).
        (None, err_dict) لـ JsonResponse: {'success': False, 'error': '...'}
    """
    if not files:
        return [], None

    max_count = _max_count()
    if len(files) > max_count:
        return None, {'success': False, 'error': 'too_many_images'}

    max_bytes = _max_bytes()
    for f in files:
        name = (getattr(f, 'name', '') or '').lower()
        ext = os.path.splitext(name)[1]
        if ext not in _ALLOWED_EXT:
            return None, {'success': False, 'error': 'image_invalid_type'}
        try:
            size = f.size
        except (AttributeError, TypeError, OSError):
            return None, {'success': False, 'error': 'image_invalid_type'}
        if size > max_bytes:
            return None, {'success': False, 'error': 'image_too_large'}
        ct = (getattr(f, 'content_type', '') or '').strip().lower()
        if ct and ct not in _ALLOWED_CT:
            return None, {'success': False, 'error': 'image_invalid_type'}

    return list(files), None


def chat_image_error_message(error_code: str) -> str:
    """رسالة عربية للعرض في messages.error أو واجهة المستخدم."""
    mapping = {
        'too_many_images': _('عدد الصور يتجاوز الحد المسموح.'),
        'image_invalid_type': _('نوع الملف غير مسموح. استخدم صورة (JPEG أو PNG أو GIF أو WebP).'),
        'image_too_large': _('حجم الصورة كبير جداً.'),
    }
    return str(mapping.get(error_code, _('ملف مرفوض.')))
