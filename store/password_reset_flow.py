"""
تدفق موحّد لإعادة تعيين كلمة المرور عبر OTP (كل البوابات).
خطوات: بريد → التحقق من الرمز فقط → صفحة كلمة المرور الجديدة (بعد نجاح الرمز).
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import sys
from typing import Callable, Optional, Tuple, Union

from django.contrib import messages
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

# حدود المعدّل (قابلة للضبط عبر البيئة)
_PASSWORD_RESET_EMAIL_MAX = int(os.environ.get('PASSWORD_RESET_EMAIL_MAX', '5'))
_PASSWORD_RESET_IP_MAX = int(os.environ.get('PASSWORD_RESET_IP_MAX', '40'))
_PASSWORD_RESET_WINDOW_SEC = 3600

# رسائل موحّدة (gettext_lazy للبوابات التي تستخدم الترجمة)
MSG_EMAIL_REQUIRED = _('أدخل البريد الإلكتروني.')
MSG_RATE_LIMITED = _('تم تجاوز الحد المسموح من الطلبات. حاول مرة أخرى لاحقاً.')
MSG_OTP_SENT = _('تم إرسال رمز التحقق. تحقق من بريدك الإلكتروني.')
MSG_NO_ACCOUNT = _('لا يوجد حساب مسجل بهذا البريد الإلكتروني.')
MSG_OTP_RESTART = _('ابدأ عملية استعادة كلمة المرور من جديد.')
MSG_OTP_EXPIRED = _('انتهت صلاحية الرمز. أعد الإرسال.')
MSG_OTP_WRONG = _('رمز التحقق غير صحيح.')
MSG_OTP_VERIFIED = _('تم التحقق من الرمز. اختر كلمة المرور الجديدة.')
MSG_COMPLETE_OTP_FIRST = _('أكمل التحقق من الرمز أولاً.')
MSG_PASSWORD_SHORT = _('كلمة المرور يجب أن تكون 6 أحرف على الأقل.')
MSG_PASSWORD_MISMATCH = _('كلمتا المرور غير متطابقتين.')
MSG_PASSWORD_CHANGED = _('تمت إعادة تعيين كلمة المرور. يمكنك تسجيل الدخول الآن.')
MSG_OTP_RESEND_LIMIT = _('تم تجاوز الحد: يُسمح بثلاث إعادات إرسال للرمز في نفس الجلسة بعد الإرسال الأول.')


def generate_otp() -> str:
    return f"{random.randint(0, 999999):06d}"


def create_password_reset_otp(*, user, email: str):
    """
    Create a new password reset OTP for user.
    Returns (otp_obj, code).
    """
    from store.models import PasswordResetOTP

    code = generate_otp()
    otp = PasswordResetOTP.objects.create(
        user=user,
        email=email,
        code=code,
        expires_at=timezone.now() + timezone.timedelta(minutes=10),
    )
    return otp, code


def send_password_reset_otp(*, email: str, code: str, context: str = '') -> None:
    subject = 'رمز إعادة تعيين كلمة المرور'
    body = f"رمز إعادة تعيين كلمة المرور: {code}\nينتهي خلال 10 دقائق."
    if context:
        body = f"{context}\n\n{body}"
    send_mail(subject, body, None, [email], fail_silently=True)
    line = f"[PASSWORD_RESET_OTP] email={email} otp={code} context={(context or '').strip() or '-'}"
    # On Windows terminals, stdout may use cp1252 and fail on Arabic text.
    # We always emit the OTP line without raising encode errors.
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
        sys.stdout.buffer.write((line + '\n').encode(enc, errors='replace'))
        sys.stdout.flush()
    logger.info(
        'Password reset OTP queued/sent for email=%s context=%s',
        email,
        (context or '')[:80],
    )
    from django.conf import settings
    if settings.DEBUG:
        logger.debug('Password reset OTP (dev only): email=%s code=%s', email, code)


def _client_ip(request: HttpRequest) -> str:
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or 'unknown'


def _email_rate_key(email: str) -> str:
    h = hashlib.sha256(email.lower().encode('utf-8')).hexdigest()[:40]
    return f'pwreset:v1:e:{h}'


def _ip_rate_key(ip: str) -> str:
    return f'pwreset:v1:i:{ip}'


def password_reset_rate_check(request: HttpRequest, email: str) -> bool:
    """
    يزيد العداد ويُرجع True إذا كان الطلب مسموحاً، False إذا تجاوز الحد.
    """
    email = (email or '').strip().lower()
    if not email:
        return True
    ip = _client_ip(request)
    ek, ik = _email_rate_key(email), _ip_rate_key(ip)

    def _get(k: str) -> int:
        v = cache.get(k)
        return int(v) if v is not None else 0

    ev, iv = _get(ek), _get(ik)
    if ev >= _PASSWORD_RESET_EMAIL_MAX or iv >= _PASSWORD_RESET_IP_MAX:
        return False

    try:
        cache.incr(ek)
    except ValueError:
        cache.set(ek, 1, _PASSWORD_RESET_WINDOW_SEC)
    try:
        cache.incr(ik)
    except ValueError:
        cache.set(ik, 1, _PASSWORD_RESET_WINDOW_SEC)
    return True


UserType = object  # Django User


def process_forgot_password_step1(
    request: HttpRequest,
    *,
    email_raw: str,
    session_otp_key: str,
    session_verified_key: str,
    resolve_user: Callable[[str], Optional[UserType]],
    mail_context: str,
) -> Tuple[str, Optional[object]]:
    """
    معالجة POST لخطوة «أدخل البريد».

    يُرجع:
      ('empty', None)
      ('rate', None)
      ('otp', None) — تم ضبط الجلسة وإرسال البريد
      ('no_user', None) — لا يوجد مستخدم مطابق
    """
    email = (email_raw or '').strip().lower()
    if not email:
        return 'empty', None
    if not password_reset_rate_check(request, email):
        return 'rate', None

    user = resolve_user(email)
    if user:
        otp_obj, code = create_password_reset_otp(user=user, email=email)
        request.session[session_otp_key] = otp_obj.id
        request.session.pop(session_verified_key, None)
        send_password_reset_otp(email=email, code=code, context=mail_context)
        return 'otp', None
    return 'no_user', None


def get_active_password_reset_otp(request: HttpRequest, session_otp_key: str):
    """جلب سجل OTP النشط من الجلسة أو None."""
    from store.models import PasswordResetOTP

    otp_id = request.session.get(session_otp_key)
    if not otp_id:
        return None
    return PasswordResetOTP.objects.filter(id=otp_id, is_used=False).select_related('user').first()


def try_verify_password_reset_otp_step(
    request: HttpRequest,
    otp_obj,
    *,
    session_otp_key: str,
    session_verified_key: str,
    url_forgot: str,
    url_otp: str,
    url_new_password: str,
) -> Union[HttpResponse, None]:
    """POST على صفحة الرمز فقط؛ عند النجاح يضبط الجلسة ويُحوّل لصفحة كلمة المرور."""
    if request.method != 'POST':
        return None

    code = (request.POST.get('code') or '').strip()

    if otp_obj.is_expired():
        messages.error(request, MSG_OTP_EXPIRED)
        request.session.pop(session_otp_key, None)
        request.session.pop(session_verified_key, None)
        return redirect(url_forgot)

    if code != otp_obj.code:
        messages.error(request, MSG_OTP_WRONG)
        return redirect(url_otp)

    request.session[session_verified_key] = True
    messages.success(request, MSG_OTP_VERIFIED)
    return redirect(url_new_password)


def get_context_for_new_password_page(
    request: HttpRequest,
    *,
    session_otp_key: str,
    session_verified_key: str,
    url_forgot: str,
    url_otp: str,
) -> Tuple[Optional[HttpResponse], Optional[object]]:
    """
    يُرجع (redirect, None) إن لم يُسمح بعرض صفحة كلمة المرور،
    أو (None, otp_obj) إن كان المسموح.
    """
    otp_obj = get_active_password_reset_otp(request, session_otp_key)
    if not otp_obj:
        messages.error(request, MSG_OTP_RESTART)
        return redirect(url_forgot), None
    if not request.session.get(session_verified_key):
        messages.error(request, MSG_COMPLETE_OTP_FIRST)
        return redirect(url_otp), None
    if otp_obj.is_expired():
        request.session.pop(session_otp_key, None)
        request.session.pop(session_verified_key, None)
        messages.error(request, MSG_OTP_EXPIRED)
        return redirect(url_forgot), None
    return None, otp_obj


def try_set_new_password_after_verified_otp(
    request: HttpRequest,
    otp_obj,
    *,
    session_otp_key: str,
    session_verified_key: str,
    url_forgot: str,
    url_otp: str,
    url_new_password: str,
    url_login: str,
    success_message,
) -> Union[HttpResponse, None]:
    """POST على صفحة كلمة المرور الجديدة (بعد التحقق من الرمز)."""
    if request.method != 'POST':
        return None

    if not request.session.get(session_verified_key):
        messages.error(request, MSG_COMPLETE_OTP_FIRST)
        return redirect(url_otp)

    if otp_obj.is_expired():
        request.session.pop(session_otp_key, None)
        request.session.pop(session_verified_key, None)
        messages.error(request, MSG_OTP_EXPIRED)
        return redirect(url_forgot)

    pw1 = request.POST.get('password1') or ''
    pw2 = request.POST.get('password2') or ''

    if not pw1 or len(pw1) < 6:
        messages.error(request, MSG_PASSWORD_SHORT)
        return redirect(url_new_password)

    if pw1 != pw2:
        messages.error(request, MSG_PASSWORD_MISMATCH)
        return redirect(url_new_password)

    user = otp_obj.user
    user.set_password(pw1)
    user.save(update_fields=['password'])
    otp_obj.is_used = True
    otp_obj.save(update_fields=['is_used'])
    request.session.pop(session_otp_key, None)
    request.session.pop(session_verified_key, None)
    messages.success(request, success_message)
    return redirect(url_login)


def refresh_password_reset_otp_code(otp_obj) -> str:
    """رمز جديد ومدة صلاحية جديدة لنفس سجل OTP."""
    code = generate_otp()
    otp_obj.code = code
    otp_obj.expires_at = timezone.now() + timezone.timedelta(minutes=10)
    otp_obj.save(update_fields=['code', 'expires_at'])
    return code


def password_reset_otp_resend_response(
    request: HttpRequest,
    otp_obj,
    *,
    portal: str,
    mail_context: str,
    url_otp: str,
):
    """POST إعادة إرسال رمز نسيت كلمة المرور (حد الجلسة عبر security_services)."""
    from django.http import JsonResponse

    from store.security_services import (
        otp_can_send_in_challenge,
        otp_record_successful_send,
        otp_send_session_key_pw_portal,
        otp_sends_remaining,
    )

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    key = otp_send_session_key_pw_portal(portal)

    if not otp_can_send_in_challenge(request, key):
        if is_ajax:
            return JsonResponse(
                {
                    'success': False,
                    'error': str(MSG_OTP_RESEND_LIMIT),
                    'otp_sends_remaining': otp_sends_remaining(request, key),
                },
                status=429,
            )
        messages.error(request, MSG_OTP_RESEND_LIMIT)
        return redirect(url_otp)

    new_code = refresh_password_reset_otp_code(otp_obj)
    send_password_reset_otp(email=otp_obj.email, code=new_code, context=mail_context)
    otp_record_successful_send(request, key)
    rem = otp_sends_remaining(request, key)
    ok_msg = _('تم إرسال رمز جديد.')
    if is_ajax:
        return JsonResponse({'success': True, 'message': str(ok_msg), 'otp_sends_remaining': rem})
    messages.success(request, ok_msg)
    return redirect(url_otp)
