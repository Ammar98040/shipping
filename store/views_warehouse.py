"""
بوابة المستودع (تجهيز الطلبات) — رابط مستقل /warehouse/
المجهّز يرى الطلبات في حالة processing، ويحوّلها إلى ready_to_ship بعد التجهيز.
"""
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from .forms_profile import UserProfileForm
from .internal_chat_service import apply_internal_chat_routing, create_internal_chat_messages
from .models import (
    InternalSupportMessage,
    InternalSupportThread,
    LabelCode,
    Order,
    ShippingWaybill,
    UserProfile,
)
from .order_engine import OrderTransitionError, advance_order
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
from .shipping_waybill_service import ensure_shipping_waybill_for_order, get_or_create_label_for_order
from .upload_validation import chat_image_error_message, validate_chat_image_files


def _get_shipping_waybill(order):
    try:
        return order.shipping_waybill
    except ShippingWaybill.DoesNotExist:
        return None


_WAREHOUSE_PORTAL_ROLES = (
    UserProfile.ACCOUNT_PACKER,
    UserProfile.ACCOUNT_WAREHOUSE_MANAGER,
)

_WAREHOUSE_ROLE_MAP = {
    UserProfile.ACCOUNT_PACKER:            'warehouse:dashboard',
    UserProfile.ACCOUNT_WAREHOUSE_MANAGER: 'warehouse:manager_dashboard',
}

_WAREHOUSE_WAITING_TEXT = 'تم استلام رسالتك. سيتم الرد عليك من مسؤول المستودع حالما يصبح متاحاً.'


def _packer_required(view_func):
    """متوافق للخلف — يحمي views المندوبين (packer فقط)."""
    return _warehouse_portal_required(view_func, roles=(UserProfile.ACCOUNT_PACKER,))


def _warehouse_portal_required(view_func, roles=None):
    """يقبل packer و warehouse_manager معاً."""
    allowed = roles or _WAREHOUSE_PORTAL_ROLES

    def wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('warehouse:login')
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.account_type not in allowed:
            messages.error(request, _('غير مصرح لك بالدخول إلى بوابة المستودع.'))
            return redirect('warehouse:login')
        return view_func(request, *args, **kwargs)
    wrap.__name__ = getattr(view_func, '__name__', 'view')
    return wrap


def _warehouse_manager_required(view_func):
    """يقبل warehouse_manager فقط."""
    def wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('warehouse:login')
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.account_type != UserProfile.ACCOUNT_WAREHOUSE_MANAGER:
            messages.error(request, _('هذه الصفحة مخصصة لمسؤول المستودع فقط.'))
            return redirect('warehouse:login')
        return view_func(request, *args, **kwargs)
    wrap.__name__ = getattr(view_func, '__name__', 'view')
    return wrap


def warehouse_login(request):
    from .security_services import (
        clear_login_failure,
        is_login_locked,
        locked_message,
        login_needs_turnstile,
        record_login_failure,
        verify_turnstile,
    )

    request._security_portal = 'warehouse'

    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.account_type in _WAREHOUSE_PORTAL_ROLES:
            return redirect(_WAREHOUSE_ROLE_MAP.get(profile.account_type, 'warehouse:dashboard'))

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if username and is_login_locked('warehouse', request, username):
            messages.error(request, locked_message())
            return render(request, 'warehouse/login.html')
        if login_needs_turnstile('warehouse', request):
            ok, err = verify_turnstile(request)
            if not ok:
                messages.error(request, err)
                return render(request, 'warehouse/login.html')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            profile = getattr(user, 'profile', None)
            if profile and profile.account_type in _WAREHOUSE_PORTAL_ROLES:
                clear_login_failure('warehouse', request, username)
                login(request, user)
                raw_next = (request.GET.get('next') or request.POST.get('next') or '').strip()
                from django.utils.http import url_has_allowed_host_and_scheme
                if raw_next and raw_next.startswith('/') and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}):
                    return redirect(raw_next)
                return redirect(_WAREHOUSE_ROLE_MAP.get(profile.account_type, 'warehouse:dashboard'))
        if username:
            record_login_failure('warehouse', request, username)
        messages.error(request, _('اسم مستخدم أو كلمة مرور غير صحيحة.'))
    return render(request, 'warehouse/login.html')


def warehouse_logout(request):
    logout(request)
    return redirect('warehouse:login')


def forgot_password(request):
    """نسيت كلمة المرور لبوابة المستودع (OTP للبريد)."""
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.account_type in _WAREHOUSE_PORTAL_ROLES:
            return redirect(_WAREHOUSE_ROLE_MAP.get(profile.account_type, 'warehouse:dashboard'))

    if request.method == 'POST':
        from .security_services import turnstile_configured, verify_turnstile
        if turnstile_configured():
            ok, err = verify_turnstile(request)
            if not ok:
                messages.error(request, err)
                return redirect('warehouse:forgot_password')

        outcome, _ = process_forgot_password_step1(
            request,
            email_raw=request.POST.get('email') or '',
            session_otp_key='warehouse_pw_reset_otp_id',
            session_verified_key='warehouse_pw_reset_otp_verified',
            resolve_user=lambda e: User.objects.filter(
                email__iexact=e, profile__account_type=UserProfile.ACCOUNT_PACKER
            ).first(),
            mail_context='بوابة المستودع — إعادة تعيين كلمة المرور',
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

            k_pw = otp_send_session_key_pw_portal('warehouse')
            otp_reset_send_count(request, k_pw)
            otp_record_successful_send(request, k_pw)
            messages.success(request, MSG_OTP_SENT)
            return redirect('warehouse:forgot_password_otp')
        elif outcome == 'no_user':
            messages.error(request, MSG_NO_ACCOUNT)
        return redirect('warehouse:forgot_password')

    return render(request, 'warehouse/forgot_password.html')


def forgot_password_otp(request):
    from .security_services import otp_send_session_key_pw_portal, otp_sends_remaining

    otp_obj = get_active_password_reset_otp(request, 'warehouse_pw_reset_otp_id')
    if not otp_obj:
        messages.error(request, MSG_OTP_RESTART)
        return redirect('warehouse:forgot_password')

    if request.session.get('warehouse_pw_reset_otp_verified'):
        return redirect('warehouse:forgot_password_new_password')

    if request.method == 'POST' and (request.POST.get('otp_action') or '').strip() == 'resend':
        return password_reset_otp_resend_response(
            request,
            otp_obj,
            portal='warehouse',
            mail_context='بوابة المستودع — إعادة تعيين كلمة المرور',
            url_otp='warehouse:forgot_password_otp',
        )

    resp = try_verify_password_reset_otp_step(
        request,
        otp_obj,
        session_otp_key='warehouse_pw_reset_otp_id',
        session_verified_key='warehouse_pw_reset_otp_verified',
        url_forgot='warehouse:forgot_password',
        url_otp='warehouse:forgot_password_otp',
        url_new_password='warehouse:forgot_password_new_password',
    )
    if resp:
        return resp

    return render(
        request,
        'warehouse/forgot_password_otp.html',
        {
            'email': otp_obj.email,
            'otp_sends_remaining': otp_sends_remaining(request, otp_send_session_key_pw_portal('warehouse')),
        },
    )


def forgot_password_new_password(request):
    redir, otp_obj = get_context_for_new_password_page(
        request,
        session_otp_key='warehouse_pw_reset_otp_id',
        session_verified_key='warehouse_pw_reset_otp_verified',
        url_forgot='warehouse:forgot_password',
        url_otp='warehouse:forgot_password_otp',
    )
    if redir:
        return redir

    resp = try_set_new_password_after_verified_otp(
        request,
        otp_obj,
        session_otp_key='warehouse_pw_reset_otp_id',
        session_verified_key='warehouse_pw_reset_otp_verified',
        url_forgot='warehouse:forgot_password',
        url_otp='warehouse:forgot_password_otp',
        url_new_password='warehouse:forgot_password_new_password',
        url_login='warehouse:login',
        success_message=_('تم تغيير كلمة المرور. سجّل دخولك الآن.'),
    )
    if resp:
        return resp

    return render(request, 'warehouse/forgot_password_new.html', {'email': otp_obj.email})


@_packer_required
def profile(request):
    """ملف المجهّز الشخصي داخل بوابة المستودع."""
    user = request.user
    profile_obj = getattr(user, 'profile', None)
    if profile_obj is None:
        profile_obj = UserProfile.objects.create(user=user, account_type=UserProfile.ACCOUNT_PACKER)

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
                return redirect('warehouse:profile')
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
                return redirect('warehouse:profile')
            if is_ajax:
                return JsonResponse({'success': False, 'action': 'password', 'error': str(_('تعذر تغيير كلمة المرور. تحقق من البيانات.'))}, status=400)
            messages.error(request, _('تعذر تغيير كلمة المرور. تحقق من البيانات.'))

    return render(request, 'warehouse/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
        'profile_obj': profile_obj,
    })


@_packer_required
def dashboard(request):
    profile_obj, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_PACKER}
    )
    my_qs = Order.objects.prefetch_related('items__product').filter(packer=request.user).order_by('-updated_at')
    available_count = Order.objects.filter(status=Order.STATUS_PROCESSING, packer__isnull=True).count()
    stats = {
        'my_all': my_qs.count(),
        'my_processing': my_qs.filter(status=Order.STATUS_PROCESSING).count(),
        'my_ready': my_qs.filter(status=Order.STATUS_READY).count(),
    }
    recent = my_qs[:10]
    return render(request, 'warehouse/dashboard.html', {
        'stats': stats,
        'recent': recent,
        'available_count': available_count,
        'profile_obj': profile_obj,
    })


@_packer_required
def set_availability(request):
    if request.method != 'POST':
        return redirect('warehouse:dashboard')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_PACKER}
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
    return redirect(request.POST.get('next') or 'warehouse:dashboard')


@_packer_required
@require_GET
def my_availability_live(request):
    """مزامنة حالة التوفر (مثلاً بعد تغييرها من لوحة الإدارة) بدون ريفرش."""
    profile_obj, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_PACKER},
    )
    return JsonResponse({
        'success': True,
        'is_available': bool(profile_obj.is_available),
        'badge_text': '🟢 متوفر' if profile_obj.is_available else '⚪ غير متوفر',
        'button_text': 'إيقاف التوفر مؤقتاً' if profile_obj.is_available else 'أنا متوفر الآن',
        'button_class': 'btn-secondary' if profile_obj.is_available else 'btn-primary',
        'updated_at': profile_obj.availability_updated_at.isoformat() if profile_obj.availability_updated_at else '',
    })


@_packer_required
def available_orders(request):
    """طلبات تجهيز جديدة (processing وغير مسندة لمجهز)"""
    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_PACKER}
    )
    if not profile_obj.is_available:
        messages.info(request, _('أنت غير متوفر حالياً، لذلك لن تصلك مهام تجهيز جديدة حتى تعيد الحالة إلى متوفر.'))
        return render(request, 'warehouse/available_orders.html', {'items': Order.objects.none()})

    items = Order.objects.prefetch_related('items__product').filter(
        status=Order.STATUS_PROCESSING,
        packer__isnull=True
    ).order_by('created_at')

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    return render(request, 'warehouse/available_orders.html', {'items': items})


@_packer_required
def available_orders_live(request):
    """تغذية حيّة خفيفة لطلبات التجهيز غير المسندة."""
    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_PACKER}
    )
    base_qs = Order.objects.filter(
        status=Order.STATUS_PROCESSING,
        packer__isnull=True,
    )
    total_count = base_qs.count()
    if not profile_obj.is_available:
        return JsonResponse({'success': True, 'items': [], 'count': total_count})

    items = (
        base_qs
        .prefetch_related('items')
        .order_by('created_at')[:50]
    )
    payload = []
    for o in items:
        payload.append({
            'id': o.id,
            'customer_name': o.customer_name or '',
            'customer_phone': o.customer_phone or '',
            'items_count': o.items.count(),
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else '',
            'accept_url': reverse('warehouse:accept_order', args=[o.id]),
        })
    return JsonResponse({'success': True, 'items': payload, 'count': total_count})


@_packer_required
def accept_order(request, pk):
    """استلام طلب تجهيز (إسناده للمجهز)"""
    if request.method != 'POST':
        return redirect('warehouse:available_orders')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    profile_obj, _created_profile = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'account_type': UserProfile.ACCOUNT_PACKER}
    )
    if not profile_obj.is_available:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('لا يمكنك استلام طلبات جديدة لأن حالتك غير متوفر.'))}, status=400)
        messages.error(request, _('لا يمكنك استلام طلبات جديدة لأن حالتك غير متوفر.'))
        return redirect('warehouse:available_orders')

    order = get_object_or_404(Order, pk=pk)
    if order.status != Order.STATUS_PROCESSING:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('هذا الطلب ليس في حالة قيد التجهيز.'))}, status=400)
        messages.error(request, _('هذا الطلب ليس في حالة قيد التجهيز.'))
        return redirect('warehouse:available_orders')
    if order.packer_id is not None:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('هذا الطلب تم إسناده مسبقاً.'))}, status=400)
        messages.error(request, _('هذا الطلب تم إسناده مسبقاً.'))
        return redirect('warehouse:available_orders')

    order.packer = request.user
    order.save(update_fields=['packer', 'updated_at'])
    if is_ajax:
        return JsonResponse({
            'success': True,
            'order_id': order.id,
            'detail_url': reverse('warehouse:order_detail', args=[pk]),
            'message': str(_('تم استلام الطلب بنجاح.')),
        })
    messages.success(request, _('تم استلام الطلب بنجاح.'))
    return redirect('warehouse:order_detail', pk=pk)


@_packer_required
def order_detail(request, pk):
    """تفاصيل طلب للمجهز. تُنشأ بوليصة الشحن من الصفحة (زر) أو من صفحة الطباعة."""
    order = get_object_or_404(
        Order.objects.prefetch_related(
            'items__product', 'items__product__gallery_images', 'items__variant__images', 'items__selected_gallery_image',
        ).select_related('shipping_waybill', 'shipment'),
        pk=pk,
        packer=request.user,
    )

    shipping_waybill = _get_shipping_waybill(order)
    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None

    label = None
    if shipping_waybill:
        label, _ = get_or_create_label_for_order(order)

    return render(request, 'warehouse/order_detail.html', {
        'order': order,
        'shipping_waybill': shipping_waybill,
        'shipment': shipment,
        'label': label,
    })


@_packer_required
def order_detail_poll(request, pk):
    """GET — polling خفيف لحالة الطلب في بوابة المستودع بدون reload."""
    order = get_object_or_404(
        Order.objects.select_related('shipment'),
        pk=pk,
        packer=request.user,
    )
    signature = '|'.join([
        str(order.status or ''),
        order.updated_at.isoformat() if order.updated_at else '',
    ])
    return JsonResponse({
        'success': True,
        'signature': signature,
        'status': order.status or '',
        'status_display': order.get_status_display(),
    })


@_packer_required
@require_POST
def create_shipping_waybill(request, pk):
    """إنشاء/مزامنة سجل البوليصة من واجهة المستودع (JSON + HTML للقسم)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    order = get_object_or_404(
        Order.objects.prefetch_related(
            'items__product', 'items__product__gallery_images', 'items__variant__images', 'items__selected_gallery_image',
        ).select_related('shipment'),
        pk=pk,
        packer=request.user,
    )
    if order.status == Order.STATUS_CANCELLED:
        msg = str(_('لا يمكن إنشاء بوليصة لطلب ملغى.'))
        if is_ajax:
            return JsonResponse({'success': False, 'error': msg}, status=400)
        messages.error(request, msg)
        return redirect('warehouse:order_detail', pk=pk)

    wb, created, label = ensure_shipping_waybill_for_order(
        order,
        actor=request.user,
        source_line=str(_('إنشاء البوليصة من صفحة تفاصيل الطلب في المستودع.')),
    )
    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None

    if not is_ajax:
        messages.success(
            request,
            str(_('تم إنشاء بوليصة الشحن.')) if created else str(_('تم تحديث بيانات البوليصة.')),
        )
        return redirect('warehouse:order_detail', pk=pk)

    html = render_to_string(
        'warehouse/partials/order_waybill_panel.html',
        {
            'order': order,
            'shipping_waybill': wb,
            'shipment': shipment,
            'label': label,
        },
        request=request,
    )
    return JsonResponse({
        'success': True,
        'created': created,
        'html': html,
        'message': str(_('تم إنشاء بوليصة الشحن.')) if created else str(_('تم تحديث بيانات البوليصة.')),
    })


@_packer_required
def shipping_label(request, pk):
    """
    بوليصة شحن قابلة للطباعة.
    عند فتح الصفحة تُسجَّل بوليصة الشحن تلقائياً في النظام (للمسؤول) بقيم موحّدة من كود الملصق.
    """
    order = get_object_or_404(Order.objects.prefetch_related('items__product', 'items__product__gallery_images', 'items__variant__images', 'items__selected_gallery_image'), pk=pk, packer=request.user)

    if order.status == Order.STATUS_CANCELLED:
        messages.error(request, _('لا يمكن طباعة بوليصة لطلب ملغى.'))
        return redirect('warehouse:order_detail', pk=pk)

    _wb, _created_wb, label = ensure_shipping_waybill_for_order(
        order,
        actor=request.user,
        source_line=str(_('فتح صفحة طباعة البوليصة من المستودع.')),
    )
    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None

    return render(request, 'warehouse/shipping_label.html', {'order': order, 'shipment': shipment, 'label': label})


@_packer_required
def order_label_qr(request, pk):
    """صورة QR لبوليصة الشحن (للطباعة). يُسجّل سجل البوليصة كما في صفحة الطباعة."""
    import io

    import qrcode

    order = get_object_or_404(Order, pk=pk, packer=request.user)
    if order.status != Order.STATUS_CANCELLED:
        _wb, _created_wb, label = ensure_shipping_waybill_for_order(
            order,
            actor=request.user,
            source_line=str(_('طلب صورة QR للبوليصة من المستودع.')),
        )
    else:
        try:
            label = order.label_code
        except LabelCode.DoesNotExist:
            messages.error(request, _('لا يمكن عرض QR لطلب ملغى بدون كود ملصق.'))
            return redirect('warehouse:order_detail', pk=pk)

    payload = f"DLBK:{label.code}"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@_packer_required
def scan(request):
    """صفحة مسح باركود المستودع."""
    return render(request, 'warehouse/scan.html')


@_packer_required
def scan_consume(request):
    """استهلاك كود البوليصة: processing -> ready_to_ship"""
    if request.method != 'POST':
        return redirect('warehouse:scan')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    raw = (request.POST.get('code') or '').strip()
    code = raw.replace('DLBK:', '').strip().upper()
    if not code:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('أدخل الكود.'))}, status=400)
        messages.error(request, _('أدخل الكود.'))
        return redirect('warehouse:scan')

    label = LabelCode.objects.select_related('order').filter(code=code).first()
    if not label:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('الكود غير صحيح.'))}, status=404)
        messages.error(request, _('الكود غير صحيح.'))
        return redirect('warehouse:scan')

    order = label.order
    if order.packer_id != request.user.id:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(_('هذا الطلب غير مسند لك.'))}, status=403)
        messages.error(request, _('هذا الطلب غير مسند لك.'))
        return redirect('warehouse:scan')
    if order.status != Order.STATUS_PROCESSING:
        if order.status == Order.STATUS_READY:
            used_msg = str(_('هذا الكود مستخدم بالفعل — تم تجهيز الطلب مسبقاً.'))
        elif order.status == Order.STATUS_READY_TO_SHIP:
            used_msg = str(_('هذا الكود مستخدم بالفعل — تم تحويل الطلب إلى جاهز للشحن مسبقاً.'))
        elif order.status == Order.STATUS_SHIPPED:
            used_msg = str(_('هذا الكود مستخدم بالفعل — الطلب خرج للشحن مسبقاً.'))
        elif order.status == Order.STATUS_DELIVERED:
            used_msg = str(_('هذا الكود مستخدم بالفعل — الطلب تم تسليمه مسبقاً.'))
        elif order.status == Order.STATUS_CANCELLED:
            used_msg = str(_('لا يمكن استخدام هذا الكود: الطلب ملغى.'))
        else:
            used_msg = str(_('هذا الطلب ليس في حالة قيد التجهيز.'))
        if is_ajax:
            return JsonResponse({
                'success': False,
                'error': used_msg,
                'redirect_url': reverse('warehouse:order_detail', args=[order.id]),
            }, status=400)
        messages.error(request, used_msg)
        return redirect('warehouse:order_detail', pk=order.id)

    try:
        advance_order(order, Order.STATUS_READY, actor=request.user, note='Warehouse scan: prepared', is_auto=True)
        label.last_used_at = timezone.now()
        label.save(update_fields=['last_used_at'])
        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': str(_('تم قراءة الباركود: تم تحويل الطلب إلى جاهز للشحن.')),
                'redirect_url': reverse('warehouse:order_detail', args=[order.id]),
            })
        messages.success(request, _('تم قراءة الباركود: تم تحويل الطلب إلى جاهز للشحن.'))
        return redirect('warehouse:order_detail', pk=order.id)
    except OrderTransitionError as e:
        if is_ajax:
            return JsonResponse({'success': False, 'error': str(e), 'redirect_url': reverse('warehouse:order_detail', args=[order.id])}, status=400)
        messages.error(request, str(e))
        return redirect('warehouse:order_detail', pk=order.id)


# ═══════════════════════════════════════════════════════════════
#  لوحة مسؤول المستودع (warehouse_manager)
# ═══════════════════════════════════════════════════════════════

@_warehouse_manager_required
def warehouse_manager_dashboard(request):
    """لوحة تحكم مسؤول المستودع — إحصائيات + آخر الطلبات."""
    from .models import Order
    stats = {
        'processing': Order.objects.filter(status=Order.STATUS_PROCESSING).count(),
        'ready': Order.objects.filter(status=Order.STATUS_READY).count(),
        'unassigned': Order.objects.filter(status=Order.STATUS_PROCESSING, packer__isnull=True).count(),
        'total_today': Order.objects.filter(
            created_at__date=timezone.now().date()
        ).count(),
    }
    recent_orders = (
        Order.objects.filter(status__in=[Order.STATUS_PROCESSING, Order.STATUS_READY])
        .select_related('packer')
        .order_by('-updated_at')[:15]
    )
    packers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_PACKER,
        is_active=True,
    ).select_related('profile').order_by('username')
    return render(request, 'warehouse/manager_dashboard.html', {
        'stats': stats,
        'recent_orders': recent_orders,
        'packers': packers,
    })


@_warehouse_manager_required
def warehouse_manager_team(request):
    """قائمة فريق التجهيز مع إحصائيات كل مندوب."""
    from .models import Order
    packers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_PACKER,
        is_active=True,
    ).select_related('profile').order_by('username')

    team_data = []
    for packer in packers:
        team_data.append({
            'user': packer,
            'profile': packer.profile,
            'active_orders': Order.objects.filter(packer=packer, status=Order.STATUS_PROCESSING).count(),
            'ready_orders': Order.objects.filter(packer=packer, status=Order.STATUS_READY).count(),
        })

    return render(request, 'warehouse/manager_team.html', {'team_data': team_data})


@_warehouse_manager_required
def warehouse_manager_orders(request):
    """قائمة الطلبات مع فلتر الحالة وإمكانية الإسناد."""
    from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

    from .models import Order

    status_filter = request.GET.get('status', '').strip()
    packer_filter = request.GET.get('packer', '').strip()

    qs = Order.objects.select_related('packer').prefetch_related('items__product')
    if status_filter:
        qs = qs.filter(status=status_filter)
    else:
        qs = qs.filter(status__in=[Order.STATUS_PROCESSING, Order.STATUS_READY])
    if packer_filter == 'unassigned':
        qs = qs.filter(packer__isnull=True)
    elif packer_filter:
        qs = qs.filter(packer_id=packer_filter)
    qs = qs.order_by('-updated_at')

    paginator = Paginator(qs, 25)
    page = request.GET.get('page', 1)
    try:
        orders = paginator.page(page)
    except (EmptyPage, PageNotAnInteger):
        orders = paginator.page(1)

    packers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_PACKER, is_active=True
    ).order_by('username')
    status_choices = [
        (Order.STATUS_PROCESSING, 'قيد التجهيز'),
        (Order.STATUS_READY, 'جاهز للشحن'),
        (Order.STATUS_SHIPPED, 'تم الشحن'),
        (Order.STATUS_DELIVERED, 'تم التسليم'),
        (Order.STATUS_CANCELLED, 'ملغى'),
    ]

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'warehouse/manager_orders.html', {
        'orders': orders,
        'packers': packers,
        'status_filter': status_filter,
        'packer_filter': packer_filter,
        'status_choices': status_choices,
        'query_string': q.urlencode(),
    })


@_warehouse_manager_required
def warehouse_assign_order(request, pk):
    """POST — إسناد طلب لمجهّز محدد."""
    from .models import Order
    if request.method != 'POST':
        return redirect('warehouse:manager_orders')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    order = get_object_or_404(Order, pk=pk)
    packer_id = (request.POST.get('packer_id') or '').strip()

    if packer_id:
        packer = User.objects.filter(
            pk=packer_id,
            profile__account_type=UserProfile.ACCOUNT_PACKER,
            is_active=True,
        ).first()
        if not packer:
            msg = str(_('المجهّز غير موجود.'))
            if is_ajax:
                return JsonResponse({'success': False, 'error': msg}, status=400)
            messages.error(request, msg)
            return redirect('warehouse:manager_orders')
        order.packer = packer
    else:
        order.packer = None

    order.save(update_fields=['packer', 'updated_at'])

    if is_ajax:
        return JsonResponse({
            'success': True,
            'order_id': order.id,
            'packer_username': order.packer.username if order.packer else '',
            'message': str(_('تم الإسناد بنجاح.')) if order.packer else str(_('تم إلغاء الإسناد.')),
        })
    messages.success(request, _('تم تحديث إسناد الطلب.'))
    return redirect('warehouse:manager_orders')


@_warehouse_portal_required
def internal_chat(request):
    """محادثات داخلية للمستودع بين المجهزين ومسؤول المستودع."""
    profile = getattr(request.user, 'profile', None)
    is_manager = bool(profile and profile.account_type == UserProfile.ACCOUNT_WAREHOUSE_MANAGER)

    staff_thread = None
    if not is_manager:
        staff_thread = (
            InternalSupportThread.objects
            .filter(
                department=InternalSupportThread.DEPT_WAREHOUSE,
                staff_user=request.user,
                status__in=[InternalSupportThread.STATUS_WAITING, InternalSupportThread.STATUS_ACTIVE],
            )
            .order_by('-updated_at')
            .first()
        )
        if not staff_thread:
            staff_thread = InternalSupportThread.objects.create(
                department=InternalSupportThread.DEPT_WAREHOUSE,
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
                    pk=int(tid), department=InternalSupportThread.DEPT_WAREHOUSE
                ).first()
        else:
            thread = staff_thread

        if not thread:
            messages.error(request, _('المحادثة غير موجودة.'))
            return redirect('warehouse:internal_chat')

        if action == 'close' and is_manager:
            thread.status = InternalSupportThread.STATUS_CLOSED
            thread.closed_at = timezone.now()
            thread.save(update_fields=['status', 'closed_at', 'updated_at'])
            messages.success(request, _('تم إغلاق المحادثة.'))
            return redirect('warehouse:internal_chat')

        text = (request.POST.get('message') or '').strip()
        images = request.FILES.getlist('image')
        ok_imgs, img_err = validate_chat_image_files(images)
        if img_err:
            messages.error(request, chat_image_error_message(img_err['error']))
            return redirect('warehouse:internal_chat')
        images = ok_imgs
        if not text and not images:
            messages.error(request, _('أدخل رسالة أو أرفق صورة.'))
            return redirect('warehouse:internal_chat')

        sender_type = apply_internal_chat_routing(
            thread,
            user=request.user,
            is_manager=is_manager,
            manager_account_type=UserProfile.ACCOUNT_WAREHOUSE_MANAGER,
        )
        create_internal_chat_messages(thread, sender_type, request.user, text, images)

        if (not is_manager) and thread.manager_user_id is None and thread.waiting_notice_sent_at is None:
            InternalSupportMessage.objects.create(
                thread=thread,
                sender_type=InternalSupportMessage.SENDER_SYSTEM,
                text=_WAREHOUSE_WAITING_TEXT,
            )
            thread.waiting_notice_sent_at = timezone.now()

        thread.save(update_fields=[
            'manager_user', 'status', 'last_manager_message_at', 'last_staff_message_at',
            'waiting_notice_sent_at', 'updated_at',
        ])
        return redirect('warehouse:internal_chat')

    if is_manager:
        threads = list(
            InternalSupportThread.objects.select_related('staff_user', 'manager_user')
            .filter(department=InternalSupportThread.DEPT_WAREHOUSE)
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
        return render(request, 'warehouse/internal_chat.html', {
            'portal_slug': 'warehouse',
            'is_manager': True,
            'threads': threads,
            'selected_thread': selected,
            'chat_messages': list(messages_qs),
        })

    messages_qs = staff_thread.messages.select_related('sender_user').order_by('created_at')[:250]
    return render(request, 'warehouse/internal_chat.html', {
        'portal_slug': 'warehouse',
        'is_manager': False,
        'thread': staff_thread,
        'chat_messages': list(messages_qs),
    })
