"""بوابة خدمة العملاء ولوحة الدردشة في لوحة الإدارة."""

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from .manage_decorators import _staff_required
from .manage_staff_roles import _is_customer_service_manager, _is_support_admin
from .support_engagement import support_staff_visible_q, support_thread_customer_engaged
from .models import (
    SupportCustomerMessageRead,
    SupportMessage,
    SupportThread,
    SupportThreadAuditEvent,
    UserProfile,
)
from .support_bot import BOT_KIND, SUPPORT_AUTO_WAITING_REPLY
from .upload_validation import validate_chat_image_files


def _availability_payload(profile_obj: UserProfile):
    is_available = bool(profile_obj.is_available)
    return {
        'is_available': is_available,
        'badge_text': '🟢 متوفر' if is_available else '⚪ غير متوفر',
        'badge_class': 'badge-active' if is_available else 'badge-unavailable',
        'button_text': 'إيقاف التوفر' if is_available else 'تفعيل التوفر',
        'button_class': 'btn-secondary' if is_available else 'btn-primary',
        'availability_updated_at': profile_obj.availability_updated_at.strftime('%Y-%m-%d %H:%M') if profile_obj.availability_updated_at else '',
        'updated_at': profile_obj.availability_updated_at.isoformat() if profile_obj.availability_updated_at else '',
    }


@_staff_required
def support_team_accounts(request):
    """لوحة موظفي خدمة العملاء للمسؤول: بحث + فلترة التوفر + تبديل الحالة."""
    if not _is_support_admin(request.user):
        messages.error(request, 'هذه الصفحة متاحة لمسؤول خدمة العملاء أو المدير الرئيسي فقط.')
        return redirect('manage:support_portal')

    search_query = request.GET.get('search', '').strip()
    availability_filter = request.GET.get('availability', '').strip()
    staff_users = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_CUSTOMER_SERVICE
    ).select_related('profile').annotate(
        ended_sessions=Count(
            'assigned_support_threads',
            filter=Q(
                assigned_support_threads__status=SupportThread.STATUS_ENDED,
                assigned_support_threads__is_archived=False,
            ),
            distinct=True,
        ),
        responded_registered=Count(
            'assigned_support_threads__customer_user',
            filter=Q(
                assigned_support_threads__status=SupportThread.STATUS_ENDED,
                assigned_support_threads__is_archived=False,
                assigned_support_threads__customer_user__isnull=False,
            ),
            distinct=True,
        ),
        responded_guests=Count(
            'assigned_support_threads__guest_phone',
            filter=Q(
                assigned_support_threads__status=SupportThread.STATUS_ENDED,
                assigned_support_threads__is_archived=False,
                assigned_support_threads__customer_user__isnull=True,
            ) & ~Q(assigned_support_threads__guest_phone=''),
            distinct=True,
        ),
        unanswered_now=Count(
            'assigned_support_threads',
            filter=Q(
                assigned_support_threads__is_archived=False,
                assigned_support_threads__status=SupportThread.STATUS_ACTIVE,
                assigned_support_threads__last_customer_message_at__isnull=False,
            ) & (
                Q(assigned_support_threads__last_staff_message_at__isnull=True)
                | Q(assigned_support_threads__last_customer_message_at__gt=F('assigned_support_threads__last_staff_message_at'))
            ),
            distinct=True,
        ),
    )

    if search_query:
        staff_users = staff_users.filter(
            Q(username__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(profile__phone__icontains=search_query)
        )
    if availability_filter == 'available':
        staff_users = staff_users.filter(profile__is_available=True)
    elif availability_filter == 'unavailable':
        staff_users = staff_users.filter(profile__is_available=False)

    staff_users = staff_users.order_by('username')
    paginator = Paginator(staff_users, 25)
    page = request.GET.get('page', 1)
    try:
        staff_users = paginator.page(page)
    except PageNotAnInteger:
        staff_users = paginator.page(1)
    except EmptyPage:
        staff_users = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/support_team_accounts.html', {
        'staff_users': staff_users,
        'search_query': search_query,
        'availability_filter': availability_filter,
        'query_string': q.urlencode(),
    })


@_staff_required
def support_agent_detail(request, agent_id):
    """تفاصيل أداء ممثل خدمة العملاء: نشطة/منتهية/مؤرشفة + إحصائيات شاملة."""
    if not _is_support_admin(request.user):
        messages.error(request, 'هذه الصفحة متاحة لمسؤول خدمة العملاء أو المدير الرئيسي فقط.')
        return redirect('manage:support_portal')

    agent = get_object_or_404(
        User.objects.select_related('profile'),
        pk=agent_id,
        profile__account_type=UserProfile.ACCOUNT_CUSTOMER_SERVICE,
    )

    active_threads = list(
        SupportThread.objects.select_related('customer_user', 'assigned_staff')
        .filter(assigned_staff=agent, is_archived=False, status=SupportThread.STATUS_ACTIVE)
        .order_by('-updated_at')[:150]
    )
    ended_threads = list(
        SupportThread.objects.select_related('customer_user', 'assigned_staff')
        .filter(assigned_staff=agent, is_archived=False, status=SupportThread.STATUS_ENDED)
        .order_by('-updated_at')[:200]
    )
    archived_threads = list(
        SupportThread.objects.select_related('customer_user', 'assigned_staff')
        .filter(assigned_staff=agent, is_archived=True)
        .order_by('-updated_at')[:200]
    )

    now = timezone.now()
    _support_attach_thread_timing(active_threads, now=now)
    _support_attach_thread_timing(ended_threads, now=now)
    _support_attach_thread_timing(archived_threads, now=now)

    for thread in active_threads:
        pending_seconds = _support_pending_seconds(thread, now)
        mins = pending_seconds // 60
        secs = pending_seconds % 60
        thread.pending_seconds = pending_seconds
        thread.pending_label = f'{mins:02d}:{secs:02d}'
        thread.sla_state = _support_sla_state(pending_seconds)

    all_threads = active_threads + ended_threads + archived_threads
    responded_registered = len({t.customer_user_id for t in all_threads if t.customer_user_id})
    responded_guests = len({(t.guest_phone or '').strip() for t in all_threads if not t.customer_user_id and (t.guest_phone or '').strip()})
    total_responded_users = responded_registered + responded_guests

    ended_and_archived = ended_threads + archived_threads
    avg_waiting_first_reply_minutes = 0.0
    avg_conversation_minutes = 0.0
    if ended_and_archived:
        waiting_values = [t.waiting_response_seconds for t in ended_and_archived if getattr(t, 'waiting_response_seconds', 0) > 0]
        conversation_values = [t.conversation_seconds for t in ended_and_archived if getattr(t, 'conversation_seconds', 0) > 0]
        if waiting_values:
            avg_waiting_first_reply_minutes = round((sum(waiting_values) / len(waiting_values)) / 60.0, 1)
        if conversation_values:
            avg_conversation_minutes = round((sum(conversation_values) / len(conversation_values)) / 60.0, 1)

    context = {
        'agent': agent,
        'active_threads': active_threads,
        'ended_threads': ended_threads,
        'archived_threads': archived_threads,
        'agent_stats': {
            'active_count': len(active_threads),
            'ended_count': len(ended_threads),
            'archived_count': len(archived_threads),
            'responded_users': total_responded_users,
            'avg_waiting_first_reply_minutes': avg_waiting_first_reply_minutes,
            'avg_conversation_minutes': avg_conversation_minutes,
        },
    }
    return render(request, 'manage/support_agent_detail.html', context)


@_staff_required
@require_POST
def support_toggle_availability(request, user_id):
    """
    تبديل توفر ممثل خدمة العملاء:
      - المسؤول/المدير: يغيّر أي ممثل
      - الممثل: يغيّر نفسه فقط
    """
    target_user = get_object_or_404(User, pk=user_id)
    profile_obj, _ = UserProfile.objects.get_or_create(user=target_user)
    actor_is_support_admin = _is_support_admin(request.user)
    actor_account_type = getattr(getattr(request.user, 'profile', None), 'account_type', '') or ''
    actor_is_agent = (actor_account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE and not actor_is_support_admin)

    if profile_obj.account_type != UserProfile.ACCOUNT_CUSTOMER_SERVICE:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'not_customer_service_agent'}, status=400)
        messages.error(request, 'هذه الخاصية متاحة فقط لممثلي خدمة العملاء.')
        return redirect('manage:support_portal')

    if not actor_is_support_admin and not (actor_is_agent and request.user.id == target_user.id):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)
        messages.error(request, 'لا تملك صلاحية تغيير حالة هذا الموظف.')
        return redirect('manage:support_portal')

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

    payload = _availability_payload(profile_obj)
    payload.update({
        'success': True,
        'user_id': target_user.id,
    })
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(payload)

    status_text = 'متوفر' if profile_obj.is_available else 'غير متوفر'
    messages.success(request, f'تم تحديث حالة ممثل خدمة العملاء إلى: {status_text}')
    return redirect(request.POST.get('next') or 'manage:support_team_accounts')


def _support_support_admin(request) -> bool:
    return bool(request.user.is_superuser or _is_customer_service_manager(request.user))


def _support_plain_cs_agent(request) -> bool:
    account_type = getattr(getattr(request.user, 'profile', None), 'account_type', '') or ''
    return account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE and not _support_support_admin(request)


def _support_can_act_support_chat(request) -> bool:
    """مسؤول خدمة عملاء أو سوبر أو ممثل خدمة عملاء."""
    account_type = getattr(getattr(request.user, 'profile', None), 'account_type', '') or ''
    return (
        request.user.is_superuser
        or _is_customer_service_manager(request.user)
        or account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE
    )


def _support_append_audit(thread: SupportThread, event_type: str, actor, payload=None):
    SupportThreadAuditEvent.objects.create(
        thread=thread,
        event_type=event_type,
        actor=actor,
        payload=payload or {},
    )


def _support_all_customer_messages_read(thread: SupportThread, user) -> bool:
    cust_ids = list(
        SupportMessage.objects.filter(
            thread=thread,
            sender_type=SupportMessage.SENDER_CUSTOMER,
        ).values_list('id', flat=True)
    )
    if not cust_ids:
        return True
    n_read = SupportCustomerMessageRead.objects.filter(
        reader=user,
        message_id__in=cust_ids,
    ).count()
    return n_read >= len(cust_ids)


def _support_thread_ui_flags(request, thread: SupportThread) -> dict:
    """حقول لواجهة الاستطلاع / الإرسال (استلام، قراءة إلزامية)."""
    is_admin = _support_support_admin(request)
    plain = _support_plain_cs_agent(request)
    assignee_id = thread.assigned_staff_id
    viewer_is_assignee = assignee_id == request.user.id
    viewer_must_claim = (
        plain
        and thread.status == SupportThread.STATUS_WAITING
        and assignee_id is None
        and not thread.is_archived
    )
    enforce_read = (
        plain
        and viewer_is_assignee
        and thread.status != SupportThread.STATUS_ENDED
        and not thread.is_archived
    )
    all_read = (
        _support_all_customer_messages_read(thread, request.user)
        if viewer_is_assignee
        else True
    )
    return {
        'viewer_must_claim': viewer_must_claim,
        'viewer_is_assignee': viewer_is_assignee,
        'enforce_read_before_send': enforce_read,
        'all_customer_messages_read': bool(all_read) if enforce_read else True,
        'assigned_staff_id': assignee_id,
        'assigned_staff_username': thread.assigned_staff.username if thread.assigned_staff_id else '',
        'viewer_is_support_admin': is_admin,
        'send_blocked_until_claim': bool(
            plain
            and thread.status == SupportThread.STATUS_WAITING
            and assignee_id is None
        ),
        'send_blocked_until_read': bool(enforce_read and not all_read),
    }


# ================= خدمة العملاء (الدردشة) =================

def _support_thread_auto_timeout_process(thread: SupportThread, now):
    """
    نفس منطق العميل لكن على طرف الموظف/المدير.
    """
    if thread.is_archived or thread.ended_at is not None or thread.status == SupportThread.STATUS_ENDED:
        return
    if not thread.last_staff_message_at:
        return

    last_staff = thread.last_staff_message_at
    last_customer = thread.last_customer_message_at
    customer_responded_after_staff = bool(last_customer and last_customer >= last_staff)
    if customer_responded_after_staff:
        return

    delta_seconds = (now - last_staff).total_seconds()
    if thread.warning_sent_at is None and delta_seconds >= 5 * 60:
        SupportMessage.objects.create(
            thread=thread,
            sender_type=SupportMessage.SENDER_SYSTEM,
            text='تنبيه: لم نتلق ردًا من العميل. سيتم إغلاق المحادثة بعد 10 دقائق.'
        )
        thread.warning_sent_at = now
        thread.updated_at = now
        thread.save(update_fields=['warning_sent_at', 'updated_at'])
        return

    if delta_seconds >= 15 * 60:
        SupportMessage.objects.create(
            thread=thread,
            sender_type=SupportMessage.SENDER_SYSTEM,
            text='تم إغلاق المحادثة تلقائيًا لعدم وجود تفاعل من العميل. يمكنك بدء محادثة جديدة الآن.'
        )
        thread.status = SupportThread.STATUS_ENDED
        thread.ended_at = now
        thread.ended_by_type = 'system'
        thread.warning_sent_at = None
        thread.updated_at = now
        thread.save(update_fields=['status', 'ended_at', 'ended_by_type', 'warning_sent_at', 'updated_at'])


def _support_staff_can_access_thread(request, thread: SupportThread) -> bool:
    if not support_thread_customer_engaged(thread):
        return False
    if request.user.is_superuser or _is_customer_service_manager(request.user):
        return True
    account_type = getattr(getattr(request.user, 'profile', None), 'account_type', '') or ''
    if account_type != UserProfile.ACCOUNT_CUSTOMER_SERVICE:
        return False
    # طابور عام: محادثات انتظار غير مسندة
    if thread.status == SupportThread.STATUS_WAITING and not thread.assigned_staff_id:
        return True
    # بعد الاستلام: المكلف فقط
    return thread.assigned_staff_id == request.user.id


def _support_end_message_text(thread: SupportThread) -> str:
    """رسالة نهاية موحّدة لواجهات خدمة العملاء."""
    if not thread or thread.status != SupportThread.STATUS_ENDED:
        return ''
    customer_label = thread.customer_user.username if thread.customer_user_id else (thread.guest_phone or 'العميل')
    if thread.ended_by_type == 'customer':
        return f'لقد تم إنهاء الدردشة من قبل ({customer_label}).'
    if thread.ended_by_type == 'staff':
        return 'لقد تم إنهاء الدردشة من قبل خدمة العملاء.'
    if thread.ended_by_type == 'system':
        return 'لقد تم إنهاء الجلسة تلقائيًا بسبب عدم وجود رد من قبل العميل.'
    return 'لقد تم إنهاء الدردشة.'


def _support_pending_seconds(thread: SupportThread, now):
    """ثواني الانتظار منذ أول رسالة من العميل."""
    base_dt = thread.last_customer_message_at
    if not base_dt:
        return 0
    return max(0, int((now - base_dt).total_seconds()))


def _support_sla_state(pending_seconds, warning_minutes=7, critical_minutes=20):
    warning_seconds = int(warning_minutes * 60)
    critical_seconds = int(critical_minutes * 60)
    if pending_seconds >= critical_seconds:
        return 'critical'
    if pending_seconds >= warning_seconds:
        return 'warning'
    return 'ok'


def _support_format_duration(seconds_value):
    seconds = int(seconds_value or 0)
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f'{hours:02d}:{minutes:02d}:{secs:02d}'
    return f'{minutes:02d}:{secs:02d}'


def _support_thread_timing_maps(thread_ids):
    """يبني خرائط أول رسالة عميل/أول رسالة موظف/آخر رسالة لكل محادثة."""
    first_customer = {}
    first_staff = {}
    last_message = {}
    if not thread_ids:
        return first_customer, first_staff, last_message

    msg_rows = SupportMessage.objects.filter(
        thread_id__in=thread_ids,
        sender_type__in=[SupportMessage.SENDER_CUSTOMER, SupportMessage.SENDER_STAFF],
    ).order_by('thread_id', 'created_at').values('thread_id', 'sender_type', 'created_at')

    for row in msg_rows:
        tid = row['thread_id']
        sender_type = row['sender_type']
        created_at = row['created_at']
        if tid not in last_message or created_at > last_message[tid]:
            last_message[tid] = created_at
        if sender_type == SupportMessage.SENDER_CUSTOMER and tid not in first_customer:
            first_customer[tid] = created_at
        elif sender_type == SupportMessage.SENDER_STAFF and tid not in first_staff:
            first_staff[tid] = created_at
    return first_customer, first_staff, last_message


def _support_attach_thread_timing(threads, now=None):
    """
    يضيف على كل Thread:
      - waiting_response_seconds/label: انتظار أول رد من الموظف
      - conversation_seconds/label: مدة المحادثة الفعلية
    """
    if not threads:
        return
    now = now or timezone.now()
    thread_ids = [t.id for t in threads]
    first_customer, first_staff, last_message = _support_thread_timing_maps(thread_ids)

    for thread in threads:
        tid = thread.id
        first_customer_at = first_customer.get(tid)
        first_staff_at = first_staff.get(tid)
        end_point = thread.ended_at or last_message.get(tid) or now

        waiting_seconds = 0
        if first_customer_at and first_staff_at and first_staff_at >= first_customer_at:
            waiting_seconds = int((first_staff_at - first_customer_at).total_seconds())
        elif first_customer_at and thread.status != SupportThread.STATUS_ENDED:
            waiting_seconds = int((now - first_customer_at).total_seconds())

        conversation_seconds = 0
        if first_staff_at and end_point and end_point >= first_staff_at:
            conversation_seconds = int((end_point - first_staff_at).total_seconds())
        elif first_customer_at and end_point and end_point >= first_customer_at:
            conversation_seconds = int((end_point - first_customer_at).total_seconds())

        thread.waiting_response_seconds = max(0, waiting_seconds)
        thread.waiting_response_label = _support_format_duration(thread.waiting_response_seconds)
        thread.conversation_seconds = max(0, conversation_seconds)
        thread.conversation_label = _support_format_duration(thread.conversation_seconds)


def _support_portal_threads_qs_for_user(request, tab='unanswered', agent_id=None):
    """مصدر موحّد لاستعلامات بوابة خدمة العملاء (قائمة المدير/الموظف)."""
    is_manager = bool(request.user.is_superuser or _is_customer_service_manager(request.user))
    account_type = getattr(getattr(request.user, 'profile', None), 'account_type', '') or ''
    is_agent = (account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE and not is_manager)

    tab = (tab or 'unanswered').strip()
    base = SupportThread.objects.select_related('customer_user', 'assigned_staff')

    if is_manager:
        if tab == 'unanswered':
            qs = base.filter(is_archived=False).filter(
                Q(
                    status=SupportThread.STATUS_WAITING,
                    assigned_staff__isnull=True,
                )
                | Q(status=SupportThread.STATUS_ACTIVE, last_customer_message_at__isnull=False)
            ).filter(support_staff_visible_q()).filter(
                Q(last_staff_message_at__isnull=True)
                | Q(last_customer_message_at__gt=F('last_staff_message_at'))
            )
        elif tab == 'active':
            qs = base.filter(
                is_archived=False,
                status=SupportThread.STATUS_ACTIVE,
            )
        else:
            archived = tab == 'archived'
            qs = base.filter(is_archived=archived, status=SupportThread.STATUS_ENDED)
        if agent_id:
            try:
                qs = qs.filter(assigned_staff_id=int(agent_id))
            except Exception:
                pass
        return qs

    if is_agent:
        return base.filter(is_archived=False).filter(support_staff_visible_q()).filter(
            Q(status=SupportThread.STATUS_WAITING, assigned_staff__isnull=True) |
            Q(assigned_staff_id=request.user.id) |
            Q(messages__sender_type=SupportMessage.SENDER_STAFF, messages__staff_user_id=request.user.id)
        ).distinct()

    return base.none()


@_staff_required
def support_portal(request):
    """
    بوابة خدمة العملاء:
      - مدير المنظومة أو مسؤول خدمة العملاء: غير المُجاب + المنتهي + الأرشيف + إحصائيات الموظفين
      - موظف خدمة العملاء: قائمة محادثاته
    """
    is_manager = bool(request.user.is_superuser or _is_customer_service_manager(request.user))
    account_type = getattr(getattr(request.user, 'profile', None), 'account_type', '') or ''
    is_agent = (account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE and not is_manager)

    tab = (request.GET.get('tab') or 'unanswered').strip()
    agent_id = request.GET.get('agent_id')

    if is_manager:
        threads_qs = _support_portal_threads_qs_for_user(request, tab=tab, agent_id=agent_id)
        threads = list(threads_qs.order_by('-updated_at')[:200])
        now = timezone.now()
        _support_attach_thread_timing(threads, now=now)
        for thread in threads:
            pending_seconds = _support_pending_seconds(thread, now)
            mins = pending_seconds // 60
            secs = pending_seconds % 60
            thread.pending_seconds = pending_seconds
            thread.pending_label = f'{mins:02d}:{secs:02d}'
            thread.sla_state = _support_sla_state(pending_seconds)

        unanswered_qs = _support_portal_threads_qs_for_user(request, tab='unanswered', agent_id=None)
        unanswered_threads = list(unanswered_qs.order_by('-updated_at')[:400])
        warning_count = 0
        critical_count = 0
        for thread in unanswered_threads:
            state = _support_sla_state(_support_pending_seconds(thread, now))
            if state == 'critical':
                critical_count += 1
            elif state == 'warning':
                warning_count += 1

        avg_first_response_minutes = 0.0
        recent_ended = list(
            SupportThread.objects.filter(
                status=SupportThread.STATUS_ENDED,
                is_archived=False,
                assigned_staff__isnull=False,
            ).order_by('-updated_at')[:300]
        )
        if recent_ended:
            ended_ids = [t.id for t in recent_ended]
            first_customer, first_staff, _ = _support_thread_timing_maps(ended_ids)
            deltas = []
            for tid, c_at in first_customer.items():
                s_at = first_staff.get(tid)
                if s_at and s_at >= c_at:
                    deltas.append((s_at - c_at).total_seconds())
            if deltas:
                avg_first_response_minutes = round((sum(deltas) / len(deltas)) / 60.0, 1)

        return render(request, 'manage/support_portal.html', {
            'is_manager': True,
            'tab': tab,
            'threads': threads,
            'agent_id': agent_id,
            'support_metrics': {
                'unanswered_total': len(unanswered_threads),
                'warning_count': warning_count,
                'critical_count': critical_count,
                'avg_first_response_minutes': avg_first_response_minutes,
            },
        })

    if is_agent:
        threads_qs = _support_portal_threads_qs_for_user(request, tab=tab, agent_id=agent_id)
        threads = list(threads_qs.order_by('-updated_at')[:200])
        now = timezone.now()
        _support_attach_thread_timing(threads, now=now)
        for thread in threads:
            pending_seconds = _support_pending_seconds(thread, now)
            mins = pending_seconds // 60
            secs = pending_seconds % 60
            thread.pending_seconds = pending_seconds
            thread.pending_label = f'{mins:02d}:{secs:02d}'
            thread.sla_state = _support_sla_state(pending_seconds)
        agent_profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return render(request, 'manage/support_portal.html', {
            'is_manager': False,
            'threads': threads,
            'agent_is_available': bool(agent_profile.is_available),
        })

    # fallback: لا يجب الوصول هنا
    return redirect('manage:support_portal')


@_staff_required
def support_thread_detail(request, thread_id):
    thread = get_object_or_404(SupportThread.objects.select_related('assigned_staff'), pk=thread_id)
    _support_thread_auto_timeout_process(thread, timezone.now())
    thread.refresh_from_db()

    if not _support_staff_can_access_thread(request, thread):
        messages.error(request, _('لا تملك صلاحية الوصول لهذه المحادثة.'))
        return redirect('manage:support_portal')

    messages_qs = SupportMessage.objects.filter(thread=thread).order_by('created_at').select_related('staff_user')[:250]

    # تأكد من عدد الرسائل
    messages_list = list(messages_qs)
    can_send = (thread.status != SupportThread.STATUS_ENDED and not thread.is_archived)
    ui = _support_thread_ui_flags(request, thread)
    show_claim_btn = bool(ui['viewer_must_claim'] and can_send)
    support_can_compose = bool(
        can_send
        and not ui['send_blocked_until_claim']
        and not ui['send_blocked_until_read']
    )
    audit_events = list(
        thread.audit_events.select_related('actor').order_by('created_at')
    )

    return render(request, 'manage/support_thread_detail.html', {
        'thread': thread,
        'chat_messages': messages_list,
        'can_send': can_send,
        'support_can_compose': support_can_compose,
        'end_message_text': _support_end_message_text(thread),
        'show_claim_btn': show_claim_btn,
        'audit_events': audit_events,
        'support_ui_initial': ui,
    })


@_staff_required
def support_thread_messages_json(request, thread_id):
    thread = get_object_or_404(SupportThread.objects.select_related('assigned_staff'), pk=thread_id)
    if not _support_staff_can_access_thread(request, thread):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)

    now = timezone.now()
    _support_thread_auto_timeout_process(thread, now)
    thread.refresh_from_db()

    messages = list(
        SupportMessage.objects.filter(thread=thread).order_by('created_at')[:150]
    )
    out_msgs = []
    for m in messages:
        if m.sender_type == SupportMessage.SENDER_SYSTEM:
            meta = getattr(m, 'metadata', None) or {}
            if not isinstance(meta, dict):
                meta = {}
            if meta.get('kind') != BOT_KIND and (m.text or '').strip() != SUPPORT_AUTO_WAITING_REPLY:
                continue
        meta = getattr(m, 'metadata', None) or {}
        is_bot = (
            m.sender_type == SupportMessage.SENDER_SYSTEM
            and isinstance(meta, dict)
            and meta.get('kind') == BOT_KIND
        )
        out_msgs.append({
            'id': m.id,
            'sender_type': m.sender_type,
            'is_bot': is_bot,
            'text': m.text or '',
            'image_url': m.image.url if getattr(m, 'image', None) else '',
            'created_at': m.created_at.isoformat() if m.created_at else '',
        })

    ui = _support_thread_ui_flags(request, thread)
    thread_payload = {
        'id': thread.id,
        'status': thread.status,
        'status_display': thread.get_status_display(),
        'ended_at': thread.ended_at.isoformat() if thread.ended_at else None,
        'end_message': _support_end_message_text(thread),
    }
    thread_payload.update(ui)

    return JsonResponse({
        'success': True,
        'thread': thread_payload,
        'messages': out_msgs,
    })


@_staff_required
def support_portal_signature_json(request):
    """
    توقيع خفيف لبوابة خدمة العملاء.
    عند تغيّر الحالة/عدد المحادثات/آخر تحديث، يتغير التوقيع.
    """
    tab = (request.GET.get('tab') or 'ended').strip()
    agent_id = request.GET.get('agent_id')
    qs = _support_portal_threads_qs_for_user(request, tab=tab, agent_id=agent_id)
    agg = qs.aggregate(last_updated=Max('updated_at'), rows=Count('id'))
    last_updated = agg.get('last_updated')
    rows = int(agg.get('rows') or 0)
    signature = f"{tab}|{agent_id or ''}|{rows}|{last_updated.isoformat() if last_updated else ''}"
    return JsonResponse({'success': True, 'signature': signature})


@require_POST
@_staff_required
def support_thread_send_json(request, thread_id):
    thread = get_object_or_404(SupportThread, pk=thread_id, is_archived=False)
    if not _support_staff_can_access_thread(request, thread):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)
    if thread.status == SupportThread.STATUS_ENDED:
        return JsonResponse({'success': False, 'error': 'thread_ended'}, status=400)

    text = (request.POST.get('message') or '').strip()
    images = request.FILES.getlist('image')
    ok_imgs, img_err = validate_chat_image_files(images)
    if img_err:
        return JsonResponse(img_err, status=400)
    images = ok_imgs
    if not text and not images:
        return JsonResponse({'success': False, 'error': 'message_or_image_required'}, status=400)
    if text and len(text) > 2000:
        return JsonResponse({'success': False, 'error': 'message_too_long'}, status=400)

    now = timezone.now()
    with transaction.atomic():
        thread = SupportThread.objects.select_for_update().get(pk=thread_id)
        _support_thread_auto_timeout_process(thread, now)
        thread.refresh_from_db()
        if thread.status == SupportThread.STATUS_ENDED:
            return JsonResponse({'success': False, 'error': 'thread_ended_now'}, status=400)

        is_admin = _support_support_admin(request)

        # استلام صريح للمندوب؛ المسؤول يُسند في أول إرسال ضمنياً
        if thread.status == SupportThread.STATUS_WAITING:
            if thread.assigned_staff_id is None:
                if is_admin:
                    thread.assigned_staff = request.user
                    if thread.claimed_at is None:
                        thread.claimed_at = now
                    thread.save(update_fields=['assigned_staff', 'claimed_at', 'updated_at'])
                    _support_append_audit(
                        thread,
                        SupportThreadAuditEvent.EVENT_THREAD_CLAIMED,
                        request.user,
                        {'via': 'implicit_send'},
                    )
                else:
                    return JsonResponse({'success': False, 'error': 'must_claim_first'}, status=400)
            elif thread.assigned_staff_id != request.user.id:
                return JsonResponse({'success': False, 'error': 'claimed_by_another_agent'}, status=409)

        if not is_admin and thread.assigned_staff_id == request.user.id:
            if not _support_all_customer_messages_read(thread, request.user):
                return JsonResponse({'success': False, 'error': 'must_read_customer_messages'}, status=400)

        if images:
            for idx, image in enumerate(images):
                SupportMessage.objects.create(
                    thread=thread,
                    sender_type=SupportMessage.SENDER_STAFF,
                    staff_user=request.user,
                    text=text if idx == 0 else '',
                    image=image,
                )
        else:
            SupportMessage.objects.create(
                thread=thread,
                sender_type=SupportMessage.SENDER_STAFF,
                staff_user=request.user,
                text=text,
                image=None,
            )

        # تحديث الحالة/التوقيتات
        thread.last_staff_message_at = now
        thread.warning_sent_at = None
        if thread.status == SupportThread.STATUS_WAITING:
            thread.status = SupportThread.STATUS_ACTIVE
        thread.updated_at = now
        thread.save(update_fields=['assigned_staff', 'claimed_at', 'last_staff_message_at', 'warning_sent_at', 'status', 'updated_at'])

    return JsonResponse({'success': True})


@require_POST
@_staff_required
def support_thread_end_json(request, thread_id):
    thread = get_object_or_404(SupportThread, pk=thread_id, is_archived=False)
    if not _support_staff_can_access_thread(request, thread):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)
    if thread.status == SupportThread.STATUS_ENDED:
        return JsonResponse({'success': True})

    now = timezone.now()
    SupportMessage.objects.create(
        thread=thread,
        sender_type=SupportMessage.SENDER_SYSTEM,
        text='تم إنهاء الدردشة من قبل موظف خدمة العملاء. يمكنك بدء محادثة جديدة في أي وقت.'
    )
    thread.status = SupportThread.STATUS_ENDED
    thread.ended_at = now
    thread.ended_by_type = 'staff'
    thread.warning_sent_at = None
    thread.updated_at = now
    thread.save(update_fields=['status', 'ended_at', 'ended_by_type', 'warning_sent_at', 'updated_at'])

    _support_append_audit(thread, SupportThreadAuditEvent.EVENT_THREAD_ENDED_STAFF, request.user, {})

    return JsonResponse({'success': True})


@require_POST
@_staff_required
def support_thread_claim_json(request, thread_id):
    """استلام المحادثة (طابور عام) قبل الإرسال للمندوب العادي."""
    thread = get_object_or_404(SupportThread, pk=thread_id, is_archived=False)
    if not _support_can_act_support_chat(request):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)

    # من قائمة الانتظار: السماح برمز تعارض واضح بدل رفض صمتي للمندوب الآخر
    if (
        thread.status == SupportThread.STATUS_WAITING
        and thread.assigned_staff_id
        and thread.assigned_staff_id != request.user.id
        and _support_plain_cs_agent(request)
    ):
        return JsonResponse({'success': False, 'error': 'claimed_by_another_agent'}, status=409)

    if not _support_staff_can_access_thread(request, thread):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)
    if thread.status != SupportThread.STATUS_WAITING:
        return JsonResponse({'success': False, 'error': 'thread_not_waiting'}, status=400)

    now = timezone.now()
    with transaction.atomic():
        thread = SupportThread.objects.select_for_update().get(pk=thread_id)
        if thread.status != SupportThread.STATUS_WAITING or thread.is_archived:
            return JsonResponse({'success': False, 'error': 'thread_not_waiting'}, status=400)
        if thread.assigned_staff_id and thread.assigned_staff_id != request.user.id:
            return JsonResponse({'success': False, 'error': 'claimed_by_another_agent'}, status=409)
        if thread.assigned_staff_id == request.user.id:
            return JsonResponse({'success': True, 'already_claimed': True})

        thread.assigned_staff = request.user
        thread.claimed_at = now
        thread.updated_at = now
        thread.save(update_fields=['assigned_staff', 'claimed_at', 'updated_at'])

    _support_append_audit(thread, SupportThreadAuditEvent.EVENT_THREAD_CLAIMED, request.user, {'via': 'explicit_claim'})
    return JsonResponse({'success': True})


@require_POST
@_staff_required
def support_thread_mark_read_json(request, thread_id):
    """تسجيل قراءة رسائل العميل للمكلف (إلزامي قبل الإرسال)."""
    thread = get_object_or_404(SupportThread, pk=thread_id, is_archived=False)
    if not _support_staff_can_access_thread(request, thread):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)
    if thread.assigned_staff_id != request.user.id:
        return JsonResponse({'success': False, 'error': 'only_assignee_can_mark_read'}, status=403)

    mark_all = (request.POST.get('mark_all') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    raw_ids = (request.POST.get('message_ids') or '').strip()

    valid_ids = set(
        SupportMessage.objects.filter(
            thread=thread,
            sender_type=SupportMessage.SENDER_CUSTOMER,
        ).values_list('id', flat=True)
    )
    if mark_all:
        ids_to_mark = sorted(valid_ids)
    else:
        parsed = []
        for part in raw_ids.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                pid = int(part)
            except ValueError:
                continue
            if pid in valid_ids:
                parsed.append(pid)
        ids_to_mark = sorted(set(parsed))

    existing = set(
        SupportCustomerMessageRead.objects.filter(
            reader=request.user,
            message_id__in=ids_to_mark,
        ).values_list('message_id', flat=True)
    )
    new_ids = [i for i in ids_to_mark if i not in existing]
    if new_ids:
        SupportCustomerMessageRead.objects.bulk_create(
            [SupportCustomerMessageRead(message_id=i, reader=request.user) for i in new_ids],
            ignore_conflicts=True,
        )

    if new_ids:
        _support_append_audit(
            thread,
            SupportThreadAuditEvent.EVENT_MESSAGES_MARKED_READ,
            request.user,
            {'message_ids': new_ids, 'marked_new_count': len(new_ids)},
        )

    return JsonResponse({
        'success': True,
        'marked_new_count': len(new_ids),
        'all_customer_messages_read': _support_all_customer_messages_read(thread, request.user),
    })


@require_POST
@_staff_required
def support_archive_thread(request, thread_id):
    if not _is_support_admin(request.user):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)

    thread = get_object_or_404(SupportThread, pk=thread_id)
    thread.is_archived = True
    thread.archived_at = timezone.now()
    thread.save(update_fields=['is_archived', 'archived_at'])
    return redirect('manage:support_portal')


@require_POST
@_staff_required
def support_archive_agent(request, agent_id):
    if not _is_support_admin(request.user):
        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)

    agent = get_object_or_404(User, pk=agent_id)
    SupportThread.objects.filter(
        assigned_staff=agent,
        status=SupportThread.STATUS_ENDED,
        is_archived=False,
    ).update(
        is_archived=True,
        archived_at=timezone.now(),
    )
    return redirect('manage:support_portal')
