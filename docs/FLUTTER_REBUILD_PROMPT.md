# برومبت إعادة بناء نظام SHOP («دولابك») في Flutter — عربي + English

هذا المستند يصف مشروع Django الحالي كمرجع وظيفي ويوفّر **برومبتًا ثنائي اللغة** يمكن لصقه لنموذج ذكاء اصطناعي ليطلب بناء تطبيق Flutter يعادل السلوك باستخدام **قاعدة بيانات محلية** فقط للمرحلة الأولى.

**مرجع الكود المصدري (Python/Django):** الجذر المشروع، خصوصًا `store/models.py`، `store/urls.py`، `store/urls_manage.py`، `store/urls_shipping.py`، `store/urls_warehouse.py`، `store/manage_decorators.py`.

---

## فهرس

1. [البرومبت بالعربية](#1-البرومبت-بالعربية-للذكاء-الاصطناعي)
2. [English prompt for the AI](#2-english-prompt-for-the-ai)
3. [ملحق: جدول مطابقة مسارات Django ↔ شاشات/عمليات Flutter](#3-ملحق-جدول-مطابقة-مسارات-django--شاشاتعمليات-flutter)

---

## 1) البرومبت بالعربية (للذكاء الاصطناعي)

### أ) تعليمات بناء إلزامية (اقرأ أولاً)

**يجب عليك تنفيذ التالي:**

1. **أنشئ تطبيق Flutter** (مثلاً: `flutter create` + بنية نظيفة: feature folders أو clean architecture خفيفة).
2. **استخدم قاعدة بيانات محلية فقط** للمرحلة الأولى (مثل **SQLite** عبر **Drift** أو `sqflite` / **Floor** / **Isar** — اختر حلاً واحدًا ووثّقه).
3. **أضف طبقة `Repository`** تفصل منطق الوصول للبيانات عن الواجهات؛ صمّمها بحيث يمكن لاحقًا استبدال التنفيذ المحلي بـ API دون تغيير الـ UI.
4. **واجهة عربية RTL** افتراضيًا؛ دعم أسماء/نصوص إنجليزية اختيارية حيث يوجد في النموذج حقول `name_en` / `description_en`.
5. **محاكاة التكاملات الخارجية محليًا:** بوابة دفع وهمية، شركة شحن وهمية، Webhooks وهمية (شاشات أو خدمات داخلية تحدّث الحالة في قاعدة البيانات).
6. **الامتثال لآلات الحالة** الموصوفة أدناه لطلبات التنفيذ، الدفع، الشحن، المرتجعات، ومحادثات الدعم؛ لا تسمح بانتقالات غير مذكورة.
7. **الأدوار والبوابات:** نفّذ أربع تجارب مستخدم منطقية (متجر، إدارة، شحن، مستودع) كـ **تطبيق واحد** مع اختيار بوابة بعد تسجيل الدخول، أو **نكهات/أهداف بناء** متعددة إن رغبت — المهم تغطية السلوك.
8. **مرجع الحقول التفصيلي:** استخرج الحقول والقيود والعلاقات من نموذج Django في المستودع (`store/models.py`). عند التعارض، **المرجع هو الكود**.

---

### ب) السياق والرؤية

- **المنتج:** متجر إلكتروني بتجربة «**دولاب ثلاثي الأبعاد**»: تنقل هرمي **خانة (Compartment) → رف (Shelf) → صنف (Category) → منتج (Product)** مع صفحة كتالوج عامة وبحث.
- **الكتالوج:** منتجات تدعم **نسخًا (ProductVariant)** بمخزون وسعر اختياري، و**صور نسخة**؛ و**معرض صور للمنتج (ProductGalleryImage)** يمكن أن يكون له SKU/سعر/مخزون مستقل (خيارات شراء بالصورة).
- **السلة:** في Django مبنية على **الجلسة**؛ في Flutter خزّن السلة **محليًا** (واختياريًا اربطها بحساب مسجّل).
- **الطلبات:** عميل **مسجل** أو **ضيف**؛ للضيف يوجد **`tracking_token`** سرّي للتتبع مع رقم الجوال.
- **التخفيضات:** **Promotion** بنطاقات (كل الخانات/الرفوف/الأصناف/المنتجات/النسخ/الكل) وخصم نسبة أو مبلغ؛ و**Coupon** على إجمالي الطلب بعد خصومات البنود مع حد استخدام وسجل `CouponRedemption`.
- **الشحن والمستودع:** موظف تجهيز (**packer**) يقبل طلبات ويُنشئ **بوليصة (ShippingWaybill)** وملصق/QR؛ مندوب (**courier**) يمسح أكواد مراحل الاستلام/التسليم ويستخدم **OTP تسليم**؛ **مسؤول مستودع** و**مسؤول شحن** لإسناد المهام.
- **خدمة العملاء:** محادثات **SupportThread** مع إسناد موظف، رسائل نص/صورة، حالات انتظار/نشطة/منتهية، قراءة رسائل العميل قبل الرد (نموذج `SupportCustomerMessageRead`)، أرشفة، تدقيق (`SupportThreadAuditEvent`).
- **دردشة داخلية:** `InternalSupportThread` / `InternalSupportMessage` بين فريق الشحن/المستودع.
- **الإدارة:** لوحة `/manage/` مخصصة (ليست Django Admin الافتراضية) مع صلاحيات **`is_staff`** / **`is_superuser`** وقيد على `customer_service` (انظر القسم «الأدوار»).

---

### ج) المتطلبات غير الوظيفية

- أداء جيد للقوائم الطويلة (pagination مثل المتجر: ~12 منتجًا في الصنف، ~20 في البحث).
- دعم صور المنتجات محليًا (مسارات ملفات أو `byte[]` في DB — للنموذج الأولي).
- شاشات خطأ متناسقة (مكافئة `handler400/403/404/500` اختياريًا كرسائل عامة).
- **بذرة بيانات (seed)** اختيارية: خانات/ منتجات/ مستخدمين تجريبيين لكل دور.

---

### د) كيانات البيانات (ملخص علاقاتي — للمخطط المحلي)

طبّق جدولًا لكل كيان تقريبًا كما يلي (مع مفاتيح أجنبية وفهارس؛ للتفاصيل راجع `store/models.py`):

| كيان | وصف مختصر |
|------|-----------|
| `Compartment` | خانة دولاب: أسماء عربي/إنجليزي، ترتيب، صورة، نشط |
| `Shelf` | تابع لخانة |
| `Category` | تابع لرف |
| `Product` | تابع لصنف؛ SKU فريد (nullable مع توليد منطقي في السيرفر سابقًا — طبّق منطقًا معقولًا محليًا)، slug، أسعار، مخزون قديم، معرض |
| `ProductVariant` | تابع لمنتج؛ `code` فريد لكل منتج؛ سعر اختياري؛ مخزون؛ صور |
| `ProductVariantImage` | صور النسخة |
| `ProductGalleryImage` | صور عامة؛ `code` فريد لكل منتج؛ سعر/مخزون اختياري |
| `InventoryMovement` | حركات مخزون النسخة: inbound, sale, cancel_restore, return_restore, adjustment |
| `Promotion` | نطاق + خصم + جداول ربط M2M حسب النطاق |
| `Coupon` / `CouponRedemption` | كوبون + قيود فريدة لكل مستخدم أو هاتف ضيف |
| `Order` | حالة تنفيذ + حالة دفع منفصلة + طريقة دفع + رسوم توصيل + packer + سبب إلغاء |
| `OrderItem` | منتج/نسخة/صورة معرض مختارة؛ لقطات نصية؛ عرض مرتبط؛ حساب subtotal |
| `OrderStatusHistory` | سجل تغييرات الحالة والدفع |
| `PaymentAttempt` | محاولة دفع وهمية مرتبطة بطلب |
| `Shipment` | 1:1 مع طلب؛ مندوب؛ حالة شحنة؛ مزود وهمي |
| `LabelCode` | كود ملصق / ربط بطلب وشحنة |
| `ShippingWaybill` | بوليصة من المستودع |
| `DeliveryOTP` | OTP تسليم للشحنة |
| `Wishlist` | فريد (user, product) |
| `CartShare` + `CartShareItem` | مشاركة سلة برمز |
| `User` (مبسّط) | username, email, password hash, is_active, is_staff, is_superuser |
| `UserProfile` | phone, account_type, is_available, تواريخ توفر، avatar, birth-date, email_verified_at |
| `Address` | عنوان متعدد؛ افتراضي واحد |
| `Review` | فريد (product, user)؛ تقييم 1–5 |
| `ContactMessage` | اتصل بنا |
| `SupportThread`, `SupportMessage`, `SupportCustomerMessageRead`, `SupportThreadAuditEvent` | دردشة دعم |
| `InternalSupportThread`, `InternalSupportMessage` | دردشة داخلية |
| `Return`, `ReturnItem`, `ReturnStatusHistory` | مرتجعات |
| `EmailOTP`, `PasswordResetOTP` | تحقق تسجيل واستعادة كلمة مرور |
| `ManageSeenMarker` | مقروءة في لوحة الإدارة |

---

### هـ) آلات الحالة (إلزامي — لا تخلّ بهذه الانتقالات)

**1) حالة الطلب (`Order.status`)**

- القيم: `pending`, `confirmed`, `processing`, `ready_to_ship`, `shipped`, `delivered`, `cancelled`.
- الانتقالات المسموحة:

```
pending    → confirmed | cancelled
confirmed  → processing | cancelled
processing → ready_to_ship | cancelled
ready_to_ship → shipped | cancelled
shipped    → delivered | cancelled
delivered  → (لا شيء)
cancelled  → (لا شيء)
```

**2) حالة الدفع (`Order.payment_status`)**

- القيم: `pending`, `paid`, `failed`, `cancelled`, `refunded`, `partially_refunded`.
- مستقلة منطقيًا عن `status`؛ حافظ على الاتساق عند إلغاء الطلب أو الاسترداد.

**3) طرق الدفع**

- `cash_on_delivery` (الدفع عند الاستلام)
- `payment_gateway` (بطاقة — مع `PaymentAttempt` وهمي)

**4) حالة الشحنة (`Shipment.status`)**

- القيم: `created`, `picked_up`, `in_transit`, `out_for_delivery`, `delivered`, `failed`.
- عند تقدّم الطلب إلى `shipped` يمكن ربط تحديث الشحنة للحالات الأولى (كما في `order_engine` في المشروع الحالي).

**5) محاولة الدفع (`PaymentAttempt.status`)**

- `created`, `pending`, `success`, `failed`.

**6) حالة المرتجع (`Return.status`)**

```
requested  → reviewing | rejected
reviewing  → approved | rejected
approved   → received
rejected   → (لا شيء)
received   → completed
completed  → (لا شيء)
```

**7) حالات فرعية للمرتجع**

- `refund_status`: `not_required`, `pending`, `completed`, `partial`
- `stock_status`: `pending`, `restocked`, `damaged`

**8) محادثة الدعم (`SupportThread.status`)**

- `waiting_for_staff`, `active`, `ended`

---

### و) الأدوار (`UserProfile.account_type`) وصلاحيات الوصول

| القيمة | الوصف | البوابة/القيود |
|--------|--------|----------------|
| `regular` | عميل | المتجر فقط |
| `courier` | مندوب شحن | `/shipping/` + توفر + مهام + مسح |
| `packer` | موظف تجهيز | `/warehouse/` + بوليصة + مسح |
| `customer_service` | موظف دعم | في الإدارة: **فقط** مسارات الدعم ومسارات الطلبات تحت `/manage/` (مع `is_staff`) |
| `customer_service_manager` | مسؤول دعم | صلاحيات أوسع للدعم + مزامنة مع منطق `_is_support_admin` في الكود |
| `warehouse_manager` | مسؤول مستودع | لوحة مدير المستودع؛ إسناد الطلبات للمجهزين |
| `shipping_manager` | مسؤول شحن | لوحة مدير الشحن؛ إسناد الشحنات للمندوبين |
| `is_superuser` | مدير نظام | كل شيء بما فيه `system/backup` و `system/wipe` |

**ملاحظة:** في Django، الموظفون يحتاجون `is_staff`. نفّذ تعادلًا في Flutter (حقل بدور المستخدم أو جدول صلاحيات).

---

### ز) وظائف الواجهات — واجهة العملاء (مسارات مرجعية `store/urls.py`)

نفّذ شاشات/تدفقات تعادل:

- **`/`** ترحيب؛ **`/home/`** دولاب/أقسام رئيسية
- **`/compartment/<id>/`**, **`/shelf/<id>/`**, **`/category/<id>/`**, **`/products/`**, **`/product/<id>/`**, **`/p/<slug>/`**
- سلة: عرض، إضافة/تحديث/حذف، **كوبون** `POST cart/coupon`، **مشاركة سلة**: إنشاء، فتح بالرمز، تطبيق على السلة
- **`/checkout/`**، **`/order/success/<id>/`**
- **`/order/track/`** + poll؛ **`/my-orders/`**؛ **`/order/<id>/`** + poll؛ **`/reorder/<id>/`**
- مرتجعات: قائمة، تفاصيل + poll، إنشاء من طلب
- تقييمات: إضافة/حذف، قائمة مراجعاتي
- حساب: تسجيل، **`/verify-otp/`**، دخول، خروج، نسيان كلمة المرور (ثلاث خطوات)
- مفضلة: قائمة، إضافة، إزالة
- ملف شخصي: عرض وتعديل
- عناوين: CRUD + تعيين افتراضي
- **`/search/`**؛ **`/about/`**؛ **`/contact/`**
- دعم: **`/support/`**، محادثة جديدة، poll، send، end

**دفع وهمي:** `pay/fake/<attempt_id>/` وcallback؛ **Webhooks:** `webhooks/fake-gateway/`، `webhooks/fake-shipping/` — في Flutter نفّذ خدماتًا تستدعي نفس منطق تحديث السجلات محليًا.

---

### ح) لوحة الإدارة (مرجع `store/urls_manage.py` تحت `/manage/`)

- دخول/خروج/نسيان كلمة المرور (مثل المتجر)
- لوحة، نظرة شاملة، **إشعارات JSON** + تعليم مقروء (`mark-seen`, `mark-seen-bulk`)
- APIs لتوفر المجهزين والمندوبين (`packers-availability`, `couriers-availability`)
- CRUD: خانات، رفوف، أصناف، منتجات، إدارة نسخ و**تصدير CSV** و**stock JSON**
- عروض ترويجية وتفعيل/تعطيل؛ كوبونات وتفعيل/تعطيل
- طلبات: قائمة، تفاصيل، تعديل، live state، **QR بوليصة**، طباعة ملصق
- شحنات (إداري)، قائمة مندوبين، قائمة مجهزين، **مستودع إداري**
- مرتجعات: قائمة، تفاصيل، live state
- مستخدمون: قائمة، تفاصيل، تعديل ملف، تفعيل/تعطيل، تبديل توفر
- قوائم أدوار: مسؤولو شحن، مسؤولو مستودع، حسابات دعم، مدراء دعم
- **`/manage/admins/`** مسؤولو النظام
- **دعم الإدارة:** بوابة، تفاصيل محادثة، APIs: توقيع، رسائل، إرسال، claim، mark-read، end؛ فريق؛ تفاصيل وكيل؛ تبديل توفر؛ أرشفة محادثة/وكيل
- **`contact-messages/`**
- **`system/backup/`** و **`system/wipe/`** — **superuser فقط**

---

### ط) بوابة الشحن (مرجع `/shipping/`)

- دخول وملف ونسيان كلمة المرور
- **مركز مسح:** pickup / deliver / consume
- **`deliver/otp/`**
- توفر + API حي للتوفر
- مهام متاحة + live + قبول مهمة
- شحناتي: قائمة، تفاصيل، poll
- دردشة داخلية
- **مدير الشحن:** لوحة، مندوبون، شحنات، إسناد شحنة

---

### ي) بوابة المستودع (مرجع `/warehouse/`)

- دخول وملف ونسيان كلمة المرور
- توفر + API حي
- طلبات متاحة + live + قبول
- تفاصيل طلب + poll
- دردشة داخلية
- إنشاء بوليصة، ملصق شحن، QR الملصق
- مسح + consume
- **مدير المستودع:** لوحة، فريق، طلبات، إسناد طلب

---

### ك) معايير قبول (Checklist)

- [ ] التنقل الهرمي للدولاب يعمل بالكامل مع RTL.
- [ ] السلة + الكوبون + العروض على بنود السلة + الكوبون على الإجمالي وفق القواعد.
- [ ] إتمام طلب مسجل وضيف؛ تتبع الضيف بـ token + هاتف.
- [ ] آلة حالات الطلب/الدفع/الشحنة/المرتجع محترمة في كل العمليات.
- [ ] دفع بطاقة وهمي يغيّر `PaymentAttempt` و`payment_status` بشكل متسق.
- [ ] مسار المستودع: قبول طلب → بوليصة → ملصق/QR → مسح.
- [ ] مسار الشحن: قبول شحنة → مسح مراحل → OTP تسليم.
- [ ] الدعم: إسناد، قراءة قبل رد، إنهاء، أرشفة.
- [ ] قيود `customer_service` على شاشات الإدارة مطبقة.
- [ ] نسخ احتياطي/مسح النظام فقط لمدير أعلى.

---

### ل) الأمر الختامي (انسخه في نهاية المحادثة مع النموذج)

```
بناءً على كل الأقسام أعلاه: نفّذ تطبيق Flutter واحد أو أكثر يغطي البوابط الأربع،
باستخدام قاعدة بيانات محلية فقط (SQLite عبر Drift أو ما يعادله)، مع طبقة Repository قابلة لاحقًا للربط بـ API حقيقي.
حافظ على أسماء الحقول والحالات والأدوار ومسارات العمل كما ورد.
وفّر بذرة بيانات اختيارية ووثّق هيكل المشروع وخطوات التشغيل.
```

---

## 2) English prompt for the AI

### A) Mandatory build instructions (read first)

**You MUST:**

1. **Build a Flutter application** (e.g. `flutter create` + a clean structure: feature modules or lightweight clean architecture).
2. Use a **local database only** for v1 (e.g. **SQLite** via **Drift**, `sqflite`, **Floor**, or **Isar** — pick one and document it).
3. Add a **Repository layer** between UI and persistence so the local implementation can later be swapped for a remote API without UI changes.
4. Default **Arabic RTL** UI; optional English copy where the domain model exposes `name_en` / `description_en`.
5. **Simulate external integrations locally:** fake payment gateway, fake carrier, fake webhooks (services or dev screens that mutate local DB state).
6. Respect the explicit **state machines** below for orders, payments, shipments, returns, and support threads—**disallow invalid transitions**.
7. Implement **four portal experiences** (storefront, manage, shipping, warehouse) as **one app** with portal selection after login, or as multiple targets/flavors—behavior coverage matters most.
8. For **field-level truth**, mirror Django’s `store/models.py` from the source repo attached to the task.

---

### B) Product context

- **Storefront:** “3D wardrobe” mental model: **Compartment → Shelf → Category → Product**, plus global catalog and search.
- **Catalog:** `ProductVariant` (per-variant stock/optional price, images) and `ProductGalleryImage` line items (optional SKU/price/stock).
- **Cart:** session-based on web → **local cart state** in Flutter (optionally tied to logged-in user).
- **Orders:** registered or guest; guests get a **`tracking_token`** for tracking with phone.
- **Discounts:** scoped **Promotions** + **Coupons** on order totals with redemption limits.
- **Warehouse & shipping:** packers accept orders and create **ShippingWaybill**/labels; couriers scan pickup/delivery flows and confirm with **DeliveryOTP**; **warehouse/shipping managers** assign work.
- **Support chat** with assignment, image uploads, read receipts for customer messages before staff replies, archiving, audit events; **internal chat** for ops staff.
- **Manage** is a **custom admin** (not Django Admin) with staff/superuser and CS role restrictions.

---

### C) Non-functional requirements

- Pagination consistent with reference (~12 category page size, ~20 search).
- Local image handling for demo (file path or blob).
- Optional **seed** data for all roles.
- Friendly error states.

---

### D) Data entities (relational summary)

Implement tables/constraints roughly matching the Arabic section’s entity list (full detail in `store/models.py`): wardrobe hierarchy, variants & gallery images, inventory movements, promotions & coupons, orders & items & history, payment attempts, shipments & waybills & label codes & delivery OTPs, wishlist, cart share, users & profiles & addresses, reviews, contact messages, support + internal threads/messages, returns, OTP tables, manage seen markers.

---

### E) State machines (mandatory)

**Order.status** — values: `pending`, `confirmed`, `processing`, `ready_to_ship`, `shipped`, `delivered`, `cancelled`.

Allowed transitions:

```
pending    → confirmed | cancelled
confirmed  → processing | cancelled
processing → ready_to_ship | cancelled
ready_to_ship → shipped | cancelled
shipped    → delivered | cancelled
delivered  → (terminal)
cancelled  → (terminal)
```

**Order.payment_status** — `pending`, `paid`, `failed`, `cancelled`, `refunded`, `partially_refunded` (independent from fulfillment; keep cancellations/refunds coherent).

**Payment methods:** `cash_on_delivery`, `payment_gateway`.

**Shipment.status** — `created`, `picked_up`, `in_transit`, `out_for_delivery`, `delivered`, `failed`.

**PaymentAttempt.status** — `created`, `pending`, `success`, `failed`.

**Return.status** —

```
requested  → reviewing | rejected
reviewing  → approved | rejected
approved   → received
rejected   → (terminal)
received   → completed
completed  → (terminal)
```

**Return** also has `refund_status` and `stock_status` as enumerated in `store/models.py`.

**SupportThread.status** — `waiting_for_staff`, `active`, `ended`.

---

### F) Roles (`UserProfile.account_type`)

| Value | Portal / constraint |
|------|---------------------|
| `regular` | Storefront only |
| `courier` | Shipping portal + availability + scans |
| `packer` | Warehouse portal + waybills + scans |
| `customer_service` | Manage **only** support + orders paths (with `is_staff`) |
| `customer_service_manager` | Broader support administration |
| `warehouse_manager` | Warehouse manager assignment UI |
| `shipping_manager` | Shipping manager assignment UI |
| `is_superuser` | Full manage, including `system/backup` & `system/wipe` |

---

### G) Storefront features (map from `store/urls.py`)

Implement screens/flows equivalent to: welcome & home wardrobe; compartment/shelf/category/product/products-all; slug product URL; full cart + coupon + share link lifecycle; checkout & success; track + polls; my orders + detail + reorder; returns CRUD/poll; reviews; auth + OTP verify + password reset flow; wishlist; profile; addresses; search; about; contact; support chat (new, poll, send, end); fake pay + fake webhooks updating local state.

---

### H) Manage portal (`store/urls_manage.py` under `/manage/`)

Login/logout/reset; dashboard; overview; notification JSON + mark seen/bulk; packer/courier availability APIs; full CRUD catalog; variant admin + CSV export + stock JSON; promotions/coupons + toggles; orders (list/detail/edit/live/QR label print); shipments admin; couriers/packers lists; warehouse admin slice; returns admin; users + role lists; admins list; full support portal + JSON endpoints (signature, messages, send, claim, mark-read, end, team, archive); contact messages; **backup/wipe superuser-only**.

---

### I) Shipping portal (`/shipping/` — `store/urls_shipping.py`)

Auth/profile/reset; scan hub + pickup/deliver/consume; deliver OTP; availability + live API; jobs list/live/accept; shipments list/detail/poll; internal chat; manager dashboard/couriers/shipments/assign.

---

### J) Warehouse portal (`/warehouse/` — `store/urls_warehouse.py`)

Auth/profile/reset; availability + live API; available orders/live/accept; order detail/poll; internal chat; create waybill; label + QR; scan + consume; manager dashboard/team/orders/assign.

---

### K) Acceptance checklist

Same logical items as the Arabic checklist (hierarchy, cart rules, guest tracking, state machines, fake payments, warehouse/shipping flows, support rules, CS restrictions, superuser-only destructive ops).

---

### L) Final instruction block (paste at the end)

```
Implement the Flutter app(s) described above using a LOCAL database only for v1
(e.g. SQLite via Drift or equivalent), with a Repository layer ready for a future API.
Mirror the Django reference project’s entities, role rules, portals, and state machines.
Provide optional seed data, README setup steps, and a short architecture note.
```

---

## 3) ملحق: جدول مطابقة مسارات Django ↔ شاشات/عمليات Flutter

**جذر المشروع (`config/urls.py`):** يضمّ `''` → `store.urls`، و`'shipping/'` → `urls_shipping`، و`'warehouse/'` → `urls_warehouse`. المعالجات `handler400`…`handler500` اختيارية في Flutter.

### واجهة العملاء — `store/urls.py` (بادئة URL: `/`)

| Django path | name (اختياري) | ملاحظة Flutter |
|-------------|----------------|------------------|
| `''` | welcome | شاشة ترحيب |
| `home/` | wardrobe | الدولاب الرئيسي |
| `compartment/<int:compartment_id>/` | compartment | تفاصيل خانة |
| `shelf/<int:shelf_id>/` | shelf | تفاصيل رف |
| `category/<int:category_id>/` | category | قائمة منتجات صنف + ترقيم |
| `products/` | products_all | كتالوج كامل |
| `product/<int:product_id>/` | product | تفاصيل منتج |
| `p/<slug:slug>/` | product_by_slug | نفس التفاصيل عبر slug |
| `cart/` | cart_view | السلة |
| `cart/coupon/` | cart_coupon_apply | تطبيق كوبون |
| `cart/add/<int:product_id>/` | cart_add | إجراء |
| `cart/update/<int:product_id>/` | cart_update | إجراء |
| `cart/remove/<int:product_id>/` | cart_remove | إجراء |
| `cart/share/create/` | cart_share_create | إنشاء رابط |
| `cart/share/<str:token>/` | cart_share_view | معاينة مشاركة |
| `cart/share/<str:token>/apply/` | cart_share_apply | دمج في السلة |
| `checkout/` | checkout | إتمام |
| `order/success/<int:order_id>/` | order_success | تأكيد |
| `order/track/` | order_track | تتبع ضيف/عام |
| `pay/fake/<int:attempt_id>/` | fake_gateway_pay | دفع وهمي |
| `pay/fake/<int:attempt_id>/callback/` | fake_gateway_callback | رجوع الدفع |
| `webhooks/fake-gateway/` | fake_gateway_webhook | محاكاة |
| `webhooks/fake-shipping/` | fake_shipping_webhook | محاكاة |
| `register/` | user_register | تسجيل |
| `verify-otp/` | verify_otp | تحقق بريد |
| `login/` | user_login | دخول |
| `forgot-password/` | forgot_password | استعادة 1 |
| `forgot-password/otp/` | forgot_password_otp | استعادة 2 |
| `forgot-password/new-password/` | forgot_password_new_password | استعادة 3 |
| `logout/` | user_logout | خروج |
| `wishlist/` | wishlist_view | مفضلة |
| `wishlist/add/<int:product_id>/` | wishlist_add | إجراء |
| `wishlist/remove/<int:product_id>/` | wishlist_remove | إجراء |
| `my-orders/` | my_orders | قائمة طلبات |
| `order/<int:order_id>/` | order_detail | تفاصيل |
| `order/<int:order_id>/poll/` | order_detail_poll | تحديث حي |
| `order/track/poll/` | order_track_poll | تحديث تتبع |
| `reorder/<int:order_id>/` | reorder | إعادة إضافة للسلة |
| `my-returns/` | my_returns | مرتجعات |
| `return/<int:return_id>/` | return_detail | تفاصيل مرتجع |
| `return/<int:return_id>/poll/` | return_detail_poll | poll |
| `return/create/<int:order_id>/` | create_return | طلب إرجاع |
| `review/add/<int:product_id>/` | review_add | تقييم |
| `review/delete/<int:review_id>/` | review_delete | حذف |
| `reviews/` | my_reviews | مراجعاتي |
| `profile/` | profile_view | ملف |
| `profile/edit/` | profile_edit | تعديل ملف |
| `addresses/` | addresses_list | عناوين |
| `addresses/add/` | address_add | إضافة |
| `addresses/<int:address_id>/edit/` | address_edit | تعديل |
| `addresses/<int:address_id>/delete/` | address_delete | حذف |
| `addresses/<int:address_id>/set-default/` | address_set_default | افتراضي |
| `search/` | search | بحث |
| `about/` | about_view | عن المتجر |
| `contact/` | contact_view | اتصل بنا |
| `support/` | support_chat | دردشة |
| `support/new/` | support_new_conversation | محادثة جديدة |
| `support/poll/` | support_poll | تحديث |
| `support/send/` | support_send | إرسال |
| `support/end/` | support_end | إنهاء |
| `manage/` | *(include)* | يشير إلى الجدول التالي |

### لوحة الإدارة — `store/urls_manage.py` (بادئة URL: `/manage/`)

| Django path | name | ملاحظة Flutter |
|-------------|------|----------------|
| `system/backup/` | site_backup | superuser فقط → تصدير DB محلي |
| `system/wipe/` | site_full_wipe | superuser فقط |
| `''` | dashboard | لوحة |
| `login/` | login | دخول إدارة |
| `forgot-password/` | forgot_password | |
| `forgot-password/otp/` | forgot_password_otp | |
| `forgot-password/new-password/` | forgot_password_new_password | |
| `logout/` | logout | |
| `api/notifications/` | notifications_json | |
| `api/mark-seen/` | mark_seen_json | |
| `api/mark-seen-bulk/` | mark_seen_bulk_json | |
| `api/packers-availability/` | packers_availability_live | |
| `api/couriers-availability/` | couriers_availability_live | |
| `overview/` | overview | |
| `compartments/` | compartment_list | |
| `compartments/add/` | compartment_add | |
| `compartments/<int:pk>/edit/` | compartment_edit | |
| `compartments/<int:pk>/delete/` | compartment_delete | |
| `shelves/` | shelf_list | |
| `shelves/add/` | shelf_add | |
| `shelves/<int:pk>/edit/` | shelf_edit | |
| `shelves/<int:pk>/delete/` | shelf_delete | |
| `categories/` | category_list | |
| `categories/add/` | category_add | |
| `categories/<int:pk>/edit/` | category_edit | |
| `categories/<int:pk>/delete/` | category_delete | |
| `products/` | product_list | |
| `products/add/` | product_add | |
| `products/<int:pk>/edit/` | product_edit | |
| `products/<int:pk>/variants/` | product_variants_manage | |
| `products/variants/export.csv` | variants_inventory_export_csv | |
| `products/variants/<int:variant_id>/stock.json` | variant_stock_json | |
| `products/<int:pk>/delete/` | product_delete | |
| `promotions/` | promotion_list | |
| `promotions/add/` | promotion_add | |
| `promotions/<int:pk>/edit/` | promotion_edit | |
| `promotions/<int:pk>/delete/` | promotion_delete | |
| `promotions/<int:pk>/toggle-active/` | promotion_toggle_active | |
| `coupons/` | coupon_list | |
| `coupons/add/` | coupon_add | |
| `coupons/<int:pk>/edit/` | coupon_edit | |
| `coupons/<int:pk>/delete/` | coupon_delete | |
| `coupons/<int:pk>/toggle-active/` | coupon_toggle_active | |
| `orders/` | order_list | |
| `orders/<int:pk>/` | order_detail | |
| `orders/<int:pk>/edit/` | order_edit | |
| `orders/<int:pk>/live-state/` | order_detail_live_state | |
| `orders/<int:pk>/waybill-qr.png` | order_waybill_qr | |
| `orders/<int:pk>/shipping-label/` | order_shipping_label_print | |
| `shipments/` | shipments_list_manage | |
| `shipments/<int:pk>/` | shipment_detail_manage | |
| `couriers/` | couriers_list | |
| `packers/` | packers_list | |
| `warehouse/` | warehouse_orders_manage | |
| `returns/` | returns_list | |
| `returns/<int:pk>/` | return_detail | |
| `returns/<int:pk>/live-state/` | return_detail_live_state | |
| `users/` | users_list | |
| `users/<int:user_id>/` | user_detail | |
| `users/<int:user_id>/edit/` | user_profile_edit | |
| `users/<int:user_id>/toggle/` | user_toggle_active | |
| `users/<int:user_id>/toggle-availability/` | user_toggle_availability | |
| `users/roles/shipping-managers/` | shipping_managers_list | |
| `users/roles/warehouse-managers/` | warehouse_managers_list | |
| `users/roles/customer-service/` | customer_service_accounts_list | |
| `users/roles/customer-service-managers/` | customer_service_managers_list | |
| `admins/` | admins_list | |
| `support/` | support_portal | |
| `support/thread/<int:thread_id>/` | support_thread_detail | |
| `support/api/signature/` | support_portal_signature_json | |
| `support/api/thread/<int:thread_id>/messages/` | support_thread_messages_json | |
| `support/api/thread/<int:thread_id>/send/` | support_thread_send_json | |
| `support/api/thread/<int:thread_id>/claim/` | support_thread_claim_json | |
| `support/api/thread/<int:thread_id>/mark-read/` | support_thread_mark_read_json | |
| `support/api/thread/<int:thread_id>/end/` | support_thread_end_json | |
| `support/team/` | support_team_accounts | |
| `support/team/agent/<int:agent_id>/` | support_agent_detail | |
| `support/team/<int:user_id>/toggle-availability/` | support_toggle_availability | |
| `support/archive/thread/<int:thread_id>/` | support_archive_thread | |
| `support/archive/agent/<int:agent_id>/` | support_archive_agent | |
| `contact-messages/` | contact_messages_list | |

### الشحن — `store/urls_shipping.py` (بادئة: `/shipping/`)

| Django path | name |
|-------------|------|
| `''` | dashboard |
| `login/` | login |
| `forgot-password/` | forgot_password |
| `forgot-password/otp/` | forgot_password_otp |
| `forgot-password/new-password/` | forgot_password_new_password |
| `logout/` | logout |
| `profile/` | profile |
| `scan/` | scan |
| `scan/pickup/` | scan_pickup |
| `scan/deliver/` | scan_deliver |
| `scan/consume/` | scan_consume |
| `deliver/otp/` | deliver_otp |
| `availability/` | set_availability |
| `api/my-availability/` | my_availability_live |
| `jobs/` | available_jobs |
| `jobs/live/` | available_jobs_live |
| `jobs/<int:pk>/accept/` | accept_job |
| `shipments/` | shipments_list |
| `shipments/<int:pk>/` | shipment_detail |
| `shipments/<int:pk>/poll/` | shipment_detail_poll |
| `internal-chat/` | internal_chat |
| `manager/` | manager_dashboard |
| `manager/couriers/` | manager_couriers |
| `manager/shipments/` | manager_shipments |
| `manager/shipments/<int:pk>/assign/` | assign_shipment |

### المستودع — `store/urls_warehouse.py` (بادئة: `/warehouse/`)

| Django path | name |
|-------------|------|
| `''` | dashboard |
| `login/` | login |
| `forgot-password/` | forgot_password |
| `forgot-password/otp/` | forgot_password_otp |
| `forgot-password/new-password/` | forgot_password_new_password |
| `logout/` | logout |
| `profile/` | profile |
| `availability/` | set_availability |
| `api/my-availability/` | my_availability_live |
| `jobs/` | available_orders |
| `jobs/live/` | available_orders_live |
| `jobs/<int:pk>/accept/` | accept_order |
| `orders/<int:pk>/` | order_detail |
| `orders/<int:pk>/poll/` | order_detail_poll |
| `internal-chat/` | internal_chat |
| `orders/<int:pk>/waybill/create/` | create_shipping_waybill |
| `orders/<int:pk>/label/` | shipping_label |
| `orders/<int:pk>/label/qr.png` | order_label_qr |
| `scan/` | scan |
| `scan/consume/` | scan_consume |
| `manager/` | manager_dashboard |
| `manager/team/` | manager_team |
| `manager/orders/` | manager_orders |
| `manager/orders/<int:pk>/assign/` | assign_order |

---

**انتهى المستند.** يمكن لصق القسم 1 أو 2 كاملاً لنموذج ذكاء اصطناعي مع إرفاق ملف `store/models.py` من هذا المستودع للتفاصيل الحقلية.
