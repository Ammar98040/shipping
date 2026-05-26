# Generated manually for security plan

from django.db import migrations, models
from django.utils import timezone


def set_existing_verified(apps, schema_editor):
    UserProfile = apps.get_model('store', 'UserProfile')
    now = timezone.now()
    UserProfile.objects.filter(user__is_active=True).update(email_verified_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0017_passwordresetotp'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='email_verified_at',
            field=models.DateTimeField(
                blank=True,
                help_text='يُعبأ بعد إتمام التحقق (مثلاً OTP التسجيل).',
                null=True,
                verbose_name='تاريخ التحقق من البريد',
            ),
        ),
        migrations.RunPython(set_existing_verified, migrations.RunPython.noop),
    ]
