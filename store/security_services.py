"""
خدمات أمان مشتركة: Turnstile، حد محاولات الدخول، معدل التسجيل.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import HttpRequest

logger = logging.getLogger(__name__)

# ——— Turnstile ———

TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


def client_ip(request: HttpRequest) -> str:
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or 'unknown'


def turnstile_configured() -> bool:
    return bool(
        getattr(settings, 'TURNSTILE_SECRET_KEY', '')
        and getattr(settings, 'TURNSTILE_SITE_KEY', '')
    )


def verify_turnstile(request: HttpRequest) -> Tuple[bool, str]:
    """
    يتحقق من إرسال Turnstile.
    بدون مفاتيح: في DEBUG يُقبل؛ خارج DEBUG يُرفض (ما عدا إن عطّلت بالإعداد).
    """
    if not getattr(settings, 'TURNSTILE_SECRET_KEY', ''):
        if settings.DEBUG and getattr(settings, 'TURNSTILE_OPTIONAL_IN_DEBUG', True):
            return True, ''
        logger.warning('Turnstile secret missing while verification required')
        return False, 'التحقق من الهوية غير مُعدّ على الخادم.'

    token = (
        request.POST.get('cf-turnstile-response')
        or request.POST.get('g-recaptcha-response')
        or ''
    ).strip()
    if not token:
        return False, 'يرجى إكمال التحقق من أنك لست روبوتاً.'

    data = urllib.parse.urlencode(
        {
            'secret': settings.TURNSTILE_SECRET_KEY,
            'response': token,
            'remoteip': client_ip(request),
        }
    ).encode('utf-8')

    try:
        req = urllib.request.Request(
            TURNSTILE_VERIFY_URL,
            data=data,
            method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        logger.exception('Turnstile verify error: %s', e)
        return False, 'تعذر التحقق مؤقتاً. حاول لاحقاً.'

    if body.get('success'):
        return True, ''
    codes = body.get('error-codes') or []
    logger.info('Turnstile failed: %s', codes)
    return False, 'فشل التحقق. حدّث الصفحة وحاول مرة أخرى.'


# ——— Login rate limit + captcha threshold (per portal + IP + username) ———

def _norm_username(username: str) -> str:
    return (username or '').strip()


def _uh(username: str) -> str:
    return hashlib.sha256(_norm_username(username).lower().encode('utf-8')).hexdigest()[:40]


def _login_fail_key(portal: str, username: str, ip: str) -> str:
    return f'lf:v2:{portal}:{_uh(username)}:{ip}'


def _login_lock_key(portal: str, username: str, ip: str) -> str:
    return f'll:v2:{portal}:{_uh(username)}:{ip}'


def _login_ip_fail_key(portal: str, ip: str) -> str:
    """فشل من نفس IP لنفس البوابة (لإظهار Turnstile بدون معرفة اسم المستخدم مسبقاً)."""
    return f'lfip:v2:{portal}:{ip}'


def is_login_locked(portal: str, request: HttpRequest, username: str) -> bool:
    ip = client_ip(request)
    return bool(cache.get(_login_lock_key(portal, username, ip)))


def login_failure_counts(portal: str, request: HttpRequest, username: str) -> Tuple[int, int]:
    """يُرجع (فشل لهذا المستخدم+IP، فشل إجمالي من IP لهذه البوابة)."""
    ip = client_ip(request)
    u = int(cache.get(_login_fail_key(portal, username, ip)) or 0)
    ip_only = int(cache.get(_login_ip_fail_key(portal, ip)) or 0)
    return u, ip_only


def record_login_failure(portal: str, request: HttpRequest, username: str) -> None:
    ip = client_ip(request)
    fk = _login_fail_key(portal, username, ip)
    window = int(getattr(settings, 'LOGIN_FAILURE_WINDOW_SEC', 3600))
    max_fails = int(getattr(settings, 'LOGIN_FAILURE_MAX', 5))
    lock_sec = int(getattr(settings, 'LOGIN_FAILURE_LOCK_SECONDS', 900))

    try:
        cache.incr(fk)
    except ValueError:
        cache.set(fk, 1, window)

    ik = _login_ip_fail_key(portal, ip)
    try:
        cache.incr(ik)
    except ValueError:
        cache.set(ik, 1, window)

    fails = int(cache.get(fk) or 0)
    if fails >= max_fails:
        cache.set(_login_lock_key(portal, username, ip), 1, lock_sec)
        logger.info('Login locked portal=%s user_hash=%s ip=%s', portal, _uh(username), ip)


def clear_login_failure(portal: str, request: HttpRequest, username: str) -> None:
    ip = client_ip(request)
    cache.delete(_login_fail_key(portal, username, ip))
    cache.delete(_login_lock_key(portal, username, ip))
    cache.delete(_login_ip_fail_key(portal, ip))


def login_needs_turnstile(portal: str, request: HttpRequest) -> bool:
    """بعد N فشل من نفس IP لنفس البوابة."""
    if not turnstile_configured():
        return False
    ip = client_ip(request)
    n = int(getattr(settings, 'LOGIN_CAPTCHA_AFTER_FAILS', 3))
    ip_fails = int(cache.get(_login_ip_fail_key(portal, ip)) or 0)
    return ip_fails >= n


def locked_message() -> str:
    sec = int(getattr(settings, 'LOGIN_FAILURE_LOCK_SECONDS', 900))
    mins = max(1, sec // 60)
    return f'تم تجاوز عدد محاولات الدخول. حاول مرة أخرى بعد نحو {mins} دقيقة.'


# ——— Registration OTP rate (email + IP) ———

_REG_EMAIL_MAX = int(os.environ.get('REGISTER_OTP_EMAIL_MAX', '5'))
_REG_IP_MAX = int(os.environ.get('REGISTER_OTP_IP_MAX', '20'))
_REG_WINDOW = 3600


def _reg_email_key(email: str) -> str:
    h = hashlib.sha256(email.lower().strip().encode('utf-8')).hexdigest()[:40]
    return f'regotp:v1:e:{h}'


def _reg_ip_key(ip: str) -> str:
    return f'regotp:v1:i:{ip}'


# ——— OTP: حد إرسال لكل جلسة متصفح (إرسال أول + 3 إعادات = 4 كحد أقصى) ———

MAX_OTP_SENDS_PER_CHALLENGE = int(os.environ.get('MAX_OTP_SENDS_PER_CHALLENGE', '4'))


def otp_send_session_key_reg() -> str:
    return 'otp_send_count:reg'


def otp_send_session_key_pw_portal(portal: str) -> str:
    return f'otp_send_count:pw:{(portal or "").strip().lower()}'


def otp_send_session_key_deliver(label_code: str) -> str:
    code = (label_code or '').strip().upper()
    return f'otp_send_count:deliver:{code}'


def otp_reset_send_count(request: HttpRequest, key: str) -> None:
    request.session.pop(key, None)
    request.session.modified = True


def otp_can_send_in_challenge(request: HttpRequest, key: str) -> bool:
    return int(request.session.get(key) or 0) < MAX_OTP_SENDS_PER_CHALLENGE


def otp_record_successful_send(request: HttpRequest, key: str) -> None:
    n = int(request.session.get(key) or 0)
    request.session[key] = n + 1
    request.session.modified = True


def otp_sends_remaining(request: HttpRequest, key: str) -> int:
    n = int(request.session.get(key) or 0)
    return max(0, MAX_OTP_SENDS_PER_CHALLENGE - n)


def register_otp_rate_allow(request: HttpRequest, email: str) -> bool:
    email = (email or '').strip().lower()
    if not email:
        return True
    ip = client_ip(request)
    ek, ik = _reg_email_key(email), _reg_ip_key(ip)

    def _g(k):
        return int(cache.get(k) or 0)

    if _g(ek) >= _REG_EMAIL_MAX or _g(ik) >= _REG_IP_MAX:
        return False
    try:
        cache.incr(ek)
    except ValueError:
        cache.set(ek, 1, _REG_WINDOW)
    try:
        cache.incr(ik)
    except ValueError:
        cache.set(ik, 1, _REG_WINDOW)
    return True


# ——— Login alert email (store customers) ———

def send_login_alert_if_enabled(user, request: HttpRequest) -> None:
    if not getattr(settings, 'SEND_LOGIN_ALERT_EMAIL', False):
        return
    if not user.email:
        return
    ip = client_ip(request)
    ua = (request.META.get('HTTP_USER_AGENT') or '')[:200]
    subject = 'تنبيه: تسجيل دخول إلى حسابك'
    body = (
        f'مرحباً {user.username},\n\n'
        f'تم تسجيل الدخول إلى حسابك في المتجر.\n'
        f'وقت تقريبي: {request.META.get("HTTP_DATE", "")}\n'
        f'عنوان IP: {ip}\n'
        f'المتصفح: {ua}\n\n'
        f'إن لم تكن أنت، غيّر كلمة المرور فوراً.\n'
    )
    try:
        send_mail(
            subject,
            body,
            getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            [user.email],
            fail_silently=True,
        )
    except Exception:
        logger.exception('send_login_alert failed')

