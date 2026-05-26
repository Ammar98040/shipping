"""
واجهة صفحة الترحيب.
"""
from django.db.models import Sum
from django.shortcuts import render

from .models import Category, Compartment, Product


def welcome_page(request):
    hero_images = []
    active_products = (
        Product.objects.filter(is_active=True)
        .prefetch_related('gallery_images')
        .only('id', 'image')
        .order_by('?')[:24]
    )
    for product in active_products:
        gallery = product.primary_gallery_image
        if gallery and getattr(gallery, 'image', None):
            hero_images.append(gallery.image.url)
        elif product.image:
            hero_images.append(product.image.url)

    # إزالة التكرارات مع الحفاظ على نفس ترتيب الاختيار العشوائي.
    hero_images = list(dict.fromkeys(hero_images))

    total_stock = Product.objects.filter(is_active=True).aggregate(
        total=Sum('stock')
    )['total'] or 0

    context = {
        'store_name': 'دولابك',
        'hero_images': hero_images,
        'store_stats': {
            'total_compartments': Compartment.objects.filter(is_active=True).count(),
            'total_categories': Category.objects.filter(is_active=True).count(),
            'total_products': Product.objects.filter(is_active=True).count(),
            'total_stock': total_stock,
        },
    }
    return render(request, 'store/welcome.html', context)
