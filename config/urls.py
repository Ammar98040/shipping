"""
URL configuration for SHOP.
المتجر (واجهة العملاء) + لوحة الإدارة (نظامك فقط — لا تستخدم إدارة Django الافتراضية).
"""
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path(
        'favicon.ico',
        RedirectView.as_view(
            url=f'{settings.STATIC_URL.rstrip("/")}/favicon.svg',
            permanent=False,
        ),
    ),
    path('', include('store.urls')),
    path('shipping/', include('store.urls_shipping')),
    path('warehouse/', include('store.urls_warehouse')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


handler400 = 'store.views_errors.handler400'
handler403 = 'store.views_errors.handler403'
handler404 = 'store.views_errors.handler404'
handler500 = 'store.views_errors.handler500'
