# نشر الإنتاج: Nginx وملفات ثابتة ووسائط

## وسائط المستخدم (`/media/`)

في التطوير (`DEBUG=True`) يخدم Django المسار عبر [`config/urls.py`](../config/urls.py). في **الإنتاج** (`DEBUG=False`) يجب أن يخدم **Nginx** (أو خادم ويب آخر) الملفات من `MEDIA_ROOT` (مثل `.../media/` على القرص).

مثال موقع (تعديل المسارات والنطاق):

```nginx
location /media/ {
    alias /var/www/shop/media/;
    expires 7d;
    add_header Cache-Control "public, max-age=604800";
}

location /static/ {
    alias /var/www/shop/staticfiles/;
    expires 30d;
}
```

بعد النشر نفّذ `python manage.py collectstatic` لملء `STATIC_ROOT`.

مرجع مسارات الرفع في التطبيق: [`MEDIA_UPLOAD_MAP.md`](MEDIA_UPLOAD_MAP.md).

## كاش Redis (اختياري)

عند تشغيل عدة عمليات Gunicorn، عيّن `REDIS_URL` في البيئة (مثل `redis://127.0.0.1:6379/1`) ليستخدم Django `RedisCache` كما في [`config/settings.py`](../config/settings.py). يحتاج الحزمة `redis` (انظر `requirements.txt`).

## أسرار Webhooks الوهمية

في الإنتاج يجب أن تكون `FAKE_GATEWAY_WEBHOOK_SECRET` و `FAKE_SHIPPING_WEBHOOK_SECRET` قيمًا عشوائية قوية — الإعدادات ترفض القيم الافتراضية للتطوير عند `DEBUG=False`. المسارات محمية بتحقق **سر** في جسم الطلب؛ ليس CSRF من المتصفح.
