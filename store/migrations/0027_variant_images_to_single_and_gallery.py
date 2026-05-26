from django.db import migrations


def forward(apps, schema_editor):
    ProductVariantImage = apps.get_model('store', 'ProductVariantImage')
    ProductGalleryImage = apps.get_model('store', 'ProductGalleryImage')

    variant_ids = ProductVariantImage.objects.values_list('variant_id', flat=True).distinct()
    for variant_id in variant_ids:
        images = list(
            ProductVariantImage.objects.filter(variant_id=variant_id).order_by('sort_order', 'id')
        )
        if not images:
            continue
        keep = images[0]
        if not keep.is_primary:
            keep.is_primary = True
            keep.sort_order = 1
            keep.save(update_fields=['is_primary', 'sort_order'])
        for idx, img in enumerate(images[1:], start=1):
            ProductGalleryImage.objects.create(
                product_id=img.variant.product_id,
                image=img.image,
                alt_text=img.alt_text or '',
                sort_order=1000 + idx,
                is_primary=False,
            )
            img.delete()


def reverse(apps, schema_editor):
    # لا يمكن عكس النقل بدقة بعد الدمج في معرض المنتج.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0026_productgalleryimage'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]

