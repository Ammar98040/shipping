"""
بوابة شركة الشحن (شركة السريع للشحن) — نظام منفصل عن /manage/
المندوبون يدخلون هنا لتحديث الشحنات وتسليم الطلبات.
"""
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from .forms_profile import UserProfileForm
from .integrations.fake_shipping import apply_shipping_update
from .internal_chat_service import apply_internal_chat_routing, create_internal_chat_messages
from .models import (
    DeliveryOTP,
    InternalSupportMessage,
    InternalSupportThread,
    LabelCode,
    Order,
    Shipment,
    UserProfile,
)
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
from .upload_validation import chat_image_error_message, validate_chat_image_files


def _shipment_ready_for_courier_deliver(shipment):
    """
    تسليم العميل مسموح فقط بعد تسجيل «استلام من المتجر» (أو مراحل لاحقة قبل التسليم).
    المرحلة created = لم يُستلم من المتجر بعد.
    """
    return shipment.status in (
        Shipment.STATUS_PICKED,
        Shipment.STATUS_IN_TRANSIT,
        Shipment.STATUS_OUT_FOR_DELIVERY,
    )


def _used_waybill_message_for_courier(shipment, action):
    """
    رسالة موحدة عند إعادة استخدام نفس كود البوليصة.
    action: pickup | deliver
    """
    if action == 'pickup':
        if shipment.status == Shipment.STATUS_PICKED:
            return str(_('هذا الكود مستخدم بالفعل — تم استلام الشحنة من المتجر مسبقاً.'))
        if shipment.status == Shipment.STATUS_IN_TRANSIT:
            return str(_('هذا الكود مستخدم بالفعل — الشحنة بالفعل في الطريق.'))
        if shipment.status == Shipment.STATUS_OUT_FOR_DELIVERY:
            return str(_('هذا الكود مستخدم بالفعل — الشحنة خرجت للتسليم مسبقاً.'))
        if shipment.status == Shipment.STATUS_DELIVERED:
            return str(_('هذا الكود مستخدم بالفعل — تم تسليم الشحنة للعميل مسبقاً.'))
        if shipment.status == Shipment.STATUS_FAILED:
            return str(_('لا يمكن استخدام هذا الكود: الشحنة في حالة تعثر.'))
        return str(_('هذا الكود مستخدم بالفعل — لا يمكن إعادة استلام الشحنة في الحالة الحالية.'))

    # deliver
    if shipment.status == Shipment.STATUS_DELIVERED:
        return str(_('هذا الكود مستخدم بالفعل — تم تسليم الشحنة للعميل مسبقاً.'))
    if shipment.status == Shipment.STATUS_CREATED:
        return str(_(
            'لا يمكن تسليم الطلب قبل تسجيل استلام الشحنة من المتجر. '
            'الترتيب: أولاً صفحة «استلام من المتجر» ومسح نفس كود البوليصة، ثم «تسليم للعميل».'
        ))
    if shipment.status == Shipment.STATUS_FAILED:
        return str(_('لا يمكن التسليم: الشحنة في حالة تعثر. تواصل مع الإدارة.'))
    return str(_('لا يمكن تنفيذ التسليم في الحالة الحالية للشحنة.'))


_SHIPPING_PORTAL_ROLES = (
    UserProfile.ACCOUNT_COURIER,
    UserProfile.ACCOUNT_SHIPPING_MANAGER,
)

_SHIPPING_ROLE_MAP = {
    UserProfile.ACCOUNT_COURIER:          'shipping:dashboard',
    UserProfile.ACCOUNT_SHIPPING_MANAGER: 'shipping:manager_dashboard',
}

_SHIPPING_WAITING_TEXT = 'تم استلام رسالتك. سيتم الرد عليك من مسؤول الشحن حالما يصبح متاحاً.'


def _courier_required(view_func):
    """متوافق للخلف — يحمي views المندوبين (courier فقط)."""
    return _shipping_portal_required(view_func, roles=(UserProfile.ACCOUNT_COURIER,))


def _shipping_portal_required(view_func, roles=None):
    """يقبل courier و shipping_manager معاً."""
    allowed = roles or _SHIPPING_PORTAL_ROLES

    def wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('shipping:login')
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.account_type not in allowed:
            messages.error(request, _('غير مصرح لك بالدخول إلى بوابة الشحن.'))
            return redirect('shipping:login')
        return view_func(request, *args, **kwargs)
    wrap.__name__ = getattr(view_func, '__name__', 'view')
    return wrap


def _shipping_manager_required(view_func):
    """يقبل shipping_manager فقط."""
    def wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('shipping:login')
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.account_type != UserProfile.ACCOUNT_SHIPPING_MANAGER:
            messages.error(request, _('هذه الصفحة مخصصة لمسؤول الشحن فقط.'))
            return redirect('shipping:login')
        return view_func(request, *args, **kwargs)
    wrap.__name__ = getattr(view_func, '__name__', 'view')
    return wrap


def shipping_login(request):
    from .security_services import (
        clear_login_failure,
        is_login_locked,
        locked_message,
        login_needs_turnstile,
        record_login_failure,
        verify_turnstile,
    )

    request._security_portal = 'shipping'

    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.account_type in _SHIPPING_PORTAL_ROLES:
            return redirect(_SHIPPING_ROLE_MAP.get(profile.account_type, 'shipping:dashboard'))

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if username and is_login_locked('shipping', request, username):
            messages.error(request, locked_message())
            return render(request, 'shipping/login.html')
        if login_needs_turnstile('shipping', request):
            ok, err = verify_turnstile(request)
            if not ok:
                messages.error(request, err)
                return render(request, 'shipping/login.html')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            profile = getattr(user, 'profile', None)
            if profile and profile.account_type in _SHIPPING_PORTAL_ROLES:
                clear_login_failure('shipping', request, username)
                login(request, user)
                raw_next = (request.GET.get('next') or request.POST.get('next') or '').strip()
                from django.utils.http import url_has_allowed_host_and_scheme
                if raw_next and raw_next.startswith('/') and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}):
                    return redirect(raw_next)
                return redirect(_SHIPPING_ROLE_MAP.get(profile.account_type, 'shipping:dashboard'))
        if username:
            record_login_failure('shipping', request, username)
        messages.error(request, _('اسم مستخدم أو كلمة مرور غير صحيحة.'))
    return render(request, 'shipping/login.html')


def shipping_logout(request):
    logout(request)
    return redirect('shipping:login')


def forgot_password(request):
    """نسيت كلمة المرور لبوابة الشحن (OTP للبريد)."""
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.account_type in _SHIPPING_PORTAL_ROLES:
            return redirect(_SHIPPING_ROLE_MAP.get(profile.account_type, 'shipping:dashboard'))

    if request.method == 'POST':
        from .security_services import turnstile_configured, verify_turnstile
        if turnstile_configured():
            ok, err = verify_turnstile(request)
            if not ok:
                messages.error(request, err)
                return redirect('shipping:forgot_password')

        outcome, _ = process_forgot_password_step1(
            request,
            email_raw=request.POST.get('email') or '',
            session_otp_key='shipping_pw_reset_otp_id',
            session_verified_key='shipping_pw_reset_otp_verified',
            resolve_user=lambda e: User.objects.filter(
                email__iexact=e, profile__account_type=UserProfile.ACCOUNT_COURIER
            ).first(),
            mail_context='بوابة الشحن — إعادة تعيين كلمة المرور',
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

            k_pw = otp_send_session_key_pw_portal('shipping')
            otp_reset_send_count(request, k_pw)
            otp_record_successful_send(request, k_pw)
            messages.success(request, MSG_OTP_SENT)
            return redirect('shipping:forgot_password_otp')
        elif outcome == 'no_user':
            messages.error(request, MSG_NO_ACCOUNT)
        return redirect('shipping:forgot_password')

    return render(request, 'shipping/forgot_password.html')


def forgot_password_otp(request):
    from .security_services import otp_send_session_key_pw_portal, otp_sends_remaining

    otp_obj = get_active_password_reset_otp(request, 'shipping_pw_reset_otp_id')
    if not otp_obj:
        messages.error(request, MSG_OTP_RESTART)
        return redirect('shipping:forgot_password')

    if request.session.get('shipping_pw_reset_otp_verified'):
        return redirect('shipping:forgot_password_new_password')

    if request.method == 'POST' and (request.POST.get('otp_action') or '').strip() == 'resend':
        return password_reset_otp_resend_response(
            request,
            otp_obj,
            portal='shipping',
            mail_context='بوابة الشحن — إعادة تعيين كلمة المرور',
            url_otp='shipping:forgot_password_otp',
        )

    resp = try_verify_password_reset_otp_step(
        request,
        otp_obj,
        session_otp_key='shipping_pw_reset_otp_id',
        session_verified_key='shipping_pw_reset_otp_verified',
        url_forgot='shipping:forgot_password',
        url_otp='shipping:forgot_password_otp',
        url_new_password='shipping:forgot_password_new_password',
    )
    if resp:
        return resp

    return render(
        request,
        'shipping/forgot_password_otp.html',
        {
            'email': otp_obj.email,
            'otp_sends_remaining': otp_sends_remaining(request, otp_send_session_key_pw_portal('shipping')),
        },
    )


def forgot_password_new_password(request):
    redir, otp_obj = get_context_for_new_password_page(
        request,
        session_otp_key='shipping_pw_reset_otp_id',
        session_verified_key='shipping_pw_reset_otp_verified',
        url_forgot='shipping:forgot_password',
        url_otp='shipping:forgot_password_otp',
    )
    if redir:
        return redir

    resp = try_set_new_password_after_verified_otp(
        request,
        otp_obj,
        session_otp_key='shipping_pw_reset_otp_id',
        session_verified_key='shipping_pw_reset_otp_verified',
        url_forgot='shipping:forgot_password',
        url_otp='shipping:forgot_password_otp',
        url_new_password='shipping:forgot_password_new_password',
        url_login='shipping:login',
        success_message=_('تم تغيير كلمة المرور. سجّل دخولك الآن.'),
    )
    if resp:
        return resp

    return render(request, 'shipping/forgot_password_new.html', {'email': otp_obj.email})


@_courier_required
def dashboard(request):
    profile_obj, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_COURIER}
    )
    qs = Shipment.objects.select_related('order', 'courier').filter(courier=request.user).order_by('-updated_at')
    available_count = Shipment.objects.filter(
        courier__isnull=True,
        order__status=Order.STATUS_READY,
        status=Shipment.STATUS_CREATED
    ).count()
    stats = {
        'all': qs.count(),
        'created': qs.filter(status=Shipment.STATUS_CREATED).count(),
        'picked': qs.filter(status=Shipment.STATUS_PICKED).count(),
        'in_transit': qs.filter(status=Shipment.STATUS_IN_TRANSIT).count(),
        'out_for_delivery': qs.filter(status=Shipment.STATUS_OUT_FOR_DELIVERY).count(),
        'delivered': qs.filter(status=Shipment.STATUS_DELIVERED).count(),
        'failed': qs.filter(status=Shipment.STATUS_FAILED).count(),
    }
    recent = qs[:10]
    return render(request, 'shipping/dashboard.html', {
        'stats': stats,
        'recent': recent,
        'available_count': available_count,
        'profile_obj': profile_obj,
    })


@_courier_required
def set_availability(request):
    if request.method != 'POST':
        return redirect('shipping:dashboard')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_COURIER}
    )
    force_value = (request.POST.get('is_available') or '').strip().lower()
    if force_value in ('1', 'true', 'yes', 'on'):
        profile_obj.is_available = True
    elif force_value in ('0', 'false', 'no', 'off'):
        profile_obj.is_available = False
    else:
        profile_obj.is_available = not profile_obj.is_available
    profile_obj.availability_updated_at = timezone.now()
    profile_obj.availability_updated_by = request.user
    profile_obj.save(update_fields=['is_available', 'availability_updated_at', 'availability_updated_by'])
    if is_ajax:
        return JsonResponse({
            'success': True,
            'is_available': bool(profile_obj.is_available),
            'badge_text': '🟢 متوفر' if profile_obj.is_available else '⚪ غير متوفر',
            'button_text': 'إيقاف التوفر مؤقتاً' if profile_obj.is_available else 'أنا متوفر الآن',
            'button_class': 'btn-secondary' if profile_obj.is_available else 'btn-primary',
            'availability_updated_at': profile_obj.availability_updated_at.strftime('%Y-%m-%d %H:%M') if profile_obj.availability_updated_at else '',
            'updated_at': profile_obj.availability_updated_at.isoformat() if profile_obj.availability_updated_at else '',
        })
    messages.success(request, _('تم تحديث حالة التوفر بنجاح.'))
    return redirect(request.POST.get('next') or 'shipping:dashboard')


@_courier_required
@require_GET
def my_availability_live(request):
    """مزامنة حالة التوفر مع لوحة الإدارة بدون ريفرش."""
    profile_obj, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_COURIER},
    )
    return JsonResponse({
        'success': True,
        'is_available': bool(profile_obj.is_available),
        'badge_text': '🟢 متوفر' if profile_obj.is_available else '⚪ غير متوفر',
        'button_text': 'إيقاف التوفر مؤقتاً' if profile_obj.is_available else 'أنا متوفر الآن',
        'button_class': 'btn-secondary' if profile_obj.is_available else 'btn-primary',
        'updated_at': profile_obj.availability_updated_at.isoformat() if profile_obj.availability_updated_at else '',
    })


@_courier_required
def available_jobs(request):
    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_COURIER}
    )
    if not profile_obj.is_available:
        messages.info(request, _('أنت غير متوفر حالياً، لذلك لن تصلك مهام جديدة حتى تعيد الحالة إلى متوفر.'))
        items = Shipment.objects.none()
        status_filter = request.GET.get('status', '').strip()
        q = request.GET.copy()
        q.pop('page', None)
        return render(request, 'shipping/available_jobs.html', {
            'items': items,
            'status_filter': status_filter,
            'status_choices': Shipment.STATUS_CHOICES,
            'query_string': q.urlencode(),
        })

    """
    طلبات توصيل جديدة (شحنات غير مسندة).
    المندوب يستطيع قبولها فتُسند له.
    """
    status_filter = request.GET.get('status', '').strip()
    items = Shipment.objects.select_related('order').filter(
        courier__isnull=True,
        order__status=Order.STATUS_READY,
        status=Shipment.STATUS_CREATED
    )
    if status_filter:
        items = items.filter(status=status_filter)
    items = items.order_by('-updated_at')

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'shipping/available_jobs.html', {
        'items': items,
        'status_filter': status_filter,
        'status_choices': Shipment.STATUS_CHOICES,
        'query_string': q.urlencode(),
    })


@_courier_required
def available_jobs_live(request):
    """تغذية حيّة خفيفة لطلبات الشحن غير المسندة."""
    status_filter = request.GET.get('status', '').strip()
    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_COURIER}
    )
    if not profile_obj.is_available:
        return JsonResponse({'success': True, 'items': []})

    items = (
        Shipment.objects.select_related('order')
        .filter(
            courier__isnull=True,
            order__status=Order.STATUS_READY,
            status=Shipment.STATUS_CREATED
        )
        .order_by('-updated_at')[:50]
    )
    if status_filter:
        items = items.filter(status=status_filter)
    payload = []
    for s in items:
        o = s.order
        payload.append({
            'id': s.id,
            'order_id': o.id if o else '',
            'customer_name': (o.customer_name if o else '') or '',
            'customer_phone': (o.customer_phone if o else '') or '',
            'address': ((o.address if o else '') or '')[:90],
            'tracking_number': s.tracking_number or '-',
            'status_display': s.get_status_display(),
            'updated_at': s.updated_at.strftime('%Y-%m-%d %H:%M') if s.updated_at else '',
            'accept_url': reverse('shipping:accept_job', args=[s.id]),
        })
    return JsonResponse({'success': True, 'items': payload})


@_courier_required
def accept_job(request, pk):
    """قبول شحنة غير مسندة وإسنادها لهذا المندوب"""
    if request.method != 'POST':
        return redirect('shipping:available_jobs')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_COURIER}
    )
    if not profile_obj.is_available:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('لا يمكنك قبول مهام جديدة لأن حالتك غير متوفر.'))}, status=400)
        messages.error(request, _('لا يمكنك قبول مهام جديدة لأن حالتك غير متوفر.'))
        return redirect('shipping:available_jobs')

    shipment = get_object_or_404(Shipment.objects.select_related('order'), pk=pk)
    if shipment.courier_id is not None:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('هذه الشحنة تم إسنادها مسبقاً.'))}, status=400)
        messages.error(request, _('هذه الشحنة تم إسنادها مسبقاً.'))
        return redirect('shipping:available_jobs')

    shipment.courier = request.user
    shipment.save(update_fields=['courier', 'updated_at'])
    if is_ajax:
        return JsonResponse({
            'success': True,
            'shipment_id': shipment.id,
            'detail_url': reverse('shipping:shipment_detail', args=[pk]),
            'message': str(_('تم قبول الشحنة وإسنادها لك.')),
        })
    messages.success(request, _('تم قبول الشحنة وإسنادها لك.'))
    return redirect('shipping:shipment_detail', pk=pk)


@_courier_required
def shipments_list(request):
    status_filter = request.GET.get('status', '').strip()
    items = Shipment.objects.select_related('order', 'courier').filter(courier=request.user)
    if status_filter:
        items = items.filter(status=status_filter)

    items = items.order_by('-updated_at')
    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'shipping/shipments_list.html', {
        'items': items,
        'status_filter': status_filter,
        'status_choices': Shipment.STATUS_CHOICES,
        'query_string': q.urlencode(),
    })


@_courier_required
def shipment_detail(request, pk):
    shipment = get_object_or_404(
        Shipment.objects.select_related('order', 'courier'),
        pk=pk, courier=request.user
    )

    return render(request, 'shipping/shipment_detail.html', {'shipment': shipment})


@_courier_required
def shipment_detail_poll(request, pk):
    """GET — polling خفيف لحالة الشحنة في بوابة الشحن بدون reload."""
    shipment = get_object_or_404(
        Shipment.objects.select_related('order'),
        pk=pk, courier=request.user
    )
    signature = '|'.join([
        str(shipment.status or ''),
        str(shipment.order.status or ''),
        shipment.updated_at.isoformat() if shipment.updated_at else '',
    ])
    return JsonResponse({
        'success': True,
        'signature': signature,
        'shipment_status': shipment.status or '',
        'shipment_status_display': shipment.get_status_display(),
        'order_status': shipment.order.status or '',
        'order_status_display': shipment.order.get_status_display(),
        'is_delivered': shipment.status == 'delivered',
    })


@_courier_required
def profile(request):
    """ملف المندوب الشخصي داخل بوابة الشحن."""
    user = request.user
    profile_obj = getattr(user, 'profile', None)
    if profile_obj is None:
        profile_obj = UserProfile.objects.create(user=user, account_type=UserProfile.ACCOUNT_COURIER)

    profile_form = UserProfileForm(user=user, instance=profile_obj)
    password_form = PasswordChangeForm(user=user)
    for f in password_form.fields.values():
        f.widget.attrs.update({'class': 'profile-input'})

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        action = (request.POST.get('action') or '').strip()

        if action == 'profile':
            profile_form = UserProfileForm(request.POST, request.FILES, user=user, instance=profile_obj)
            if profile_form.is_valid():
                profile_form.save()
                user.first_name = profile_form.cleaned_data.get('first_name') or ''
                user.last_name = profile_form.cleaned_data.get('last_name') or ''
                user.email = profile_form.cleaned_data.get('email') or ''
                user.save(update_fields=['first_name', 'last_name', 'email'])
                if is_ajax:
                    avatar_url = profile_obj.avatar.url if getattr(profile_obj, 'avatar', None) else ''
                    display_name = (user.first_name or user.get_full_name() or user.username).strip() or user.username
                    return JsonResponse({
                        'success': True,
                        'action': 'profile',
                        'message': str(_('تم تحديث الملف الشخصي بنجاح.')),
                        'avatar_url': avatar_url,
                        'display_name': display_name,
                    })
                messages.success(request, _('تم تحديث الملف الشخصي بنجاح.'))
                return redirect('shipping:profile')
            if is_ajax:
                return JsonResponse({'success': False, 'action': 'profile', 'error': str(_('تحقق من الحقول وأعد المحاولة.'))}, status=400)
            messages.error(request, _('تحقق من الحقول وأعد المحاولة.'))

        elif action == 'password':
            password_form = PasswordChangeForm(user=user, data=request.POST)
            for f in password_form.fields.values():
                f.widget.attrs.update({'class': 'profile-input'})
            if password_form.is_valid():
                u = password_form.save()
                update_session_auth_hash(request, u)
                if is_ajax:
                    return JsonResponse({'success': True, 'action': 'password', 'message': str(_('تم تغيير كلمة المرور بنجاح.'))})
                messages.success(request, _('تم تغيير كلمة المرور بنجاح.'))
                return redirect('shipping:profile')
            if is_ajax:
                return JsonResponse({'success': False, 'action': 'password', 'error': str(_('تعذر تغيير كلمة المرور. تحقق من البيانات.'))}, status=400)
            messages.error(request, _('تعذر تغيير كلمة المرور. تحقق من البيانات.'))

    return render(request, 'shipping/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
        'profile_obj': profile_obj,
    })


@_courier_required
def scan_hub(request):
    """مركز مسار البوليصة: اختيار «استلام من المتجر» أو «تسليم للعميل» (صفحتان منفصلتان)."""
    show_delivered_ok = bool(request.session.pop('shipping_scan_show_delivered_ok', False))
    return render(request, 'shipping/scan_hub.html', {'show_delivered_ok': show_delivered_ok})


@_courier_required
def scan_pickup(request):
    """مسح البوليصة — استلام الشحنة من المتجر فقط."""
    return render(request, 'shipping/scan.html', {'scan_action': 'pickup'})


@_courier_required
def scan_deliver(request):
    """مسح البوليصة — تسليم للعميل (OTP) فقط."""
    return render(request, 'shipping/scan.html', {'scan_action': 'deliver'})


@_courier_required
def scan_consume(request):
    """قراءة كود البوليصة وتطبيق الإجراء."""
    if request.method != 'POST':
        return redirect('shipping:scan')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    action = (request.POST.get('action') or '').strip()
    raw = (request.POST.get('code') or '').strip()
    code = raw.replace('DLBK:', '').strip().upper()
    if not code:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('أدخل الكود.'))}, status=400)
        messages.error(request, _('أدخل الكود.'))
        return redirect('shipping:scan_pickup' if action == 'pickup' else 'shipping:scan_deliver')

    label = LabelCode.objects.select_related('order', 'shipment').filter(code=code).first()
    if not label:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('الكود غير صحيح.'))}, status=404)
        messages.error(request, _('الكود غير صحيح.'))
        return redirect('shipping:scan')

    # Ensure shipment exists
    shipment = label.shipment
    if not shipment:
        try:
            shipment = label.order.shipment
        except Exception:
            shipment = None
    if not shipment:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('لا توجد شحنة لهذا الطلب بعد.'))}, status=404)
        messages.error(request, _('لا توجد شحنة لهذا الطلب بعد.'))
        return redirect('shipping:scan')

    # Must be assigned to this courier (or accepted first)
    if shipment.courier_id != request.user.id:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('هذه الشحنة غير مسندة لك.'))}, status=403)
        messages.error(request, _('هذه الشحنة غير مسندة لك.'))
        return redirect('shipping:scan')

    if action == 'pickup':
        if shipment.status != Shipment.STATUS_CREATED:
            used_msg = _used_waybill_message_for_courier(shipment, 'pickup')
            if is_ajax:
                return JsonResponse({'success': False, 'error': used_msg}, status=400)
            messages.error(request, used_msg)
            return redirect('shipping:scan_pickup')
        try:
            apply_shipping_update(
                shipment=shipment,
                new_status=Shipment.STATUS_PICKED,
                message='Courier scan: picked up from store',
                payload={'via': 'barcode_scan', 'action': 'pickup', 'courier': request.user.username},
                actor=request.user
            )
            label.last_used_at = timezone.now()
            label.save(update_fields=['last_used_at'])
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': str(_('تم الاستلام بنجاح عبر الباركود.')),
                    'redirect_url': reverse('shipping:shipment_detail', args=[shipment.id]),
                })
            messages.success(request, _('تم الاستلام بنجاح عبر الباركود.'))
            return redirect('shipping:shipment_detail', pk=shipment.id)
        except Exception as e:
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(e), 'redirect_url': reverse('shipping:shipment_detail', args=[shipment.id])}, status=400)
            messages.error(request, str(e))
            return redirect('shipping:shipment_detail', pk=shipment.id)

    if action == 'deliver':
        if shipment.status == Shipment.STATUS_DELIVERED:
            used_msg = _used_waybill_message_for_courier(shipment, 'deliver')
            if is_ajax:
                return JsonResponse({'success': False, 'error': used_msg}, status=400)
            messages.error(request, used_msg)
            return redirect('shipping:scan_deliver')
        if shipment.status == Shipment.STATUS_CREATED:
            used_msg = _used_waybill_message_for_courier(shipment, 'deliver')
            if is_ajax:
                return JsonResponse({'success': False, 'error': used_msg}, status=400)
            messages.error(request, used_msg)
            return redirect('shipping:scan_deliver')
        if shipment.status == Shipment.STATUS_FAILED:
            used_msg = _used_waybill_message_for_courier(shipment, 'deliver')
            if is_ajax:
                return JsonResponse({'success': False, 'error': used_msg}, status=400)
            messages.error(request, used_msg)
            return redirect('shipping:scan_deliver')
        if not _shipment_ready_for_courier_deliver(shipment):
            used_msg = _used_waybill_message_for_courier(shipment, 'deliver')
            if is_ajax:
                return JsonResponse({'success': False, 'error': used_msg}, status=400)
            messages.error(request, used_msg)
            return redirect('shipping:scan_deliver')
        request.session['deliver_code'] = label.code
        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': str(_('تم التحقق من البوليصة. انتقل الآن لتأكيد OTP.')),
                'redirect_url': reverse('shipping:deliver_otp'),
            })
        return redirect('shipping:deliver_otp')

    if is_ajax:
        return JsonResponse({'success': False, 'error': str(_('إجراء غير صحيح.'))}, status=400)
    messages.error(request, _('إجراء غير صحيح.'))
    return redirect('shipping:scan')


@_courier_required
def deliver_otp(request):
    """صفحة إرسال/تحقق OTP لتسليم الشحنة."""
    code = (request.session.get('deliver_code') or '').strip().upper()
    if not code:
        messages.error(request, _('قم بمسح الباركود من صفحة «تسليم للعميل» أولاً.'))
        return redirect('shipping:scan_deliver')

    label = LabelCode.objects.select_related('order', 'shipment').filter(code=code).first()
    if not label:
        request.session.pop('deliver_code', None)
        messages.error(request, _('الكود غير صحيح.'))
        return redirect('shipping:scan_deliver')

    shipment = label.shipment
    if not shipment:
        try:
            shipment = label.order.shipment
        except Exception:
            shipment = None
    if not shipment or shipment.courier_id != request.user.id:
        request.session.pop('deliver_code', None)
        messages.error(request, _('هذه الشحنة غير مسندة لك.'))
        return redirect('shipping:scan')

    if not _shipment_ready_for_courier_deliver(shipment):
        request.session.pop('deliver_code', None)
        if shipment.status == Shipment.STATUS_CREATED:
            messages.error(
                request,
                _(
                    'لم يُسجَّل استلام الشحنة من المتجر بعد. '
                    'استخدم صفحة «استلام من المتجر» وامسح البوليصة أولاً، ثم «تسليم للعميل».'
                ),
            )
        else:
            messages.error(request, _used_waybill_message_for_courier(shipment, 'deliver'))
        return redirect('shipping:scan_deliver')

    order = shipment.order

    from .security_services import (
        otp_can_send_in_challenge,
        otp_record_successful_send,
        otp_send_session_key_deliver,
        otp_sends_remaining,
    )

    deliver_send_key = otp_send_session_key_deliver(code)

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        post_action = (request.POST.get('action') or '').strip()
        if post_action == 'send':
            if not otp_can_send_in_challenge(request, deliver_send_key):
                msg = _(
                    'تم تجاوز حد إرسال الرمز لهذه الجلسة (إرسال أول + 3 إعادات كحد أقصى).'
                )
                if is_ajax:
                    return JsonResponse(
                        {
                            'success': False,
                            'error': str(msg),
                            'otp_sends_remaining': otp_sends_remaining(request, deliver_send_key),
                        },
                        status=429,
                    )
                messages.error(request, msg)
                return redirect('shipping:deliver_otp')

            otp = f"{__import__('random').randint(0, 999999):06d}"
            expires_at = timezone.now() + timezone.timedelta(minutes=10)
            DeliveryOTP.objects.create(shipment=shipment, code=otp, expires_at=expires_at)
            otp_record_successful_send(request, deliver_send_key)

            # send via console email backend + print to terminal
            subject = 'رمز تأكيد تسليم الطلب'
            body = f"رمز التأكيد لطلبك رقم #{order.id}: {otp}\nينتهي خلال 10 دقائق."
            to_email = (order.customer_email or '').strip()
            if to_email:
                send_mail(subject, body, None, [to_email], fail_silently=True)
            print(f"[DELIVERY_OTP] order={order.id} phone={order.customer_phone} email={to_email or '-'} otp={otp}")

            rem = otp_sends_remaining(request, deliver_send_key)
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'action': 'send',
                    'message': str(_('تم إرسال رمز التحقق (اختبار: يظهر في التيرمنال).')),
                    'otp_sends_remaining': rem,
                })
            messages.success(request, _('تم إرسال رمز التحقق (اختبار: يظهر في التيرمنال).'))
            return redirect('shipping:deliver_otp')

        if post_action == 'confirm':
            entered = (request.POST.get('otp') or '').strip()
            if not entered or len(entered) != 6:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(_('أدخل رمز مكون من 6 أرقام.'))}, status=400)
                messages.error(request, _('أدخل رمز مكون من 6 أرقام.'))
                return redirect('shipping:deliver_otp')

            latest = DeliveryOTP.objects.filter(shipment=shipment, is_used=False).order_by('-created_at').first()
            if not latest or latest.is_expired():
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(_('الرمز غير صالح أو منتهي. أعد إرسال رمز جديد.'))}, status=400)
                messages.error(request, _('الرمز غير صالح أو منتهي. أعد إرسال رمز جديد.'))
                return redirect('shipping:deliver_otp')
            if latest.code != entered:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(_('الرمز غير صحيح.'))}, status=400)
                messages.error(request, _('الرمز غير صحيح.'))
                return redirect('shipping:deliver_otp')

            latest.is_used = True
            latest.save(update_fields=['is_used'])

            try:
                apply_shipping_update(
                    shipment=shipment,
                    new_status=Shipment.STATUS_DELIVERED,
                    message='Courier OTP confirmed: delivered',
                    payload={'via': 'otp', 'courier': request.user.username},
                    actor=request.user
                )
                label.last_used_at = timezone.now()
                label.save(update_fields=['last_used_at'])
                request.session.pop('deliver_code', None)
                request.session['shipping_scan_show_delivered_ok'] = True
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'action': 'confirm',
                        'message': str(_('تم تأكيد التسليم بنجاح.')),
                        'redirect_url': reverse('shipping:scan'),
                    })
                messages.success(request, _('تم تأكيد التسليم بنجاح.'))
                return redirect('shipping:scan')
            except Exception as e:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(e), 'redirect_url': reverse('shipping:shipment_detail', args=[shipment.id])}, status=400)
                messages.error(request, str(e))
                return redirect('shipping:shipment_detail', pk=shipment.id)

    return render(
        request,
        'shipping/deliver_otp.html',
        {
            'shipment': shipment,
            'order': order,
            'label': label,
            'otp_sends_remaining': otp_sends_remaining(request, deliver_send_key),
        },
    )


# ═══════════════════════════════════════════════════════════════
#  لوحة مسؤول الشحن (shipping_manager)
# ═══════════════════════════════════════════════════════════════

@_shipping_manager_required
def shipping_manager_dashboard(request):
    """لوحة تحكم مسؤول الشحن — إحصائيات + آخر الشحنات."""
    stats = {
        'unassigned': Shipment.objects.filter(courier__isnull=True, status=Shipment.STATUS_CREATED).count(),
        'in_progress': Shipment.objects.filter(status__in=[
            Shipment.STATUS_PICKED, Shipment.STATUS_IN_TRANSIT, Shipment.STATUS_OUT_FOR_DELIVERY
        ]).count(),
        'delivered_today': Shipment.objects.filter(
            status=Shipment.STATUS_DELIVERED,
            updated_at__date=timezone.now().date()
        ).count(),
        'failed': Shipment.objects.filter(status=Shipment.STATUS_FAILED).count(),
    }
    recent_shipments = (
        Shipment.objects.select_related('order', 'courier')
        .exclude(status=Shipment.STATUS_DELIVERED)
        .order_by('-updated_at')[:15]
    )
    couriers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_COURIER,
        profile__is_available=True,
        is_active=True,
    ).select_related('profile').order_by('username')
    return render(request, 'shipping/manager_dashboard.html', {
        'stats': stats,
        'recent_shipments': recent_shipments,
        'couriers': couriers,
    })


@_shipping_manager_required
def shipping_manager_couriers(request):
    """قائمة المندوبين مع إحصائيات كل منهم."""
    couriers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_COURIER,
        is_active=True,
    ).select_related('profile').order_by('username')

    couriers_data = []
    for courier in couriers:
        couriers_data.append({
            'user': courier,
            'profile': courier.profile,
            'active': Shipment.objects.filter(
                courier=courier,
                status__in=[Shipment.STATUS_PICKED, Shipment.STATUS_IN_TRANSIT, Shipment.STATUS_OUT_FOR_DELIVERY]
            ).count(),
            'delivered_today': Shipment.objects.filter(
                courier=courier,
                status=Shipment.STATUS_DELIVERED,
                updated_at__date=timezone.now().date()
            ).count(),
        })

    return render(request, 'shipping/manager_couriers.html', {'couriers_data': couriers_data})


@_shipping_manager_required
def shipping_manager_shipments(request):
    """قائمة الشحنات مع فلتر الحالة وإمكانية الإسناد."""
    from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

    status_filter = request.GET.get('status', '').strip()
    courier_filter = request.GET.get('courier', '').strip()

    qs = Shipment.objects.select_related('order', 'courier')
    if status_filter:
        qs = qs.filter(status=status_filter)
    else:
        qs = qs.exclude(status__in=[Shipment.STATUS_DELIVERED])
    if courier_filter == 'unassigned':
        qs = qs.filter(courier__isnull=True)
    elif courier_filter:
        qs = qs.filter(courier_id=courier_filter)
    qs = qs.order_by('-updated_at')

    paginator = Paginator(qs, 25)
    page = request.GET.get('page', 1)
    try:
        shipments = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        shipments = paginator.page(1)

    couriers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_COURIER,
        is_active=True,
    ).order_by('username')

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'shipping/manager_shipments.html', {
        'shipments': shipments,
        'couriers': couriers,
        'status_filter': status_filter,
        'courier_filter': courier_filter,
        'status_choices': Shipment.STATUS_CHOICES,
        'query_string': q.urlencode(),
    })


@_shipping_manager_required
def shipping_assign_shipment(request, pk):
    """POST — إسناد شحنة لمندوب محدد."""
    if request.method != 'POST':
        return redirect('shipping:manager_shipments')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    shipment = get_object_or_404(Shipment, pk=pk)
    courier_id = (request.POST.get('courier_id') or '').strip()

    if courier_id:
        courier = User.objects.filter(
            pk=courier_id,
            profile__account_type=UserProfile.ACCOUNT_COURIER,
            is_active=True,
        ).first()
        if not courier:
            msg = str(_('المندوب غير موجود.'))
            if is_ajax:
                return JsonResponse({'success': False, 'error': msg}, status=400)
            messages.error(request, msg)
            return redirect('shipping:manager_shipments')
        shipment.courier = courier
    else:
        shipment.courier = None

    shipment.save(update_fields=['courier', 'updated_at'])

    if is_ajax:
        return JsonResponse({
            'success': True,
            'shipment_id': shipment.id,
            'courier_username': shipment.courier.username if shipment.courier else '',
            'message': str(_('تم إسناد الشحنة بنجاح.')) if shipment.courier else str(_('تم إلغاء إسناد الشحنة.')),
        })
    messages.success(request, _('تم تحديث إسناد الشحنة.'))
    return redirect('shipping:manager_shipments')


@_shipping_portal_required
def internal_chat(request):
    """
    محادثات داخلية للشحن:
      - المندوب: يرسل مباشرة بدون اختيار مسؤول.
      - المسؤول: يرى كل محادثات الشحن ويرد عليها.
    """
    profile = getattr(request.user, 'profile', None)
    is_manager = bool(profile and profile.account_type == UserProfile.ACCOUNT_SHIPPING_MANAGER)

    staff_thread = None
    if not is_manager:
        staff_thread = (
            InternalSupportThread.objects
            .filter(
                department=InternalSupportThread.DEPT_SHIPPING,
                staff_user=request.user,
                status__in=[InternalSupportThread.STATUS_WAITING, InternalSupportThread.STATUS_ACTIVE],
            )
            .order_by('-updated_at')
            .first()
        )
        if not staff_thread:
            staff_thread = InternalSupportThread.objects.create(
                department=InternalSupportThread.DEPT_SHIPPING,
                staff_user=request.user,
                status=InternalSupportThread.STATUS_WAITING,
            )

    if request.method == 'POST':
        action = (request.POST.get('action') or 'send').strip()
        thread = None
        if is_manager:
            tid = (request.POST.get('thread_id') or '').strip()
            if tid.isdigit():
                thread = InternalSupportThread.objects.filter(
                    pk=int(tid), department=InternalSupportThread.DEPT_SHIPPING
                ).first()
        else:
            thread = staff_thread

        if not thread:
            messages.error(request, _('المحادثة غير موجودة.'))
            return redirect('shipping:internal_chat')

        if action == 'close' and is_manager:
            thread.status = InternalSupportThread.STATUS_CLOSED
            thread.closed_at = timezone.now()
            thread.save(update_fields=['status', 'closed_at', 'updated_at'])
            messages.success(request, _('تم إغلاق المحادثة.'))
            return redirect('shipping:internal_chat')

        text = (request.POST.get('message') or '').strip()
        images = request.FILES.getlist('image')
        ok_imgs, img_err = validate_chat_image_files(images)
        if img_err:
            messages.error(request, chat_image_error_message(img_err['error']))
            return redirect('shipping:internal_chat')
        images = ok_imgs
        if not text and not images:
            messages.error(request, _('أدخل رسالة أو أرفق صورة.'))
            return redirect('shipping:internal_chat')

        sender_type = apply_internal_chat_routing(
            thread,
            user=request.user,
            is_manager=is_manager,
            manager_account_type=UserProfile.ACCOUNT_SHIPPING_MANAGER,
        )
        create_internal_chat_messages(thread, sender_type, request.user, text, images)

        # polite waiting auto-reply when no available manager picked yet
        if (not is_manager) and thread.manager_user_id is None and thread.waiting_notice_sent_at is None:
            InternalSupportMessage.objects.create(
                thread=thread,
                sender_type=InternalSupportMessage.SENDER_SYSTEM,
                text=_SHIPPING_WAITING_TEXT,
            )
            thread.waiting_notice_sent_at = timezone.now()

        thread.save(update_fields=[
            'manager_user', 'status', 'last_manager_message_at', 'last_staff_message_at',
            'waiting_notice_sent_at', 'updated_at',
        ])
        return redirect('shipping:internal_chat')

    if is_manager:
        threads = list(
            InternalSupportThread.objects.select_related('staff_user', 'manager_user')
            .filter(department=InternalSupportThread.DEPT_SHIPPING)
            .exclude(status=InternalSupportThread.STATUS_CLOSED)
            .order_by('-updated_at')[:200]
        )
        selected_id = request.GET.get('thread_id')
        selected = None
        if selected_id and selected_id.isdigit():
            selected = next((t for t in threads if t.id == int(selected_id)), None)
        if selected is None and threads:
            selected = threads[0]
        messages_qs = selected.messages.select_related('sender_user').order_by('created_at')[:250] if selected else []
        return render(request, 'shipping/internal_chat.html', {
            'portal_slug': 'shipping',
            'is_manager': True,
            'threads': threads,
            'selected_thread': selected,
            'chat_messages': list(messages_qs),
        })

    messages_qs = staff_thread.messages.select_related('sender_user').order_by('created_at')[:250]
    return render(request, 'shipping/internal_chat.html', {
        'portal_slug': 'shipping',
        'is_manager': False,
        'thread': staff_thread,
        'chat_messages': list(messages_qs),
    })

