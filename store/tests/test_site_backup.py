"""اختبارات تصدير/استيراد النسخة الاحتياطية ZIP."""

import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from store.models import Category, Compartment, Product, Shelf
from store.services import site_backup as svc


@override_settings(
    USE_SQLITE=True,
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    },
    BACKUP_PROTECTED_USERNAMES=['prot_backup_admin'],
    BACKUP_PROTECTED_BOOTSTRAP_PASSWORD='BootstrapPw999!',
)
class SiteBackupRoundTripTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        os.environ.setdefault('PRIMARY_ADMIN_USERNAME', 'signal_admin_detach')

    def test_roundtrip_keeps_protected_password_and_catalog(self):
        media_dir = tempfile.mkdtemp()
        prev_media = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = media_dir
        zip_path = None
        try:
            comp = Compartment.objects.create(name_ar='خانة', name_en='c')
            shelf = Shelf.objects.create(compartment=comp, name_ar='رف', name_en='s')
            cat = Category.objects.create(shelf=shelf, name_ar='صنف', name_en='cat')
            Product.objects.create(
                category=cat,
                name_ar='قميص',
                name_en='shirt',
                price='49.99',
                sku='BK-RND-1',
                slug='bk-rnd-1',
            )

            User.objects.create_superuser(
                username='prot_backup_admin',
                email='p@test.local',
                password='ProtStablePw999!',
            )
            User.objects.create_user(
                username='bob_backup',
                email='b@test.local',
                password='BobPw999!',
                is_staff=True,
            )

            pwd_stable = User.objects.get(username='prot_backup_admin').password
            self.assertEqual(Product.objects.count(), 1)

            fd, zip_path = tempfile.mkstemp(suffix='.zip')
            os.close(fd)
            with open(zip_path, 'wb') as fh:
                svc.write_site_backup_zip(fh)

            svc.restore_site_backup_from_upload_path(
                Path(zip_path),
                protected_usernames=['prot_backup_admin'],
            )

            self.assertEqual(User.objects.filter(username='prot_backup_admin').count(), 1)
            self.assertEqual(User.objects.get(username='prot_backup_admin').password, pwd_stable)
            self.assertTrue(User.objects.filter(username='bob_backup').exists())
            self.assertEqual(Product.objects.count(), 1)
        finally:
            settings.MEDIA_ROOT = prev_media
            try:
                import shutil

                shutil.rmtree(media_dir, ignore_errors=True)
            except Exception:
                pass
            if zip_path and os.path.isfile(zip_path):
                try:
                    os.unlink(zip_path)
                except OSError:
                    pass


class SiteBackupMysqlGateTests(SimpleTestCase):
    """التأكد من بوابة السماح بالاستيراد حسب نوع القاعدة."""

    def test_mysql_blocked_when_flag_off(self):
        with self.settings(
            DATABASES={'default': {'ENGINE': 'django.db.backends.mysql'}},
            BACKUP_WEB_RESTORE_ALLOW_MYSQL=False,
        ):
            self.assertFalse(svc.mysql_restore_allowed())

    def test_mysql_allowed_when_flag_on(self):
        with self.settings(
            DATABASES={'default': {'ENGINE': 'django.db.backends.mysql'}},
            BACKUP_WEB_RESTORE_ALLOW_MYSQL=True,
        ):
            self.assertTrue(svc.mysql_restore_allowed())

    def test_sqlite_allowed_without_flag(self):
        with self.settings(
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3'}},
            BACKUP_WEB_RESTORE_ALLOW_MYSQL=False,
        ):
            self.assertTrue(svc.mysql_restore_allowed())

    def test_full_wipe_raises_when_secret_missing(self):
        with self.settings(FULL_SITE_WIPE_SECRET=''):
            with self.assertRaises(ValueError):
                svc.full_site_wipe()

    def test_full_wipe_blocked_mysql_when_flag_off(self):
        with self.settings(
            DATABASES={'default': {'ENGINE': 'django.db.backends.mysql'}},
            BACKUP_WEB_RESTORE_ALLOW_MYSQL=False,
            FULL_SITE_WIPE_SECRET='x',
        ):
            with self.assertRaises(PermissionError):
                svc.full_site_wipe()


@override_settings(
    USE_SQLITE=True,
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    },
    SYSTEM_IMMUTABLE_USERNAMES=(),
    FULL_SITE_WIPE_SECRET='wipe-test-secret',
)
class FullSiteWipeTests(TransactionTestCase):
    reset_sequences = True

    def test_full_site_wipe_clears_store_users_and_media(self):
        media_dir = tempfile.mkdtemp()
        prev_media = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = media_dir
        dummy = Path(media_dir) / 'keep_me.txt'
        dummy.write_text('x', encoding='utf-8')
        try:
            comp = Compartment.objects.create(name_ar='خانة', name_en='c')
            shelf = Shelf.objects.create(compartment=comp, name_ar='رف', name_en='s')
            cat = Category.objects.create(shelf=shelf, name_ar='صنف', name_en='cat')
            Product.objects.create(
                category=cat,
                name_ar='قميص',
                name_en='shirt',
                price='49.99',
                sku='WIPE-1',
                slug='wipe-1',
            )
            User.objects.create_superuser(
                username='admin_wipe',
                email='a@test.local',
                password='Pw999!!!',
            )
            self.assertEqual(Product.objects.count(), 1)
            self.assertTrue(User.objects.filter(username='admin_wipe').exists())

            svc.full_site_wipe()

            self.assertEqual(Product.objects.count(), 0)
            self.assertEqual(User.objects.count(), 0)
            self.assertFalse(dummy.exists())
        finally:
            settings.MEDIA_ROOT = prev_media
            import shutil

            shutil.rmtree(media_dir, ignore_errors=True)


@override_settings(
    USE_SQLITE=True,
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    },
    SYSTEM_IMMUTABLE_USERNAMES=('ammar',),
)
class SystemImmutableUserBackupTests(TransactionTestCase):
    reset_sequences = True

    def test_export_and_wipe_keep_system_immutable_user(self):
        media_dir = tempfile.mkdtemp()
        prev_media = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = media_dir
        zip_path = None
        try:
            User.objects.create_superuser(
                username='ammar',
                email='a@test.local',
                password='SystemPw999!',
            )
            User.objects.create_user(
                username='bob_backup',
                email='b@test.local',
                password='BobPw999!',
            )
            pwd_stable = User.objects.get(username='ammar').password

            fd, zip_path = tempfile.mkstemp(suffix='.zip')
            os.close(fd)
            with open(zip_path, 'wb') as fh:
                svc.write_site_backup_zip(fh)

            import zipfile

            with zipfile.ZipFile(zip_path, 'r') as zf:
                payload = json.loads(zf.read('data.json').decode('utf-8'))
            usernames = {
                (row.get('fields') or {}).get('username')
                for row in payload
                if row.get('model') == 'auth.user'
            }
            self.assertNotIn('ammar', usernames)
            self.assertIn('bob_backup', usernames)

            with self.settings(FULL_SITE_WIPE_SECRET='wipe-test-secret'):
                svc.full_site_wipe()

            self.assertEqual(User.objects.filter(username='ammar').count(), 1)
            self.assertEqual(User.objects.get(username='ammar').password, pwd_stable)
            self.assertFalse(User.objects.filter(username='bob_backup').exists())
        finally:
            settings.MEDIA_ROOT = prev_media
            import shutil

            shutil.rmtree(media_dir, ignore_errors=True)
            if zip_path and os.path.isfile(zip_path):
                try:
                    os.unlink(zip_path)
                except OSError:
                    pass
