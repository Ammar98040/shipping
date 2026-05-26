import sys

from django.apps import apps
from django.db import connection
from django.db.models.signals import post_migrate
from django.db.utils import OperationalError, ProgrammingError
from django.dispatch import receiver

from .system_accounts import ensure_system_primary_admin


@receiver(post_migrate)
def ensure_primary_admin_after_migrate(sender, **kwargs):
    if sender.name != 'store':
        return
    try:
        ensure_system_primary_admin()
    except Exception:
        pass


def bootstrap_system_primary_admin_on_startup() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {
        'migrate',
        'makemigrations',
        'test',
        'shell',
        'collectstatic',
    }:
        return
    if not apps.ready:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except (OperationalError, ProgrammingError):
        return
    try:
        ensure_system_primary_admin()
    except Exception:
        pass
