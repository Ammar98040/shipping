"""مُزخرفات لوحة الإدارة (صلاحيات الموظف والمدير الرئيسي)."""
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from .models import UserProfile


def _staff_required(view_func):
    """يتطلب أن يكون المستخدم مسجلاً و is_staff."""
    def wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('manage:login')
        if not request.user.is_staff:
            messages.error(request, _('غير مصرح لك بالدخول.'))
            return redirect('manage:login')
        try:
            account_type = getattr(request.user.profile, 'account_type', '') or ''
        except Exception:
            account_type = ''
        if account_type in (
            UserProfile.ACCOUNT_CUSTOMER_SERVICE,
            UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER,
        ) and not request.user.is_superuser:
            if not (
                request.path.startswith('/manage/support')
                or request.path.startswith('/manage/orders/')
            ):
                messages.error(request, _('لا يحق لك الوصول لصفحة غير بوابة خدمة العملاء.'))
                return redirect('manage:support_portal')
        return view_func(request, *args, **kwargs)
    return wrap


def _superuser_required(view_func):
    """يتطلب أن يكون المستخدم مديراً رئيسياً (is_superuser)."""
    def wrap(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('manage:login')
        if not request.user.is_superuser:
            messages.error(request, _('هذه الصفحة متاحة للمدير الرئيسي فقط.'))
            return redirect('manage:dashboard')
        return view_func(request, *args, **kwargs)
    return wrap
