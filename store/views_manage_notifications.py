"""إشعارات لوحة الإدارة وتعليم الصفوف كمُشاهَدة."""
import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .manage_decorators import _staff_required
from .manage_seen_utils import mark_seen_key
from .models import (
    Category,
    Compartment,
    ContactMessage,
    ManageSeenMarker,
    Order,
    Product,
    Return,
    Shelf,
    Shipment,
    SupportThread,
    UserProfile,
)
from .support_engagement import support_staff_visible_q
from .revenue_stats import get_revenue_stats_formatted


def _build_manage_notifications_payload(request):
    """
    بيانات عدّادات التنبيهات ولوحة التحكم للتحديث التلقائي (JSON).
    """
    now = timezone.now()
    max_age_days = int(getattr(settings, 'MANAGE_NEW_ROW_MAX_AGE_DAYS', 30))
    fresh_since = now - timedelta(days=max_age_days)

    orders_nav_badge = Order.objects.filter(
        Q(status=Order.STATUS_PENDING)
        | Q(
            payment_method=Order.PAYMENT_GATEWAY,
            payment_status=Order.PAY_STATUS_PENDING,
        )
    ).distinct().count()

    warehouse_badge = Order.objects.filter(
        status__in=[
            Order.STATUS_CONFIRMED,
            Order.STATUS_PROCESSING,
            Order.STATUS_READY,
        ]
    ).count()

    shipments_active = Shipment.objects.exclude(
        status__in=[Shipment.STATUS_DELIVERED, Shipment.STATUS_FAILED]
    ).count()

    returns_badge = Return.objects.filter(
        status__in=[Return.STATUS_REQUESTED, Return.STATUS_REVIEWING]
    ).count()

    # عداد رسائل الاتصال: غير مُشاهَد من المسؤول (بنفس منطق النقطة على الصف)
    contact_ids = list(
        ContactMessage.objects.filter(created_at__gte=fresh_since).values_list('id', flat=True)
    )
    contact_unread = 0
    if contact_ids:
        seen_contact_keys = set(
            ManageSeenMarker.objects.filter(
                user=request.user,
                key__in=[f'contact:{cid}' for cid in contact_ids],
            ).values_list('key', flat=True)
        )
        contact_unread = sum(1 for cid in contact_ids if f'contact:{cid}' not in seen_contact_keys)

    users_new = 0
    if request.user.is_superuser:
        # عداد المستخدمين: حسابات جديدة غير مُشاهَدة (بنفس منطق النقطة على الصف)
        user_ids = list(User.objects.filter(
            is_staff=False,
            is_superuser=False,
            date_joined__gte=fresh_since,
        ).values_list('id', flat=True))
        if user_ids:
            seen_user_keys = set(
                ManageSeenMarker.objects.filter(
                    user=request.user,
                    key__in=[f'user:{uid}' for uid in user_ids],
                ).values_list('key', flat=True)
            )
            users_new = sum(1 for uid in user_ids if f'user:{uid}' not in seen_user_keys)

    # عداد طلبات الدردشة الجديدة
    try:
        account_type = getattr(request.user.profile, 'account_type', '') or ''
    except Exception:
        account_type = ''
    if request.user.is_superuser:
        support_waiting = SupportThread.objects.filter(
            status=SupportThread.STATUS_WAITING,
            is_archived=False,
        ).filter(support_staff_visible_q()).count()
    elif account_type in (
        UserProfile.ACCOUNT_CUSTOMER_SERVICE,
        UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER,
    ):
        support_waiting = SupportThread.objects.filter(
            status=SupportThread.STATUS_WAITING,
            is_archived=False,
            assigned_staff__isnull=True,
        ).filter(support_staff_visible_q()).count()
    else:
        support_waiting = 0

    revenue = get_revenue_stats_formatted()

    order_stats = {
        'all': Order.objects.count(),
        'pending': Order.objects.filter(status=Order.STATUS_PENDING).count(),
        'confirmed': Order.objects.filter(status=Order.STATUS_CONFIRMED).count(),
        'processing': Order.objects.filter(status=Order.STATUS_PROCESSING).count(),
        'shipped': Order.objects.filter(status=Order.STATUS_SHIPPED).count(),
        'delivered': Order.objects.filter(status=Order.STATUS_DELIVERED).count(),
        'cancelled': Order.objects.filter(status=Order.STATUS_CANCELLED).count(),
        'guests': Order.objects.filter(customer_type=Order.CUSTOMER_GUEST).count(),
        'unpaid_gateway': Order.objects.filter(
            payment_method=Order.PAYMENT_GATEWAY,
            payment_status=Order.PAY_STATUS_PENDING,
        ).count(),
        **revenue,
    }

    returns_stats = {
        'all': Return.objects.count(),
        'pending': Return.objects.filter(
            status__in=[Return.STATUS_REQUESTED, Return.STATUS_REVIEWING]
        ).count(),
        'approved': Return.objects.filter(status=Return.STATUS_APPROVED).count(),
        'rejected': Return.objects.filter(status=Return.STATUS_REJECTED).count(),
        'completed': Return.objects.filter(status=Return.STATUS_COMPLETED).count(),
        'total_refund': revenue['refunds_total'],
    }

    dashboard = {
        'compartments': Compartment.objects.count(),
        'shelves': Shelf.objects.count(),
        'categories': Category.objects.count(),
        'products': Product.objects.count(),
        'orders': Order.objects.count(),
        'orders_pending': Order.objects.filter(status=Order.STATUS_PENDING).count(),
    }

    recent_orders = []
    for o in Order.objects.order_by('-created_at')[:10]:
        recent_orders.append({
            'id': o.id,
            'customer_name': o.customer_name,
            'customer_phone': o.customer_phone,
            'total': str(o.total),
            'status': o.status,
            'status_display': o.get_status_display(),
            'created_at': o.created_at.isoformat(),
            'detail_url': request.build_absolute_uri(
                reverse('manage:order_detail', args=[o.pk])
            ),
        })

    # موجز نشاط قصير للهيدر (آخر عمليات النظام)
    events = []
    for o in Order.objects.order_by('-updated_at')[:4]:
        events.append({
            'kind': 'order',
            'id': o.id,
            'label': f'طلب #{o.id} — {o.get_status_display()}',
            'when': o.updated_at.isoformat(),
            'url': reverse('manage:order_detail', args=[o.id]),
        })
    for r in Return.objects.order_by('-updated_at')[:4]:
        events.append({
            'kind': 'return',
            'id': r.id,
            'label': f'مرتجع #{r.id} — {r.get_status_display()}',
            'when': r.updated_at.isoformat(),
            'url': reverse('manage:return_detail', args=[r.id]),
        })
    for s in Shipment.objects.order_by('-updated_at')[:4]:
        events.append({
            'kind': 'shipment',
            'id': s.id,
            'label': f'شحنة الطلب #{s.order_id} — {s.get_status_display()}',
            'when': s.updated_at.isoformat(),
            'url': reverse('manage:shipment_detail_manage', args=[s.id]),
        })
    if request.user.is_superuser:
        for u in User.objects.filter(is_staff=False, is_superuser=False).order_by('-date_joined')[:4]:
            events.append({
                'kind': 'user',
                'id': u.id,
                'label': f'مستخدم جديد: {u.username}',
                'when': u.date_joined.isoformat(),
                'url': reverse('manage:user_detail', args=[u.id]),
            })
    for c in ContactMessage.objects.order_by('-created_at')[:4]:
        events.append({
            'kind': 'contact',
            'id': c.id,
            'label': f'رسالة اتصال: {c.subject}',
            'when': c.created_at.isoformat(),
            'url': reverse('manage:contact_messages_list'),
        })
    support_events_qs = SupportThread.objects.filter(
        status=SupportThread.STATUS_WAITING,
        is_archived=False,
    ).filter(support_staff_visible_q()).select_related('customer_user')
    if not request.user.is_superuser:
        # لموظف خدمة العملاء: نعرض الطابور العام فقط
        support_events_qs = support_events_qs.filter(assigned_staff__isnull=True)
    for t in support_events_qs.order_by('-updated_at')[:4]:
        customer_label = t.customer_user.username if t.customer_user_id else (t.guest_phone or 'عميل')
        events.append({
            'kind': 'support',
            'id': t.id,
            'label': f'طلب دردشة جديد: {customer_label}',
            'when': (t.updated_at or t.created_at).isoformat(),
            'url': reverse('manage:support_thread_detail', args=[t.id]),
        })
    events.sort(key=lambda e: e['when'], reverse=True)
    events = events[:10]

    poll_ms = int(getattr(settings, 'MANAGE_NOTIFICATIONS_POLL_MS', 18000))
    # خدمة العملاء تحتاج تحديث أسرع لظهور الطلبات الجديدة بسرعة
    if support_waiting > 0:
        poll_ms = min(poll_ms, 5000)

    return {
        'ok': True,
        'counts': {
            'orders': orders_nav_badge,
            'users_new': users_new,
            'returns': returns_badge,
            'warehouse': warehouse_badge,
            'shipments': shipments_active,
            'contact': contact_unread,
            'support': support_waiting,
        },
        'dashboard': dashboard,
        'order_stats': order_stats,
        'returns_stats': returns_stats,
        'recent_orders': recent_orders,
        'recent_events': events,
        'ui': {
            'poll_ms': max(5000, poll_ms),
        },
    }


@_staff_required
def manage_notifications_json(request):
    """GET /manage/api/notifications/ — عدّادات التنبيهات + بيانات للتحديث التلقائي."""
    if request.method != 'GET':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)
    return JsonResponse(_build_manage_notifications_payload(request))


@_staff_required
@require_POST
def manage_mark_seen_json(request):
    """POST /manage/api/mark-seen/ — تسجيل اطلاع المسؤول على صف (إزالة العلامة الحمراء)."""
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'bad_json'}, status=400)
    key = (data.get('key') or '').strip()
    if not key or ':' not in key:
        return JsonResponse({'ok': False, 'error': 'bad_key'}, status=400)
    mark_seen_key(request.user, key)
    return JsonResponse({'ok': True})


@_staff_required
@require_POST
def manage_mark_seen_bulk_json(request):
    """POST /manage/api/mark-seen-bulk/ — تعليم عدة صفوف كـ مُشاهدة."""
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'bad_json'}, status=400)

    keys = data.get('keys') or []
    if not isinstance(keys, list):
        return JsonResponse({'ok': False, 'error': 'bad_keys'}, status=400)

    cleaned = []
    for k in keys[:500]:
        if isinstance(k, str) and ':' in k:
            cleaned.append(k.strip()[:120])

    for k in cleaned:
        mark_seen_key(request.user, k)

    return JsonResponse({'ok': True, 'marked': len(cleaned)})


