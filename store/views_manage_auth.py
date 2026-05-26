"""مصادقة لوحة الإدارة — تسجيل الدخول، استعادة كلمة المرور، تسجيل الخروج."""

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from .models import UserProfile
from .password_reset_flow import (
    MSG_EMAIL_REQUIRED,
    MSG_NO_ACCOUNT,
    MSG_OTP_RESTART,
    MSG_OTP_SENT,
    MSG_RATE_LIMITED,
    get_active_password_reset_otp,
    get_context_for_new_password_page,
    password_reset_otp_resend_response,
    process_forgot_password_step1,
    try_set_new_password_after_verified_otp,
    try_verify_password_reset_otp_step,
)


def manage_login(request):
    from .security_services import (
        clear_login_failure,
        is_login_locked,
        locked_message,
        login_needs_turnstile,
        record_login_failure,
        verify_turnstile,
    )

    request._security_portal = 'manage'

    if request.user.is_authenticated and request.user.is_staff:
        try:
            account_type = getattr(request.user.profile, 'account_type', '') or ''
        except Exception:
            account_type = ''
        if account_type in (
            UserProfile.ACCOUNT_CUSTOMER_SERVICE,
            UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER,
        ) and not request.user.is_superuser:
            return redirect('manage:support_portal')
        return redirect('manage:dashboard')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if username and is_login_locked('manage', request, username):
            messages.error(request, locked_message())
            return render(request, 'manage/login.html')
        if login_needs_turnstile('manage', request):
            ok, err = verify_turnstile(request)
            if not ok:
                messages.error(request, err)
                return render(request, 'manage/login.html')
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            clear_login_failure('manage', request, username)
            login(request, user)
            try:
                account_type = getattr(user.profile, 'account_type', '') or ''
            except Exception:
                account_type = ''
            if account_type in (
                UserProfile.ACCOUNT_CUSTOMER_SERVICE,
                UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER,
            ) and not user.is_superuser:
                return redirect('manage:support_portal')
            next_url = request.GET.get('next') or request.POST.get('next') or 'manage:dashboard'
            return redirect(next_url)
        if username:
            record_login_failure('manage', request, username)
        messages.error(request, _('اسم مستخدم أو كلمة مرور غير صحيحة.'))
    return render(request, 'manage/login.html')


def forgot_password(request):
    """نسيت كلمة المرور للوحة الإدارة (OTP للبريد)."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('manage:dashboard')

    if request.method == 'POST':
        from .security_services import turnstile_configured, verify_turnstile
        if turnstile_configured():
            ok, err = verify_turnstile(request)
            if not ok:
                messages.error(request, err)
                return redirect('manage:forgot_password')

        outcome, _ = process_forgot_password_step1(
            request,
            email_raw=request.POST.get('email') or '',
            session_otp_key='manage_pw_reset_otp_id',
            session_verified_key='manage_pw_reset_otp_verified',
            resolve_user=lambda e: User.objects.filter(email__iexact=e, is_staff=True).first(),
            mail_context='لوحة الإدارة — إعادة تعيين كلمة المرور',
        )
        if outcome == 'empty':
            messages.error(request, MSG_EMAIL_REQUIRED)
        elif outcome == 'rate':
            messages.error(request, MSG_RATE_LIMITED)
        elif outcome == 'otp':
            from .security_services import (
                otp_record_successful_send,
                otp_reset_send_count,
                otp_send_session_key_pw_portal,
            )

            k_pw = otp_send_session_key_pw_portal('manage')
            otp_reset_send_count(request, k_pw)
            otp_record_successful_send(request, k_pw)
            messages.success(request, MSG_OTP_SENT)
            return redirect('manage:forgot_password_otp')
        elif outcome == 'no_user':
            messages.error(request, MSG_NO_ACCOUNT)
        return redirect('manage:forgot_password')

    return render(request, 'manage/forgot_password.html')


def forgot_password_otp(request):
    from .security_services import otp_send_session_key_pw_portal, otp_sends_remaining

    otp_obj = get_active_password_reset_otp(request, 'manage_pw_reset_otp_id')
    if not otp_obj:
        messages.error(request, MSG_OTP_RESTART)
        return redirect('manage:forgot_password')

    if request.session.get('manage_pw_reset_otp_verified'):
        return redirect('manage:forgot_password_new_password')

    if request.method == 'POST' and (request.POST.get('otp_action') or '').strip() == 'resend':
        return password_reset_otp_resend_response(
            request,
            otp_obj,
            portal='manage',
            mail_context='لوحة الإدارة — إعادة تعيين كلمة المرور',
            url_otp='manage:forgot_password_otp',
        )

    resp = try_verify_password_reset_otp_step(
        request,
        otp_obj,
        session_otp_key='manage_pw_reset_otp_id',
        session_verified_key='manage_pw_reset_otp_verified',
        url_forgot='manage:forgot_password',
        url_otp='manage:forgot_password_otp',
        url_new_password='manage:forgot_password_new_password',
    )
    if resp:
        return resp

    return render(
        request,
        'manage/forgot_password_otp.html',
        {
            'email': otp_obj.email,
            'otp_sends_remaining': otp_sends_remaining(request, otp_send_session_key_pw_portal('manage')),
        },
    )


def forgot_password_new_password(request):
    redir, otp_obj = get_context_for_new_password_page(
        request,
        session_otp_key='manage_pw_reset_otp_id',
        session_verified_key='manage_pw_reset_otp_verified',
        url_forgot='manage:forgot_password',
        url_otp='manage:forgot_password_otp',
    )
    if redir:
        return redir

    resp = try_set_new_password_after_verified_otp(
        request,
        otp_obj,
        session_otp_key='manage_pw_reset_otp_id',
        session_verified_key='manage_pw_reset_otp_verified',
        url_forgot='manage:forgot_password',
        url_otp='manage:forgot_password_otp',
        url_new_password='manage:forgot_password_new_password',
        url_login='manage:login',
        success_message=_('تم تغيير كلمة المرور. سجّل دخولك الآن.'),
    )
    if resp:
        return resp

    return render(request, 'manage/forgot_password_new.html', {'email': otp_obj.email})


def manage_logout(request):
    logout(request)
    return redirect('manage:login')
