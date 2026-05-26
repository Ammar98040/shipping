# خريطة رفع الصور والتخزين والعرض

مرجع داخلي للفريق. لا يُعدّل ملف الخطة الأصلي؛ التحديثات هنا عند تغيّر المسارات أو النماذج.

## أين تُخزّن الملفات

- **جذر الوسائط**: `config/settings.py` — `MEDIA_ROOT = BASE_DIR / 'media'` و `MEDIA_URL = '/media/'`.
- **التقديم للمتصفح (تطوير)**: `config/urls.py` — `static(MEDIA_URL, document_root=MEDIA_ROOT)` عند `DEBUG`.
- **المسارات الفرعية**: تُحدد عبر `upload_to` في `store/models.py`؛ الملفات تُحفظ تحت `media/<upload_to>/...` عند أول رفع. Django ينشئ المجلد عند الحفظ؛ لا يلزم إنشاء مجلدات فارغة يدويًا للتشغيل.

## جدول: النموذج → مجلد التخزين → أين يُرفع → أين يُعرض / يُستخدم

| المصدر | الحقل / النموذج | `upload_to` (تحت `media/`) | نقاط الرفع (Views) | الاستخدام / العرض |
|--------|-----------------|----------------------------|--------------------|-------------------|
| الكتالوج | `Compartment.image` | `compartments/` | `store/views_manage.py` (نماذج Compartment) | صفحات المتجر / الإدارة حسب القوالب |
| الكتالوج | `Shelf.image` | `shelves/` | نفس الملف | صفحات المتجر / الإدارة |
| الكتالوج | `Category.image` | `categories/` | نفس الملف | صفحات المتجر / الإدارة |
| الكتالوج | `Product.image` | `products/` | نفس الملف | `store/views.py` (JSON صور)، السلة `store/cart.py`، قوالب المنتجات |
| الكتالوج | `ProductVariantImage.image` | `products/variants/` | `store/views_manage.py` (`variant_image`، رفع AJAX) | صفحة المنتج، الطلبات، إلخ |
| الكتالوج | `ProductGalleryImage.image` | `products/gallery/` | `store/views_manage.py` (`getlist('product_gallery_images')`) | معرض المنتج، السلة، الطلبات |
| الملف الشخصي | `UserProfile.avatar` | `avatars/` | `store/views.py` (`profile_edit`)، `store/views_manage.py` (`user_profile_edit`)، `store/views_shipping.py` / `store/views_warehouse.py` (بوابات الشحن/المستودع مع `UserProfileForm`) | قوالب الملف الشخصي في المتجر والإدارة والبوابات |
| خدمة العملاء | `SupportMessage.image` | `support_chat/` | `store/views.py` (`support_send` — `getlist('image')`)، `store/views_manage.py` (`support_thread_send_json`) | `store/templates/store/support_chat.html` + `static/js/support_chat.js`؛ `templates/manage/support_thread_detail.html` + `static/js/manage-support.js`؛ JSON يتضمن `image_url` |
| دردشة داخلية | `InternalSupportMessage.image` | `internal_support/` | `store/views_shipping.py`، `store/views_warehouse.py` (`getlist('image')`) | `templates/shipping/internal_chat.html`، `templates/warehouse/internal_chat.html` |

## أشكال الرفع في الواجهة (نماذج HTML)

- إدارة الكتالوج: `templates/manage/compartment_form.html`، `shelf_form.html`، `category_form.html`، `product_form.html`، `product_variants_manage.html` — `enctype="multipart/form-data"` حيث يلزم.
- الملف الشخصي: `store/templates/store/profile_edit.html`، `templates/manage/user_profile_edit.html`، `templates/shipping/profile.html`، `templates/warehouse/profile.html`.
- الدردشة: `store/templates/store/support_chat.html`، `templates/manage/support_thread_detail.html`، `templates/shipping/internal_chat.html`، `templates/warehouse/internal_chat.html`.

## ملاحظات

- **إنتاج**: يُخدم `/media/` عادةً عبر خادم الويب أو التخزين السحابي؛ `static(..., MEDIA)` في `urls.py` للتطوير فقط. مثال Nginx: [`DEPLOYMENT_NGINX.md`](DEPLOYMENT_NGINX.md).
- **تحسينات اختيارية لاحقًا**: حد أقصى لحجم/عدد الصور، أنواع MIME، تنظيف الملفات عند حذف الرسالة، توحيد أسماء الحقول في الواجهة إن لزم.
