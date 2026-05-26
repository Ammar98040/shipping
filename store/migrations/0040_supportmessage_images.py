from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0039_rename_store_inter_thread__ce8ed7_idx_store_inter_thread__25643d_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportmessage',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='support_chat/', verbose_name='صورة مرفقة'),
        ),
        migrations.AlterField(
            model_name='supportmessage',
            name='text',
            field=models.TextField(blank=True, verbose_name='النص'),
        ),
    ]
