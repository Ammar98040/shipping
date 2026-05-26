# Generated manually for support claim / read receipts / audit trail

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('store', '0041_supportmessage_metadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportthread',
            name='claimed_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='وقت استلام المحادثة'),
        ),
        migrations.CreateModel(
            name='SupportCustomerMessageRead',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('read_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت القراءة')),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='customer_reads', to='store.supportmessage', verbose_name='الرسالة')),
                ('reader', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='support_customer_message_reads', to=settings.AUTH_USER_MODEL, verbose_name='القارئ')),
            ],
            options={
                'verbose_name': 'قراءة رسالة عميل',
                'verbose_name_plural': 'قراءات رسائل العملاء',
            },
        ),
        migrations.CreateModel(
            name='SupportThreadAuditEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('thread_claimed', 'استلام المحادثة'), ('customer_messages_marked_read', 'تأكيد قراءة رسائل العميل'), ('thread_ended_staff', 'إنهاء من الموظف')], db_index=True, max_length=60, verbose_name='نوع الحدث')),
                ('payload', models.JSONField(blank=True, default=dict, verbose_name='تفاصيل')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_thread_audit_actions', to=settings.AUTH_USER_MODEL, verbose_name='من قام بالإجراء')),
                ('thread', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audit_events', to='store.supportthread', verbose_name='المحادثة')),
            ],
            options={
                'verbose_name': 'حدث إشراف محادثة',
                'verbose_name_plural': 'أحداث الإشراف على المحادثات',
                'ordering': ['created_at', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='supportcustomermessageread',
            constraint=models.UniqueConstraint(fields=('message', 'reader'), name='uniq_support_customer_msg_read_reader'),
        ),
    ]
