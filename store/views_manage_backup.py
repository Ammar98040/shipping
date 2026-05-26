"""نسخ احتياطي واستعادة ZIP — سوبر يوزر فقط (عمليات خطرة)."""

import logging
import secrets
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .manage_decorators import _superuser_required
from .services import site_backup as backup_svc

logger = logging.getLogger(__name__)


def _upload_size(upload):
    if upload is None:
        return 0
    sz = getattr(upload, 'size', None)
    if isinstance(sz, int) and sz >= 0:
        return sz
    upload.seek(0, 2)
    n = upload.tell()
    upload.seek(0)
    return int(n)


def _web_restore_blocked() -> bool:
    engine = settings.DATABASES['default'].get('ENGINE', '')
    return ('sqlite' not in engine) and not getattr(
        settings, 'BACKUP_WEB_RESTORE_ALLOW_MYSQL', False
    )


@csrf_protect
@require_http_methods(['GET', 'POST'])
@_superuser_required
def site_backup(request):
    web_restore_blocked = _web_restore_blocked()

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'export':
            bio = BytesIO()
            backup_svc.write_site_backup_zip(bio)
            bio.seek(0)
            fname = f'shop_backup_{timezone.now().strftime("%Y%m%d_%H%M%S")}.zip'
            resp = HttpResponse(bio.read(), content_type='application/zip')
            resp['Content-Disposition'] = f'attachment; filename="{fname}"'
            resp['Cache-Control'] = 'no-store'
            return resp

        if action == 'import':
            if web_restore_blocked:
                messages.error(
                    request,
                    'استيراد الويب الكامل غير مفعّل على هذه القاعدة. استخدم SQLite أو عيّن '
                    'BACKUP_WEB_RESTORE_ALLOW_MYSQL=true بعد تقييم المخاطر.',
                )
                return redirect('manage:site_backup')

            upload = request.FILES.get('backup_zip')
            if not upload:
                messages.error(request, 'لم يُرفع ملف ZIP.')
                return redirect('manage:site_backup')

            max_b = getattr(settings, 'BACKUP_IMPORT_MAX_BYTES', 2048 * 1024 * 1024)
            if _upload_size(upload) > max_b:
                messages.error(request, 'حجم الملف يتجاوز الحد المسموح.')
                return redirect('manage:site_backup')

            try:
                autopath = backup_svc.save_auto_backup_zip()
                messages.info(request, f'تم حفظ نسخة أمان على الخادم: {autopath}')
            except Exception as exc:
                messages.warning(request, f'تعذّر حفظ نسخة أمان تلقائية: {exc}')

            try:
                backup_svc.restore_site_backup_from_uploaded_file(
                    upload,
                    protected_usernames=backup_svc.backup_protected_usernames(),
                )
                messages.success(request, 'اكتمل الاستيراد. راجع البيانات وسجّل الدخول للموظفين إن لزم.')
            except PermissionError:
                messages.error(request, 'تم رفض الاستيراد (نوع القاعدة أو الإعدادات).')
            except ValueError as ve:
                messages.error(request, f'ملف النسخة غير صالح: {ve}')
            except Exception as exc:
                messages.error(request, f'فشل الاستيراد: {exc}')
            return redirect('manage:site_backup')

    ctx = {
        'web_restore_blocked': web_restore_blocked,
        'protected_hint': ', '.join(backup_svc.backup_protected_usernames()) or '(لا يوجد — سيُستورد كل المستخدمين)',
        'max_upload_mb': getattr(settings, 'BACKUP_IMPORT_MAX_MB', 2048),
    }
    return render(request, 'manage/site_backup.html', ctx)


@csrf_protect
@require_http_methods(['GET', 'POST'])
@_superuser_required
def site_full_wipe(request):
    web_restore_blocked = _web_restore_blocked()
    wipe_secret_configured = bool(getattr(settings, 'FULL_SITE_WIPE_SECRET', '').strip())

    if request.method == 'POST':
        if not wipe_secret_configured:
            messages.error(
                request,
                'حذف النظام بالكامل غير مفعّل. عيّن FULL_SITE_WIPE_SECRET في ملف البيئة على الخادم.',
            )
            return redirect('manage:site_full_wipe')
        if web_restore_blocked:
            messages.error(
                request,
                'حذف النظام من الويب غير مفعّل على هذا النوع من القاعدة. استخدم SQLite أو '
                'فعّل BACKUP_WEB_RESTORE_ALLOW_MYSQL بعد تقييم المخاطر.',
            )
            return redirect('manage:site_full_wipe')

        wipe_pw = request.POST.get('wipe_secret') or ''

        cfg_secret = settings.FULL_SITE_WIPE_SECRET.encode('utf-8')
        if not secrets.compare_digest(wipe_pw.encode('utf-8'), cfg_secret):
            messages.error(request, 'كلمة سر الحذف الكامل غير صحيحة.')
            return redirect('manage:site_full_wipe')

        try:
            backup_svc.save_auto_backup_zip()
        except Exception:
            logger.warning('full_wipe_auto_backup_failed', exc_info=True)

        try:
            backup_svc.full_site_wipe()
        except PermissionError:
            messages.error(request, 'تم رفض الحذف الكامل (نوع القاعدة أو الإعدادات).')
            return redirect('manage:site_full_wipe')
        except ValueError as ve:
            messages.error(request, f'الحذف الكامل غير مسموح: {ve}')
            return redirect('manage:site_full_wipe')
        except Exception as exc:
            messages.error(request, f'فشل الحذف الكامل: {exc}')
            return redirect('manage:site_full_wipe')

        logout(request)
        return redirect(f'{reverse("manage:login")}?system_wiped=1')

    ctx = {
        'web_restore_blocked': web_restore_blocked,
        'wipe_secret_configured': wipe_secret_configured,
    }
    return render(request, 'manage/site_wipe.html', ctx)
