"""واجهات خدمة العملاء (الدردشة)."""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import support_bot
from .models import SupportMessage, SupportThread
from .support_engagement import support_thread_customer_engaged
from .upload_validation import validate_chat_image_files


def _support_get_guest_phone_from_request(request):
    return (request.session.get('support_guest_phone') or '').strip()


def _support_resolve_identity(request):
    """
    يرجع dict يحتوي:
      - customer_user (إذا مسجل)
      - guest_phone (للضيف)
    """
    if request.user.is_authenticated:
        return {'customer_user': request.user, 'guest_phone': None}
    guest_phone = _support_get_guest_phone_from_request(request)
    return {'customer_user': None, 'guest_phone': guest_phone or None}


def _support_find_active_thread_for_identity(request, identity):
    """يعيد محادثة قائمة لنفس الهوية دون إنشاء سجل جديد."""
    thread_id = request.session.get('support_thread_id')
    if thread_id:
        try:
            t = SupportThread.objects.select_related('customer_user', 'assigned_staff').get(pk=int(thread_id))
            if t.is_archived or t.status == SupportThread.STATUS_ENDED:
                thread_id = None
            else:
                if identity.get('customer_user') and t.customer_user_id == identity['customer_user'].id:
                    return t
                if identity.get('guest_phone') and (t.guest_phone or '') == identity['guest_phone']:
                    return t
        except Exception:
            thread_id = None

    qs = SupportThread.objects.select_related('customer_user', 'assigned_staff').filter(is_archived=False)
    if identity.get('customer_user'):
        qs = qs.filter(customer_user=identity['customer_user'])
    if identity.get('guest_phone'):
        qs = qs.filter(guest_phone=identity['guest_phone'])

    return qs.filter(
        status__in=[SupportThread.STATUS_WAITING, SupportThread.STATUS_ACTIVE],
        ended_at__isnull=True,
    ).order_by('-updated_at').first()


def _support_create_fresh_customer_thread(request, identity):
    """محادثة جديدة بعد إنهاء سابقة — دون إعادة استخدام محادثة منتهية."""
    t = SupportThread.objects.create(
        customer_user=identity.get('customer_user'),
        guest_phone=(identity.get('guest_phone') or ''),
        status=SupportThread.STATUS_WAITING,
        assigned_staff=None,
        last_customer_message_at=None,
        last_staff_message_at=None,
        warning_sent_at=None,
        ended_at=None,
        ended_by_type='',
    )
    request.session['support_thread_id'] = str(t.id)
    return t


def _support_get_or_create_thread_for_identity(request, identity):
    active = _support_find_active_thread_for_identity(request, identity)
    if active:
        request.session['support_thread_id'] = str(active.id)
        return active

    t = SupportThread.objects.create(
        customer_user=identity.get('customer_user'),
        guest_phone=(identity.get('guest_phone') or ''),
        status=SupportThread.STATUS_WAITING,
        # طابور مشترك: تُسند المحادثة لأول موظف يرد
        assigned_staff=None,
        last_customer_message_at=None,
        last_staff_message_at=None,
        warning_sent_at=None,
        ended_at=None,
        ended_by_type='',
    )
    request.session['support_thread_id'] = str(t.id)
    return t


def _support_auto_timeout_process(thread: SupportThread, now):
    """
    - بعد 5 دقائق من آخر رسالة موظف بدون رد من العميل: إرسال تنبيه
    - بعد 15 دقيقة: إنهاء تلقائي
    """
    if thread.is_archived or thread.ended_at is not None or thread.status == SupportThread.STATUS_ENDED:
        return
    if not thread.last_staff_message_at:
        return

    last_staff = thread.last_staff_message_at
    last_customer = thread.last_customer_message_at

    # هل العميل رد بعد رسالة الموظف الأخيرة؟
    customer_responded_after_staff = bool(last_customer and last_customer >= last_staff)
    if customer_responded_after_staff:
        # بما أن العميل رد: لا تنبيه ولا إنهاء
        return

    delta = now - last_staff
    if thread.warning_sent_at is None and delta.total_seconds() >= 5 * 60:
        SupportMessage.objects.create(
            thread=thread,
            sender_type=SupportMessage.SENDER_SYSTEM,
            text='تنبيه: لم نتلق ردًا من العميل. سيتم إغلاق المحادثة بعد 10 دقائق.'
        )
        thread.warning_sent_at = now
        thread.updated_at = now
        thread.save(update_fields=['warning_sent_at', 'updated_at'])
        return

    if delta.total_seconds() >= 15 * 60:
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


def _support_fetch_messages(thread: SupportThread, limit=120):
    return list(
        thread.messages.select_related('staff_user').order_by('created_at')[:limit]
    )


def _support_messages_to_json(messages):
    out = []
    for m in messages:
        sender_type = m.sender_type if hasattr(m, 'sender_type') else m.get('sender_type')
        text = m.text if hasattr(m, 'text') else (m.get('text') or '')
        created_at = m.created_at if hasattr(m, 'created_at') else m.get('created_at')
        image_url = ''
        if hasattr(m, 'image'):
            image_url = m.image.url if getattr(m, 'image', None) else ''
        else:
            image_url = m.get('image_url') or ''

        if sender_type == SupportMessage.SENDER_SYSTEM:
            meta = {}
            if hasattr(m, 'metadata') and m.metadata is not None:
                meta = m.metadata
            if isinstance(meta, dict) and meta.get('kind') == support_bot.BOT_KIND:
                out.append({
                    'id': m.id if hasattr(m, 'id') else m.get('id'),
                    'sender_type': 'system',
                    'is_bot': True,
                    'text': text,
                    'image_url': image_url,
                    'quick_replies': meta.get('quick_replies') or [],
                    'created_at': (created_at.isoformat() if created_at else ''),
                })
                continue
            # إظهار رسالة الانتظار الترحيبية فقط للعميل، وإخفاء رسائل النظام الأخرى.
            if (text or '').strip() != support_bot.SUPPORT_AUTO_WAITING_REPLY:
                continue
        out.append({
            'id': m.id if hasattr(m, 'id') else m.get('id'),
            'sender_type': sender_type,
            'is_bot': False,
            'text': text,
            'image_url': image_url,
            'quick_replies': [],
            'created_at': (created_at.isoformat() if created_at else ''),
        })
    return out


def _support_end_message_text(thread: SupportThread) -> str:
    """رسالة ختامية واضحة حسب الجهة التي أنهت الدردشة."""
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


def support_new_conversation(request):
    """
    يبدأ الضيف محادثة جديدة: يمسح رقم الجوال/الجلسة في الجلسة ويعيد صفحة إدخال الرقم.
    (المسجّلون: إعادة توجيه بسيطة لنفس صفحة الدعم)
    """
    if request.user.is_authenticated:
        return redirect('support_chat')
    request.session.pop('support_guest_phone', None)
    request.session.pop('support_thread_id', None)
    for k in list(request.session.keys()):
        if isinstance(k, str) and k.startswith('support_bot_'):
            request.session.pop(k, None)
    request.session.modified = True
    return redirect('support_chat')


def support_chat(request):
    """
    صفحة المحادثة للعميل/الضيف.
    - للضيف: يحتاج رقم جوال قبل بدء المحادثة
    """
    if request.method == 'POST':
        guest_phone = (request.POST.get('guest_phone') or '').strip()
        if guest_phone and not request.user.is_authenticated:
            request.session['support_guest_phone'] = guest_phone
            request.session.pop('support_thread_id', None)
            return redirect('support_chat')

    identity = _support_resolve_identity(request)

    guest_needs_phone = (identity.get('customer_user') is None and not identity.get('guest_phone'))
    thread = None
    viewer_label = ''
    if not guest_needs_phone:
        if identity.get('customer_user'):
            viewer_label = identity['customer_user'].username
        elif identity.get('guest_phone'):
            viewer_label = identity['guest_phone'] or 'العميل'
        thread = _support_find_active_thread_for_identity(request, identity)
        if thread and support_thread_customer_engaged(thread):
            now = timezone.now()
            _support_auto_timeout_process(thread, now)
            thread.refresh_from_db()
        else:
            thread = None

    return render(request, 'store/support_chat.html', {
        'guest_needs_phone': guest_needs_phone,
        'thread': thread,
        'viewer_label': viewer_label,
        'end_message_text': _support_end_message_text(thread) if thread else '',
    })


def support_poll(request):
    """GET /support/poll/ — إرجاع أحدث الرسائل وحالة المحادثة."""
    identity = _support_resolve_identity(request)
    if identity.get('customer_user') is None and not identity.get('guest_phone'):
        return JsonResponse({'success': False, 'error': 'phone_required'}, status=400)

    thread_id = request.session.get('support_thread_id')
    thread = None
    if thread_id:
        try:
            thread_pk = int(thread_id)
        except (TypeError, ValueError):
            request.session.pop('support_thread_id', None)
            thread_pk = None
        if thread_pk is not None:
            try:
                thread = SupportThread.objects.select_related('assigned_staff').get(
                    pk=thread_pk,
                    is_archived=False,
                )
            except SupportThread.DoesNotExist:
                request.session.pop('support_thread_id', None)
                thread = None

    if thread:
        if identity.get('customer_user'):
            if thread.customer_user_id != identity['customer_user'].id:
                return JsonResponse({'success': False, 'error': 'thread_forbidden'}, status=403)
        if identity.get('guest_phone'):
            if (thread.guest_phone or '') != identity['guest_phone']:
                return JsonResponse({'success': False, 'error': 'thread_forbidden'}, status=403)

    if not thread or not support_thread_customer_engaged(thread):
        return JsonResponse({
            'success': True,
            'thread': {
                'id': None,
                'status': '',
                'status_display': '',
                'ended_at': None,
                'ended_by_type': '',
                'end_message': '',
            },
            'messages': support_bot.welcome_messages_for_client(),
        })

    now = timezone.now()
    _support_auto_timeout_process(thread, now)
    thread = SupportThread.objects.select_related('assigned_staff').get(pk=thread.id)

    messages = _support_fetch_messages(thread, limit=80)

    return JsonResponse({
        'success': True,
        'thread': {
            'id': thread.id,
            'status': thread.status,
            'status_display': thread.get_status_display(),
            'ended_at': thread.ended_at.isoformat() if thread.ended_at else None,
            'ended_by_type': thread.ended_by_type,
            'end_message': _support_end_message_text(thread),
        },
        'messages': _support_messages_to_json(messages),
    })


@require_POST
def support_send(request):
    """POST /support/send/ — إرسال رسالة للعميل."""
    identity = _support_resolve_identity(request)
    if identity.get('customer_user') is None and not identity.get('guest_phone'):
        return JsonResponse({'success': False, 'error': 'phone_required'}, status=400)

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

    thread_id = request.session.get('support_thread_id')
    thread = None
    if thread_id:
        try:
            thread = SupportThread.objects.get(pk=int(thread_id), is_archived=False)
        except Exception:
            thread = None

    started_fresh_after_end = False
    if not thread or thread.status == SupportThread.STATUS_ENDED:
        request.session.pop('support_thread_id', None)
        thread = _support_create_fresh_customer_thread(request, identity)

    # تحقق الهوية
    if identity.get('customer_user'):
        if thread.customer_user_id != identity['customer_user'].id:
            return JsonResponse({'success': False, 'error': 'thread_forbidden'}, status=403)
    if identity.get('guest_phone'):
        if (thread.guest_phone or '') != identity['guest_phone']:
            return JsonResponse({'success': False, 'error': 'thread_forbidden'}, status=403)

    now = timezone.now()
    _support_auto_timeout_process(thread, now)
    thread.refresh_from_db()
    if thread.status == SupportThread.STATUS_ENDED:
        request.session.pop('support_thread_id', None)
        thread = _support_create_fresh_customer_thread(request, identity)

    if not SupportMessage.objects.filter(thread=thread).exists():
        support_bot.ensure_bot_welcome_for_thread(thread)

    if images:
        for idx, image in enumerate(images):
            SupportMessage.objects.create(
                thread=thread,
                sender_type=SupportMessage.SENDER_CUSTOMER,
                staff_user=None,
                text=text if idx == 0 else '',
                image=image,
            )
    else:
        SupportMessage.objects.create(
            thread=thread,
            sender_type=SupportMessage.SENDER_CUSTOMER,
            staff_user=None,
            text=text,
            image=None,
        )
    thread.last_customer_message_at = now
    thread.warning_sent_at = None
    # إذا كان ما زال بانتظار الموظف، يبقى status كما هو
    thread.updated_at = now
    thread.save(update_fields=['last_customer_message_at', 'warning_sent_at', 'updated_at'])

    skip_first_waiting = False
    if not images:
        skip_first_waiting = bool(
            support_bot.process_support_bot_turn(request, thread, identity).get('skip_first_waiting')
        )

    if support_bot.should_send_auto_waiting_reply(
        thread,
        skip_first_waiting=skip_first_waiting,
    ):
        SupportMessage.objects.create(
            thread=thread,
            sender_type=SupportMessage.SENDER_SYSTEM,
            text=support_bot.SUPPORT_AUTO_WAITING_REPLY,
        )

    return JsonResponse({'success': True})


@require_POST
def support_end(request):
    """POST /support/end/ — إنهاء المحادثة من العميل/الضيف."""
    identity = _support_resolve_identity(request)
    if identity.get('customer_user') is None and not identity.get('guest_phone'):
        return JsonResponse({'success': False, 'error': 'phone_required'}, status=400)

    thread_id = request.session.get('support_thread_id')
    if not thread_id:
        return JsonResponse({'success': True})

    try:
        thread_pk = int(thread_id)
    except (TypeError, ValueError):
        request.session.pop('support_thread_id', None)
        return JsonResponse({'success': True})

    try:
        thread = SupportThread.objects.get(pk=thread_pk, is_archived=False)
    except SupportThread.DoesNotExist:
        request.session.pop('support_thread_id', None)
        return JsonResponse({'success': True})

    if not support_thread_customer_engaged(thread):
        return JsonResponse({'success': True})

    if identity.get('customer_user'):
        if thread.customer_user_id != identity['customer_user'].id:
            return JsonResponse({'success': False, 'error': 'thread_forbidden'}, status=403)
    if identity.get('guest_phone'):
        if (thread.guest_phone or '') != identity['guest_phone']:
            return JsonResponse({'success': False, 'error': 'thread_forbidden'}, status=403)

    if thread.status == SupportThread.STATUS_ENDED:
        return JsonResponse({'success': True})

    support_bot.end_thread_by_customer(thread)
    return JsonResponse({'success': True})
