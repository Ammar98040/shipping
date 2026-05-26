"""
نسخ احتياطي ZIP كامل (بيانات + مجلد media) واستعادة خطرة للسوبر يوزر فقط عبر الواجهة.

تحذير: الاستيراد يمسح بيانات المتجر وبيانات المستخدمين غير المحميين من قاعدة البيانات.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterable

import django
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core import serializers
from django.core.management import call_command
from django.db import connection, transaction
from django.db.models import ForeignKey, OneToOneField
from django.utils import timezone

MANIFEST_NAME = 'manifest.json'
DATA_NAME = 'data.json'
MEDIA_ZIP_PREFIX = 'media/'


def db_engine_short() -> str:
    return settings.DATABASES['default'].get('ENGINE', '').split('.')[-1]


def mysql_restore_allowed() -> bool:
    eng = settings.DATABASES['default'].get('ENGINE', '')
    if 'sqlite' in eng:
        return True
    if 'mysql' in eng:
        return bool(getattr(settings, 'BACKUP_WEB_RESTORE_ALLOW_MYSQL', False))
    # PostgreSQL أو غيره: خطر تعطيل القيود؛ افتراضياً كـ MySQL
    return bool(getattr(settings, 'BACKUP_WEB_RESTORE_ALLOW_MYSQL', False))


def backup_protected_usernames(extra: Iterable[str] | None = None) -> list[str]:
    """دمج الحسابات المحمية في الشيفرة مع أي أسماء إضافية من البيئة."""
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in list(getattr(settings, 'SYSTEM_IMMUTABLE_USERNAMES', ())) + list(
        getattr(settings, 'BACKUP_PROTECTED_USERNAMES', []) or []
    ):
        uname = str(raw).strip()
        if not uname:
            continue
        key = uname.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(uname)
    if extra:
        for raw in extra:
            uname = str(raw).strip()
            if not uname:
                continue
            key = uname.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(uname)
    return ordered


def _protected_username_ci_set(protected_usernames: Iterable[str]) -> set[str]:
    return {str(u).strip().lower() for u in protected_usernames if str(u).strip()}


def _protected_user_ids(protected_usernames: Iterable[str]) -> set[int]:
    names = [str(u).strip() for u in protected_usernames if str(u).strip()]
    if not names:
        return set()
    return set(User.objects.filter(username__in=names).values_list('pk', flat=True))


def _filter_backup_dump(raw_json: str, protected_usernames: Iterable[str]) -> str:
    """يستبعد حسابات النظام المحمية من ملف data.json."""
    protected_ci = _protected_username_ci_set(protected_usernames)
    protected_ids = _protected_user_ids(protected_usernames)
    rows = json.loads(raw_json)
    kept = []
    for row in rows:
        model = row.get('model') or ''
        fields = row.get('fields') or {}
        if model == 'auth.user':
            if (fields.get('username') or '').strip().lower() in protected_ci:
                continue
        if model == 'store.userprofile':
            user_ref = fields.get('user')
            if isinstance(user_ref, int) and user_ref in protected_ids:
                continue
        kept.append(row)
    return json.dumps(kept, indent=2, ensure_ascii=False)


def _restore_should_skip_instance(instance, protected_ci: set[str]) -> bool:
    if isinstance(instance, User):
        return (getattr(instance, 'username', '') or '').strip().lower() in protected_ci
    profile_model = apps.get_model('store', 'UserProfile')
    if isinstance(instance, profile_model):
        user_ref = getattr(instance, 'user_id', None)
        if user_ref:
            uname = User.objects.filter(pk=user_ref).values_list('username', flat=True).first()
            return bool(uname and uname.strip().lower() in protected_ci)
    return False


def ensure_protected_users_exist(protected_usernames: Iterable[str]) -> None:
    """يُنشئ المستخدمين المحميين إذا كانوا مفقودين (كلمة المرور من البيئة فقط)."""
    pw = getattr(settings, 'BACKUP_PROTECTED_BOOTSTRAP_PASSWORD', '') or ''
    for raw in protected_usernames:
        uname = (raw or '').strip()
        if not uname:
            continue
        if User.objects.filter(username=uname).exists():
            continue
        if not pw:
            raise ValueError(f'backup_missing_protected:{uname}')
        User.objects.create_superuser(
            username=uname,
            email=f'{uname}@backup.bootstrap.local',
            password=pw,
        )


def _store_models_dependency_graph():
    store_models = [
        m for m in apps.get_app_config('store').get_models()
        if not m._meta.proxy
    ]
    dependents = {m: [] for m in store_models}
    for m in store_models:
        for f in m._meta.fields:
            if isinstance(f, (ForeignKey, OneToOneField)):
                tgt = f.remote_field.model
                if tgt in store_models:
                    dependents[tgt].append(m)
    return store_models, dependents


def purge_store_models() -> None:
    """حذف كل صفوف نماذج التطبيق store بالترتيب الصحيح (من الفروع إلى الجذور)."""
    _, dependents = _store_models_dependency_graph()
    remaining = set(dependents.keys())
    iterations = len(remaining) + 10
    while remaining and iterations > 0:
        iterations -= 1
        leaves = [m for m in remaining if not any(d in remaining for d in dependents[m])]
        if not leaves:
            raise RuntimeError('backup_store_cycle')
        for m in leaves:
            m.objects.all().delete()
            remaining.remove(m)
    if remaining:
        raise RuntimeError('backup_store_incomplete')


def purge_groups_and_nonprotected_users(protected_usernames: Iterable[str]) -> None:
    protected = {str(u).strip() for u in protected_usernames if str(u).strip()}
    Group.objects.all().delete()
    User.objects.exclude(username__in=protected).delete()


def full_site_wipe_secret_configured() -> bool:
    return bool((getattr(settings, 'FULL_SITE_WIPE_SECRET', '') or '').strip())


def clear_media_root() -> None:
    """يمسح محتويات MEDIA_ROOT فقط (لا يحذف مجلد الجذر نفسه)."""
    root = Path(settings.MEDIA_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            elif child.is_file():
                child.unlink(missing_ok=True)
        except OSError:
            pass


def full_site_wipe() -> None:
    """
    مسح كامل لبيانات المتجر وجميع الحسابات والجلسات وسجل لوحة الإدارة والوسائط المحلية.
    لا يُمسّ django_migrations. يجب ضبط FULL_SITE_WIPE_SECRET في الإعدادات لتفعيل المسار من الواجهة.
    """
    if not full_site_wipe_secret_configured():
        raise ValueError('full_wipe_disabled')
    if not mysql_restore_allowed():
        raise PermissionError('mysql_full_wipe_disabled')

    from django.contrib.admin.models import LogEntry
    from django.contrib.sessions.models import Session

    protected = backup_protected_usernames()

    with transaction.atomic():
        with connection.constraint_checks_disabled():
            purge_store_models()
            LogEntry.objects.all().delete()
            Session.objects.all().delete()
            Group.objects.all().delete()
            purge_groups_and_nonprotected_users(protected)

    clear_media_root()


def write_site_backup_zip(dest: BinaryIO | str | Path) -> dict:
    """
    يكتب ملف ZIP يحتوي manifest.json و data.json ونسخ مجلد MEDIA_ROOT تحت media/.
    يُرجع manifest كقاموس.
    """
    buf = io.StringIO()
    call_command(
        'dumpdata',
        'store',
        'auth.user',
        'auth.group',
        stdout=buf,
        indent=2,
        natural_foreign=True,
        natural_primary=True,
        exclude=['sessions.session', 'admin.logentry'],
    )
    raw_json = buf.getvalue()
    protected = backup_protected_usernames()
    raw_json = _filter_backup_dump(raw_json, protected)
    digest = hashlib.sha256(raw_json.encode('utf-8')).hexdigest()
    manifest = {
        'schema_version': getattr(settings, 'BACKUP_SCHEMA_VERSION', 1),
        'django_version': django.get_version(),
        'exported_at': timezone.now().isoformat(),
        'db_engine': db_engine_short(),
        'includes_media': True,
        'data_sha256': digest,
        'dump_labels': ['store', 'auth.user', 'auth.group'],
        'excludes': ['sessions.session', 'admin.logentry'],
    }

    media_root = Path(settings.MEDIA_ROOT).resolve()

    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr(DATA_NAME, raw_json.encode('utf-8'))
        if media_root.exists():
            for path in media_root.rglob('*'):
                if path.is_file():
                    try:
                        rel = path.relative_to(media_root)
                    except ValueError:
                        continue
                    arcname = MEDIA_ZIP_PREFIX + str(rel).replace('\\', '/')
                    zf.write(path, arcname)
    return manifest


def validate_archive_structure(extract_root: Path) -> dict:
    manifest_path = extract_root / MANIFEST_NAME
    data_path = extract_root / DATA_NAME
    if not manifest_path.is_file():
        raise ValueError('manifest_missing')
    if not data_path.is_file():
        raise ValueError('data_missing')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    actual_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
    expected = manifest.get('data_sha256')
    if expected and expected != actual_hash:
        raise ValueError('data_integrity_mismatch')
    return manifest


def merge_media_from_extract(extract_root: Path) -> None:
    src = extract_root / 'media'
    if not src.is_dir():
        return
    dest = Path(settings.MEDIA_ROOT).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for path in src.rglob('*'):
        if path.is_file():
            rel = path.relative_to(src)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def save_auto_backup_zip() -> Path:
    """نسخة أمان قبل الاستيراد؛ يُرجع مسار الملف."""
    raw_dir = getattr(settings, 'BACKUP_AUTO_SAVE_DIR', '') or ''
    base = Path(raw_dir).resolve() if raw_dir.strip() else Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = base / f'shop_autobackup_pre_restore_{ts}.zip'
    with open(path, 'wb') as fh:
        write_site_backup_zip(fh)
    return path


def restore_site_backup_from_upload_path(zip_path: Path, *, protected_usernames: list[str]) -> None:
    """
    استعادة كاملة من ملف ZIP على القرص (مسار مؤقت بعد الرفع).
    """
    if not mysql_restore_allowed():
        raise PermissionError('mysql_restore_disabled')

    prot_set = [str(u).strip() for u in protected_usernames if str(u).strip()]
    ensure_protected_users_exist(prot_set)

    protected_ci = {u.lower() for u in prot_set}

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        with zipfile.ZipFile(zip_path, 'r') as zin:
            zin.extractall(td_path)

        validate_archive_structure(td_path)
        raw = (td_path / DATA_NAME).read_text(encoding='utf-8')

        with transaction.atomic():
            with connection.constraint_checks_disabled():
                purge_store_models()
                purge_groups_and_nonprotected_users(prot_set)

                for obj in serializers.deserialize('json', raw):
                    instance = obj.object
                    if _restore_should_skip_instance(instance, protected_ci):
                        continue
                    obj.save()

        merge_media_from_extract(td_path)


def restore_site_backup_from_uploaded_file(uploaded_file, *, protected_usernames: list[str]) -> None:
    suffix = '.zip'
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        for chunk in uploaded_file.chunks():
            tmp.write(chunk)
        tmp.flush()
        tmp.close()
        restore_site_backup_from_upload_path(Path(tmp.name), protected_usernames=protected_usernames)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
