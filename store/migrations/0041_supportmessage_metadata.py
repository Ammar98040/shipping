# Generated manually for support chatbot quick-replies metadata

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0040_supportmessage_images'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportmessage',
            name='metadata',
            field=models.JSONField(blank=True, default=dict, verbose_name='بيانات إضافية'),
        ),
    ]
