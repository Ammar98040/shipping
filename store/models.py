"""
Models: Wardrobe hierarchy and orders.
Compartment → Shelf → Category → Product.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class Compartment(models.Model):
    """خانة الدولاب - الملابس، الشنط، الأحذية، الإكسسوارات"""
    name_ar = models.CharField(_('الاسم (عربي)'), max_length=100)
    name_en = models.CharField(_('الاسم (إنجليزي)'), max_length=100, blank=True)
    order = models.PositiveIntegerField(_('ترتيب العرض'), default=0)
    image = models.ImageField(_('صورة'), upload_to='compartments/', blank=True, null=True)
    is_active = models.BooleanField(_('نشط'), default=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = _('خانة')
        verbose_name_plural = _('الخانات')

    def __str__(self):
        return self.name_ar


class Shelf(models.Model):
    """رف - داخل كل خانة (مثلاً: صيفي، شتوي)"""
    compartment = models.ForeignKey(
        Compartment, on_delete=models.CASCADE, related_name='shelves',
        verbose_name=_('الخانة')
    )
    name_ar = models.CharField(_('الاسم (عربي)'), max_length=100)
    name_en = models.CharField(_('الاسم (إنجليزي)'), max_length=100, blank=True)
    order = models.PositiveIntegerField(_('ترتيب العرض'), default=0)
    image = models.ImageField(_('صورة'), upload_to='shelves/', blank=True, null=True)
    is_active = models.BooleanField(_('نشط'), default=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = _('رف')
        verbose_name_plural = _('الرفوف')

    def __str__(self):
        return f"{self.compartment.name_ar} - {self.name_ar}"


class Category(models.Model):
    """صنف - تحت كل رف (مثلاً: تيشيرتات، شورتات)"""
    shelf = models.ForeignKey(
        Shelf, on_delete=models.CASCADE, related_name='categories',
        verbose_name=_('الرف')
    )
    name_ar = models.CharField(_('الاسم (عربي)'), max_length=100)
    name_en = models.CharField(_('الاسم (إنجليزي)'), max_length=100, blank=True)
    order = models.PositiveIntegerField(_('ترتيب العرض'), default=0)
    image = models.ImageField(_('صورة'), upload_to='categories/', blank=True, null=True)
    is_active = models.BooleanField(_('نشط'), default=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = _('صنف')
        verbose_name_plural = _('الأصناف')

    def __str__(self):
        return f"{self.shelf.name_ar} - {self.name_ar}"


class Product(models.Model):
    """منتج - داخل كل صنف"""
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name='products',
        verbose_name=_('الصنف')
    )
    sku = models.CharField(
        _('رمز المنتج'), max_length=50, unique=True, null=True, blank=True,
        help_text='رمز فريد للمنتج (مثال: T-001). سيتم توليده تلقائياً إذا ترك فارغاً'
    )
    slug = models.SlugField(_('معرّف الرابط'), max_length=255, unique=True, blank=True, null=True, db_index=True)
    name_ar = models.CharField(_('الاسم (عربي)'), max_length=200)
    name_en = models.CharField(_('الاسم (إنجليزي)'), max_length=200, blank=True)
    description_ar = models.TextField(_('الوصف (عربي)'), blank=True)
    description_en = models.TextField(_('الوصف (إنجليزي)'), blank=True)
    price = models.DecimalField(_('السعر'), max_digits=10, decimal_places=2)
    image = models.ImageField(_('صورة رئيسية'), upload_to='products/', blank=True, null=True)
    stock = models.PositiveIntegerField(_('الكمية المتوفرة'), default=0)
    order = models.PositiveIntegerField(_('ترتيب العرض'), default=0)
    is_active = models.BooleanField(_('نشط'), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = _('منتج')
        verbose_name_plural = _('المنتجات')

    def __str__(self):
        return f"{self.sku} - {self.name_ar}" if self.sku else self.name_ar

    def save(self, *args, **kwargs):
        """توليد SKU تلقائي إذا لم يكن موجوداً"""
        if not self.sku:
            category_prefix = self.category.name_ar[0].upper() if self.category.name_ar else 'P'
            # ضمان عدم تكرار SKU حتى لو وُجدت بيانات قديمة غير منظمة
            qs = Product.objects.filter(sku__startswith=f"{category_prefix}-").exclude(sku__isnull=True).exclude(sku='')

            # حاول استخراج أكبر رقم موجود
            max_num = 0
            for p in qs.only('sku'):
                try:
                    part = (p.sku or '').split('-', 1)[1]
                    n = int(part)
                    if n > max_num:
                        max_num = n
                except Exception:
                    continue

            new_number = max_num + 1
            while True:
                candidate = f"{category_prefix}-{new_number:03d}"
                if not Product.objects.filter(sku=candidate).exists():
                    self.sku = candidate
                    break
                new_number += 1

        if not self.slug:
            base_name = self.name_ar or self.name_en or self.sku or 'product'
            base_slug = slugify(base_name) or 'product'
            candidate = base_slug
            idx = 2
            while Product.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base_slug}-{idx}"
                idx += 1
            self.slug = candidate

        super().save(*args, **kwargs)

    @property
    def average_rating(self):
        """متوسط التقييم"""
        from django.db.models import Avg
        avg = self.reviews.aggregate(Avg('rating'))['rating__avg']
        return round(avg, 1) if avg else 0

    @property
    def reviews_count(self):
        """عدد التقييمات"""
        return self.reviews.count()

    @property
    def default_variant(self):
        """النسخة الافتراضية للمنتج (للانتقال التدريجي إلى نظام النسخ)."""
        return self.variants.order_by('sort_order', 'id').first()

    @property
    def total_variant_stock(self):
        """إجمالي مخزون النسخ النشطة. fallback إلى stock القديم عند عدم وجود نسخ."""
        active_variants = self.variants.filter(is_active=True)
        if active_variants.exists():
            return sum(v.stock_quantity for v in active_variants)
        return self.stock

    @property
    def primary_gallery_image(self):
        primary = self.gallery_images.filter(is_primary=True).order_by('sort_order', 'id').first()
        if primary:
            return primary
        return self.gallery_images.order_by('sort_order', 'id').first()


# عناوين مزروعة للنسخة الافتراضية — لا تُعرض للعميل في واجهة المتجر
_PLACEHOLDER_VARIANT_TITLES = frozenset({'النسخة الافتراضية', 'Default'})


class ProductVariant(models.Model):
    """نسخة منتج (لون/ستايل/مقاس) بمخزون مستقل."""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='variants',
        verbose_name=_('المنتج')
    )
    code = models.CharField(_('رمز النسخة (SKU فرعي)'), max_length=80)
    title = models.CharField(_('اسم النسخة'), max_length=120, blank=True)
    color_name = models.CharField(_('اللون'), max_length=80, blank=True)
    color_hex = models.CharField(_('لون HEX'), max_length=7, blank=True, help_text='#RRGGBB')
    price = models.DecimalField(_('سعر النسخة'), max_digits=10, decimal_places=2, null=True, blank=True)
    stock_quantity = models.PositiveIntegerField(_('مخزون النسخة'), default=0)
    sort_order = models.PositiveIntegerField(_('ترتيب العرض'), default=0)
    is_active = models.BooleanField(_('نشطة للبيع'), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('نسخة منتج')
        verbose_name_plural = _('نسخ المنتجات')
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['product', 'code'], name='unique_variant_code_per_product'),
        ]
        indexes = [
            models.Index(fields=['product', 'is_active', 'sort_order']),
        ]

    def __str__(self):
        label = self.title or self.color_name or self.code
        return f"{self.product_id}:{label}"

    @property
    def effective_price(self):
        return self.price if self.price is not None else self.product.price

    @property
    def is_distinct_customer_choice(self):
        """هل تُعرض كخيار منفصل للعميل (لون/نسخة)؟ وإلا تُستخدم بيانات المنتج الرئيسي في المتجر."""
        if self.customer_variant_color_label:
            return True
        if (self.color_hex or '').strip():
            return True
        return False

    @property
    def customer_variant_color_label(self):
        """نص لون/نسخة للعميل؛ None عندما لا يوجد سوى تسمية افتراضية مزروعة."""
        cn = (self.color_name or '').strip()
        if cn:
            if cn in _PLACEHOLDER_VARIANT_TITLES:
                return None
            return cn
        t = (self.title or '').strip()
        if t and t not in _PLACEHOLDER_VARIANT_TITLES:
            return t
        return None

    @property
    def customer_variant_button_label(self):
        """نص زر اختيار النسخة في صفحة المنتج (بدون رمز SKU)."""
        cl = self.customer_variant_color_label
        if cl:
            return cl
        return 'قياسي'

    @property
    def open_order_items_exist(self):
        """طلبات لم تُسلَّم بعد (ليست حالة تم التوصيل أو ملغي)."""
        return self.order_items.exclude(
            order__status__in=['delivered', 'cancelled'],
        ).exists()

    @property
    def can_delete_variant(self):
        """حذف النسخة مسموح ما لم يوجد طلب غير مُسلَّم وغير ملغٍ."""
        return not self.open_order_items_exist


class ProductVariantImage(models.Model):
    """صور متعددة لكل نسخة منتج."""
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name='images',
        verbose_name=_('نسخة المنتج')
    )
    image = models.ImageField(_('الصورة'), upload_to='products/variants/')
    alt_text = models.CharField(_('نص بديل'), max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(_('ترتيب الصورة'), default=0)
    is_primary = models.BooleanField(_('صورة أساسية'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('صورة نسخة المنتج')
        verbose_name_plural = _('صور نسخ المنتجات')
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['variant', 'sort_order']),
        ]

    def __str__(self):
        return f"VariantImage({self.variant_id})"


class ProductGalleryImage(models.Model):
    """صور المنتج العامة (غير مرتبطة بالألوان)."""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='gallery_images',
        verbose_name=_('المنتج')
    )
    image = models.ImageField(_('الصورة'), upload_to='products/gallery/')
    code = models.CharField(_('SKU صورة المنتج'), max_length=90, blank=True)
    title = models.CharField(_('اسم الصورة'), max_length=140, blank=True)
    price = models.DecimalField(_('سعر الصورة'), max_digits=10, decimal_places=2, null=True, blank=True)
    stock_quantity = models.PositiveIntegerField(_('كمية الصورة'), default=0)
    alt_text = models.CharField(_('نص بديل'), max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(_('ترتيب الصورة'), default=0)
    is_primary = models.BooleanField(_('صورة رئيسية للمنتج'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('صورة معرض المنتج')
        verbose_name_plural = _('صور معرض المنتجات')
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['product', 'sort_order']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['product', 'code'], name='unique_gallery_code_per_product'),
        ]

    def __str__(self):
        return f"ProductGalleryImage({self.product_id})"

    def save(self, *args, **kwargs):
        if not self.code:
            base = (self.product.sku or f"P{self.product_id}").strip() or f"P{self.product_id}"
            used = set(
                ProductGalleryImage.objects.filter(product=self.product).exclude(pk=self.pk).values_list('code', flat=True)
            )
            n = 1
            while True:
                candidate = f"{base}-G{n:03d}"
                if candidate not in used:
                    self.code = candidate
                    break
                n += 1
        if not self.title:
            self.title = self.product.name_ar
        super().save(*args, **kwargs)

    @property
    def effective_price(self):
        return self.price if self.price is not None else self.product.price

    @property
    def effective_stock(self):
        return int(self.stock_quantity if self.stock_quantity is not None else self.product.stock)


class InventoryMovement(models.Model):
    """سجل حركة مخزون النسخ للتدقيق والمراجعة."""
    MOVE_INBOUND = 'inbound'
    MOVE_SALE = 'sale'
    MOVE_CANCEL_RESTORE = 'cancel_restore'
    MOVE_RETURN_RESTORE = 'return_restore'
    MOVE_ADJUSTMENT = 'adjustment'
    MOVE_CHOICES = [
        (MOVE_INBOUND, _('إضافة مخزون')),
        (MOVE_SALE, _('بيع/خصم')),
        (MOVE_CANCEL_RESTORE, _('استرجاع بعد إلغاء')),
        (MOVE_RETURN_RESTORE, _('استرجاع بعد مرتجع')),
        (MOVE_ADJUSTMENT, _('تعديل يدوي')),
    ]

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name='movements',
        verbose_name=_('نسخة المنتج')
    )
    movement_type = models.CharField(_('نوع الحركة'), max_length=30, choices=MOVE_CHOICES)
    quantity = models.PositiveIntegerField(_('الكمية'))
    reference_type = models.CharField(_('نوع المرجع'), max_length=30, blank=True)
    reference_id = models.PositiveIntegerField(_('معرف المرجع'), null=True, blank=True)
    note = models.CharField(_('ملاحظة'), max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inventory_movements', verbose_name=_('تم بواسطة')
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('حركة مخزون')
        verbose_name_plural = _('حركات المخزون')
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['variant', 'created_at']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]

    def __str__(self):
        return f"{self.variant_id}:{self.movement_type}:{self.quantity}"


class Order(models.Model):
    """طلب عميل"""

    # ── حالة الطلب (مسار التنفيذ) ──────────────────────────────────────
    STATUS_PENDING       = 'pending'
    STATUS_CONFIRMED     = 'confirmed'
    STATUS_PROCESSING    = 'processing'
    STATUS_READY         = 'ready_to_ship'
    STATUS_SHIPPED       = 'shipped'
    STATUS_DELIVERED     = 'delivered'
    STATUS_CANCELLED     = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING,    _('قيد الانتظار')),
        (STATUS_CONFIRMED,  _('تم التأكيد')),
        (STATUS_PROCESSING, _('قيد التجهيز')),
        (STATUS_READY,      _('جاهز للشحن')),
        (STATUS_SHIPPED,    _('تم الشحن')),
        (STATUS_DELIVERED,  _('تم التوصيل')),
        (STATUS_CANCELLED,  _('ملغي')),
    ]

    # الانتقالات المسموحة: من الحالة الحالية → الحالات المسموح الانتقال إليها
    ALLOWED_TRANSITIONS = {
        STATUS_PENDING:    [STATUS_CONFIRMED, STATUS_CANCELLED],
        STATUS_CONFIRMED:  [STATUS_PROCESSING, STATUS_CANCELLED],
        STATUS_PROCESSING: [STATUS_READY, STATUS_CANCELLED],
        STATUS_READY:      [STATUS_SHIPPED, STATUS_CANCELLED],
        STATUS_SHIPPED:    [STATUS_DELIVERED, STATUS_CANCELLED],
        STATUS_DELIVERED:  [],
        STATUS_CANCELLED:  [],
    }

    # ── حالة الدفع (مستقلة عن مسار التنفيذ) ────────────────────────────
    PAY_STATUS_PENDING   = 'pending'
    PAY_STATUS_PAID      = 'paid'
    PAY_STATUS_FAILED    = 'failed'
    PAY_STATUS_CANCELLED = 'cancelled'
    PAY_STATUS_REFUNDED  = 'refunded'
    PAY_STATUS_PARTIAL   = 'partially_refunded'

    PAYMENT_STATUS_CHOICES = [
        (PAY_STATUS_PENDING,   _('في انتظار الدفع')),
        (PAY_STATUS_PAID,      _('مدفوع')),
        (PAY_STATUS_FAILED,    _('فشل الدفع')),
        (PAY_STATUS_CANCELLED, _('دفع ملغي')),
        (PAY_STATUS_REFUNDED,  _('تم الاسترداد')),
        (PAY_STATUS_PARTIAL,   _('استرداد جزئي')),
    ]

    # ── طريقة الدفع ─────────────────────────────────────────────────────
    PAYMENT_CASH    = 'cash_on_delivery'
    PAYMENT_GATEWAY = 'payment_gateway'
    PAYMENT_CHOICES = [
        (PAYMENT_CASH,    _('الدفع عند الاستلام')),
        (PAYMENT_GATEWAY, _('الدفع بالبطاقة (فيزا / مدى)')),
    ]

    # ── نوع العميل ──────────────────────────────────────────────────────
    CUSTOMER_REGISTERED = 'registered'
    CUSTOMER_GUEST      = 'guest'
    CUSTOMER_TYPE_CHOICES = [
        (CUSTOMER_REGISTERED, _('مستخدم مسجل')),
        (CUSTOMER_GUEST,      _('ضيف')),
    ]

    # ── أسباب الإلغاء ───────────────────────────────────────────────────
    CANCEL_BY_CUSTOMER  = 'customer_request'
    CANCEL_OUT_OF_STOCK = 'out_of_stock'
    CANCEL_PAYMENT_FAIL = 'payment_failed'
    CANCEL_BY_ADMIN     = 'admin_decision'
    CANCEL_OTHER        = 'other'
    CANCEL_REASON_CHOICES = [
        (CANCEL_BY_CUSTOMER,  _('طلب العميل')),
        (CANCEL_OUT_OF_STOCK, _('نفاد المخزون')),
        (CANCEL_PAYMENT_FAIL, _('فشل الدفع')),
        (CANCEL_BY_ADMIN,     _('قرار إداري')),
        (CANCEL_OTHER,        _('أخرى')),
    ]

    # ── الحقول ──────────────────────────────────────────────────────────
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='orders', verbose_name=_('المستخدم')
    )
    packer = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='packed_orders', verbose_name=_('مجهّز الطلب')
    )
    customer_type = models.CharField(
        _('نوع العميل'), max_length=20,
        choices=CUSTOMER_TYPE_CHOICES, default=CUSTOMER_REGISTERED
    )
    customer_name  = models.CharField(_('اسم العميل'),  max_length=200)
    customer_phone = models.CharField(_('رقم الجوال'),  max_length=20)
    customer_email = models.EmailField(_('البريد'),      blank=True)
    address        = models.TextField(_('العنوان'))

    status = models.CharField(
        _('حالة الطلب'), max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    payment_method = models.CharField(
        _('طريقة الدفع'), max_length=30, choices=PAYMENT_CHOICES, default=PAYMENT_CASH
    )
    payment_status = models.CharField(
        _('حالة الدفع'), max_length=30,
        choices=PAYMENT_STATUS_CHOICES, default=PAY_STATUS_PENDING
    )
    delivery_fee = models.DecimalField(
        _('رسوم التوصيل'), max_digits=10, decimal_places=2, default=0
    )
    notes = models.TextField(_('ملاحظات'), blank=True)

    # سبب الإلغاء
    cancel_reason      = models.CharField(
        _('سبب الإلغاء'), max_length=30,
        choices=CANCEL_REASON_CHOICES, blank=True
    )
    cancel_note        = models.TextField(_('ملاحظة الإلغاء'), blank=True)

    # رمز تتبع الضيف (لتتبع الطلب بدون حساب)
    tracking_token = models.CharField(
        _('رمز التتبع'), max_length=64, blank=True, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('طلب')
        verbose_name_plural = _('الطلبات')

    def __str__(self):
        return f"#{self.id} - {self.customer_name}"

    def save(self, *args, **kwargs):
        # توليد رمز تتبع للضيف إذا لم يكن موجوداً
        if not self.tracking_token:
            import secrets
            self.tracking_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def total(self):
        items_total = sum(item.subtotal for item in self.items.all())
        return items_total + (self.delivery_fee or 0)

    @property
    def subtotal(self):
        return sum(item.subtotal for item in self.items.all())

    @property
    def is_guest(self):
        return self.customer_type == self.CUSTOMER_GUEST

    @property
    def can_be_cancelled(self):
        return self.status in [self.STATUS_PENDING, self.STATUS_CONFIRMED, self.STATUS_PROCESSING]

    @property
    def can_be_returned(self):
        return self.status == self.STATUS_DELIVERED

    def get_allowed_next_statuses(self):
        return self.ALLOWED_TRANSITIONS.get(self.status, [])

    def get_status_progress(self):
        """نسبة تقدم الطلب (للشريط البصري)"""
        progress_map = {
            self.STATUS_PENDING:    10,
            self.STATUS_CONFIRMED:  25,
            self.STATUS_PROCESSING: 45,
            self.STATUS_READY:      65,
            self.STATUS_SHIPPED:    80,
            self.STATUS_DELIVERED:  100,
            self.STATUS_CANCELLED:  0,
        }
        return progress_map.get(self.status, 0)


class Promotion(models.Model):
    """عرض/بروموشن يخصّم من سعر المنتج داخل السلة."""

    SCOPE_ALL = 'all'
    SCOPE_COMPARTMENTS = 'compartments'
    SCOPE_SHELVES = 'shelves'
    SCOPE_CATEGORIES = 'categories'
    SCOPE_PRODUCTS = 'products'
    SCOPE_VARIANTS = 'variants'
    SCOPE_CHOICES = [
        (SCOPE_ALL, _('الكل')),
        (SCOPE_COMPARTMENTS, _('الخانات')),
        (SCOPE_SHELVES, _('الرفوف')),
        (SCOPE_CATEGORIES, _('الأصناف')),
        (SCOPE_PRODUCTS, _('المنتجات')),
        (SCOPE_VARIANTS, _('النسخ')),
    ]

    DISCOUNT_PERCENT = 'percent'
    DISCOUNT_FIXED = 'fixed'
    DISCOUNT_TYPE_CHOICES = [
        (DISCOUNT_PERCENT, _('نسبة مئوية')),
        (DISCOUNT_FIXED, _('مبلغ ثابت')),
    ]

    name = models.CharField(_('اسم العرض'), max_length=150)
    description = models.TextField(_('وصف العرض'), blank=True)

    is_active = models.BooleanField(_('نشط'), default=True)
    start_at = models.DateTimeField(_('تاريخ البداية'), null=True, blank=True)
    end_at = models.DateTimeField(_('تاريخ النهاية'), null=True, blank=True)

    scope = models.CharField(
        _('نطاق التطبيق'),
        max_length=30,
        choices=SCOPE_CHOICES,
        default=SCOPE_ALL,
        help_text=_('اختر أين سيتم تطبيق الخصم (خانة/رف/صنف/منتج/نسخة/الكل).'),
    )

    discount_type = models.CharField(_('نوع الخصم'), max_length=20, choices=DISCOUNT_TYPE_CHOICES, default=DISCOUNT_PERCENT)
    discount_value = models.DecimalField(_('قيمة الخصم'), max_digits=10, decimal_places=2)

    # حد أدنى لعدد القطع في السطر (للجولة/تجارب فقط)
    min_quantity = models.PositiveIntegerField(_('الحد الأدنى للكمية'), default=1)

    # ربط العرض وفق نطاق النظام: خانة/رف/صنف/منتج/نسخة (فارغ = ينطبق على الكل)
    compartments = models.ManyToManyField(
        Compartment,
        verbose_name=_('الخانات'),
        blank=True,
        related_name='compartment_promotions',
    )
    shelves = models.ManyToManyField(
        Shelf,
        verbose_name=_('الرفوف'),
        blank=True,
        related_name='shelf_promotions',
    )
    categories = models.ManyToManyField(
        Category,
        verbose_name=_('الأصناف'),
        blank=True,
        related_name='category_promotions',
    )
    products = models.ManyToManyField(
        Product,
        verbose_name=_('المنتجات'),
        blank=True,
        related_name='product_promotions',
    )
    variants = models.ManyToManyField(
        ProductVariant,
        verbose_name=_('النسخ'),
        blank=True,
        related_name='variant_promotions',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('عرض')
        verbose_name_plural = _('العروض')
        ordering = ['-updated_at', 'id']

    def __str__(self):
        return f"{self.name} ({self.discount_type}:{self.discount_value})"


class Coupon(models.Model):
    """كوبون خصم على إجمالي الطلب بعد خصم عروض المنتجات."""

    DISCOUNT_PERCENT = 'percent'
    DISCOUNT_FIXED = 'fixed'
    DISCOUNT_TYPE_CHOICES = [
        (DISCOUNT_PERCENT, _('نسبة مئوية')),
        (DISCOUNT_FIXED, _('مبلغ ثابت')),
    ]

    code = models.CharField(_('كود الكوبون'), max_length=50, unique=True, db_index=True)
    is_active = models.BooleanField(_('نشط'), default=True)
    start_at = models.DateTimeField(_('تاريخ البداية'), null=True, blank=True)
    end_at = models.DateTimeField(_('تاريخ النهاية'), null=True, blank=True)

    discount_type = models.CharField(_('نوع الخصم'), max_length=20, choices=DISCOUNT_TYPE_CHOICES, default=DISCOUNT_PERCENT)
    discount_value = models.DecimalField(_('قيمة الخصم'), max_digits=10, decimal_places=2)

    # عدد الأشخاص المسموح لهم باستخدام هذا الكوبون (مرة واحدة لكل شخص)
    max_uses_total = models.PositiveIntegerField(_('الحد الأقصى للاستخدام'), default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('كوبون')
        verbose_name_plural = _('كوبونات')
        ordering = ['-updated_at', 'id']

    def __str__(self):
        return self.code


class CouponRedemption(models.Model):
    """سجل استخدام الكوبون (مرة واحدة لكل عميل)."""

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='redemptions', verbose_name=_('الكوبون'))
    # للمستخدمين المسجلين
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='coupon_redemptions', verbose_name=_('المستخدم')
    )
    # للضيوف: عبر رقم الجوال المكتوب في checkout
    guest_phone = models.CharField(_('رقم الجوال (للكوبون)'), max_length=20, null=True, blank=True)

    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('تسجيل استخدام الكوبون')
        verbose_name_plural = _('سجلات استخدام الكوبونات')
        constraints = [
            models.UniqueConstraint(fields=['coupon', 'user'], name='unique_coupon_per_user'),
            models.UniqueConstraint(fields=['coupon', 'guest_phone'], name='unique_coupon_per_guest_phone'),
        ]
        ordering = ['-redeemed_at', 'id']

    def __str__(self):
        who = self.user.username if self.user else (self.guest_phone or 'guest')
        return f"{self.coupon.code} → {who}"


class OrderStatusHistory(models.Model):
    """سجل زمني لتغييرات حالة الطلب"""
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE,
        related_name='status_history', verbose_name=_('الطلب')
    )
    old_status = models.CharField(_('الحالة السابقة'), max_length=30, blank=True)
    new_status = models.CharField(_('الحالة الجديدة'), max_length=30)
    old_payment_status = models.CharField(_('حالة الدفع السابقة'), max_length=30, blank=True)
    new_payment_status = models.CharField(_('حالة الدفع الجديدة'), max_length=30, blank=True)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='order_changes', verbose_name=_('بواسطة')
    )
    is_automatic = models.BooleanField(_('تلقائي'), default=False)
    note = models.TextField(_('ملاحظة'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('وقت التغيير'))

    class Meta:
        ordering = ['created_at']
        verbose_name = _('سجل حالة الطلب')
        verbose_name_plural = _('سجلات حالات الطلبات')

    def __str__(self):
        return f"طلب #{self.order.id}: {self.old_status} → {self.new_status}"


class PaymentAttempt(models.Model):
    """محاولة دفع مرتبطة بطلب (محاكاة بوابة الدفع)"""
    PROVIDER_FAKE = 'fake_gateway'
    PROVIDER_CHOICES = [
        (PROVIDER_FAKE, _('بوابة دفع وهمية')),
    ]

    STATUS_CREATED = 'created'
    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_CREATED, _('تم الإنشاء')),
        (STATUS_PENDING, _('معلق')),
        (STATUS_SUCCESS, _('نجح')),
        (STATUS_FAILED, _('فشل')),
    ]

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE,
        related_name='payment_attempts', verbose_name=_('الطلب')
    )
    provider = models.CharField(
        _('المزود'), max_length=30, choices=PROVIDER_CHOICES, default=PROVIDER_FAKE
    )
    status = models.CharField(
        _('الحالة'), max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED
    )
    amount = models.DecimalField(_('المبلغ'), max_digits=10, decimal_places=2, default=0)
    reference = models.CharField(_('مرجع العملية'), max_length=100, blank=True, db_index=True)
    raw_payload = models.JSONField(_('بيانات خام'), blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('محاولة دفع')
        verbose_name_plural = _('محاولات الدفع')

    def __str__(self):
        return f"PaymentAttempt #{self.id} for Order #{self.order.id} ({self.status})"


class Shipment(models.Model):
    """شحنة مرتبطة بطلب (محاكاة شركة الشحن)"""
    PROVIDER_FAKE = 'fake_shipping'
    PROVIDER_CHOICES = [
        (PROVIDER_FAKE, _('شركة شحن وهمية')),
    ]

    STATUS_CREATED = 'created'
    STATUS_PICKED = 'picked_up'
    STATUS_IN_TRANSIT = 'in_transit'
    STATUS_OUT_FOR_DELIVERY = 'out_for_delivery'
    STATUS_DELIVERED = 'delivered'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_CREATED, _('تم إنشاء الشحنة')),
        (STATUS_PICKED, _('تم الاستلام من المتجر')),
        (STATUS_IN_TRANSIT, _('بالطريق')),
        (STATUS_OUT_FOR_DELIVERY, _('خرجت للتسليم')),
        (STATUS_DELIVERED, _('تم التسليم')),
        (STATUS_FAILED, _('تعثر التسليم')),
    ]

    order = models.OneToOneField(
        Order, on_delete=models.CASCADE,
        related_name='shipment', verbose_name=_('الطلب')
    )
    courier = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_shipments', verbose_name=_('المندوب')
    )
    provider = models.CharField(
        _('شركة الشحن'), max_length=30, choices=PROVIDER_CHOICES, default=PROVIDER_FAKE
    )
    tracking_number = models.CharField(_('رقم التتبع'), max_length=50, blank=True, db_index=True)
    status = models.CharField(_('حالة الشحنة'), max_length=30, choices=STATUS_CHOICES, default=STATUS_CREATED)
    last_event = models.TextField(_('آخر تحديث'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('شحنة')
        verbose_name_plural = _('الشحنات')

    def __str__(self):
        return f"Shipment for Order #{self.order.id} ({self.status})"


class LabelCode(models.Model):
    """
    كود قصير يُطبع تحت QR على بوليصة الشحن.
    الهدف: مسح QR أو إدخال الكود يدوياً لتغيير الحالات بأمان.
    """
    code = models.CharField(max_length=24, unique=True, db_index=True, verbose_name=_('كود البوليصة'))
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='label_code', verbose_name=_('الطلب'))
    shipment = models.OneToOneField(Shipment, on_delete=models.SET_NULL, null=True, blank=True, related_name='label_code', verbose_name=_('الشحنة'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('تاريخ الإنشاء'))
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name=_('آخر استخدام'))

    class Meta:
        verbose_name = _('كود بوليصة')
        verbose_name_plural = _('أكواد البوالص')

    def __str__(self):
        return f"LabelCode {self.code} (Order #{self.order_id})"


class ShippingWaybill(models.Model):
    """
    بوليصة شحن يُنشئها موظف المستودع ويُحفظ رقمها وقيمة الباركود
    للمراجعة والإجراءات الأمنية لاحقاً.
    """
    order = models.OneToOneField(
        Order, on_delete=models.CASCADE,
        related_name='shipping_waybill', verbose_name=_('الطلب')
    )
    shipment = models.ForeignKey(
        'Shipment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='waybills',
        verbose_name=_('الشحنة المرتبطة'),
    )
    waybill_number = models.CharField(
        _('رقم البوليصة'), max_length=64,
        help_text=_('رقم البوليصة الظاهر على وثيقة الشحن أو من شركة الناقل.'),
    )
    barcode_value = models.CharField(
        _('قيمة الباركود (أرشيف آمن)'), max_length=512, blank=True,
        help_text=_('النص الذي يقرأه الماسح الضوئي أو المرجع الداخلي للباركود.'),
    )
    linked_internal_code = models.CharField(
        _('الكود الداخلي للملصق'), max_length=32, blank=True,
        help_text=_('مرجع لكود الطباعة على الملصق (مثل كود QR الداخلي).'),
    )
    notes = models.TextField(_('ملاحظات المستودع'), blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='shipping_waybills_created',
        verbose_name=_('أنشأها'),
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='shipping_waybills_updated',
        verbose_name=_('آخر تعديل'),
    )
    created_at = models.DateTimeField(_('تاريخ الإنشاء'), auto_now_add=True)
    updated_at = models.DateTimeField(_('آخر تحديث'), auto_now=True)

    class Meta:
        verbose_name = _('بوليصة شحن')
        verbose_name_plural = _('بوالص الشحن')

    def __str__(self):
        return f"Waybill {self.waybill_number} (Order #{self.order_id})"


class DeliveryOTP(models.Model):
    """رمز تسليم (6 أرقام) لتأكيد التسليم من العميل."""
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='delivery_otps', verbose_name=_('الشحنة'))
    code = models.CharField(max_length=6, db_index=True, verbose_name=_('رمز التحقق'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('تاريخ الإنشاء'))
    expires_at = models.DateTimeField(verbose_name=_('ينتهي في'))
    is_used = models.BooleanField(default=False, verbose_name=_('تم استخدامه'))

    class Meta:
        verbose_name = _('رمز تسليم')
        verbose_name_plural = _('رموز التسليم')

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at


class OrderItem(models.Model):
    """عنصر في الطلب"""
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items', verbose_name=_('الطلب')
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_('المنتج')
    )
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='order_items', verbose_name=_('نسخة المنتج')
    )
    selected_gallery_image = models.ForeignKey(
        'ProductGalleryImage', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='order_items', verbose_name=_('صورة المنتج المختارة')
    )
    applied_promotion = models.ForeignKey(
        'Promotion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
        verbose_name=_('العرض المطبق'),
    )
    quantity = models.PositiveIntegerField(_('الكمية'), default=1)
    price = models.DecimalField(_('السعر عند الطلب'), max_digits=10, decimal_places=2)
    product_name_snapshot = models.CharField(
        _('اسم المنتج عند الطلب'), max_length=250, blank=True,
        help_text=_('يُستخدم لعرض الطلب بعد حذف المنتج من الكتالوج')
    )
    variant_label_snapshot = models.CharField(_('وصف اللون/النسخة عند الطلب'), max_length=200, blank=True)
    line_sku_snapshot = models.CharField(_('SKU السطر عند الطلب'), max_length=120, blank=True)
    image_url_snapshot = models.CharField(_('رابط صورة السطر عند الطلب'), max_length=500, blank=True)

    class Meta:
        verbose_name = _('عنصر الطلب')
        verbose_name_plural = _('عناصر الطلب')

    @classmethod
    def build_snapshots(cls, product, variant=None, selected_gallery_image=None, image_url=''):
        """حقول نصية للاحتفاظ ببيانات العرض بعد حذف المنتج/النسخة."""
        name_ar = (product.name_ar or '').strip()
        vlabel = ''
        if variant:
            vlabel = (variant.color_name or variant.title or '').strip()
        elif selected_gallery_image:
            vlabel = (selected_gallery_image.title or '').strip()
        if variant:
            sku = (variant.code or '').strip()
        elif selected_gallery_image and selected_gallery_image.code:
            sku = (selected_gallery_image.code or '').strip()
        else:
            sku = (product.sku or '').strip()
        return {
            'product_name_snapshot': name_ar,
            'variant_label_snapshot': vlabel,
            'line_sku_snapshot': sku,
            'image_url_snapshot': (image_url or '')[:500],
        }

    @property
    def subtotal(self):
        return self.quantity * self.price

    @property
    def display_product_name(self):
        if self.product_id:
            return self.product.name_ar
        return self.product_name_snapshot or ''

    @property
    def display_variant_label(self):
        if self.variant_id and self.variant:
            return self.variant.color_name or self.variant.title or self.variant.code
        return (self.variant_label_snapshot or '').strip()

    @property
    def display_sku(self):
        if self.variant_id and self.variant:
            return self.variant.code
        if self.selected_gallery_image_id and self.selected_gallery_image and self.selected_gallery_image.code:
            return self.selected_gallery_image.code
        if self.product_id and self.product:
            return self.product.sku or ''
        return self.line_sku_snapshot or ''

    @property
    def display_image_url(self):
        if self.variant_id and self.variant:
            images = list(self.variant.images.all())
            primary = next((img for img in images if img.is_primary), None) or (images[0] if images else None)
            if primary and getattr(primary, 'image', None):
                return primary.image.url
        if self.selected_gallery_image_id and self.selected_gallery_image and getattr(self.selected_gallery_image, 'image', None):
            return self.selected_gallery_image.image.url
        if self.product_id and self.product:
            gallery = self.product.gallery_images.filter(is_primary=True).order_by('sort_order', 'id').first()
            if not gallery:
                gallery = self.product.gallery_images.order_by('sort_order', 'id').first()
            if gallery and getattr(gallery, 'image', None):
                return gallery.image.url
            if self.product.image:
                return self.product.image.url
        return (self.image_url_snapshot or '').strip()


class Wishlist(models.Model):
    """المفضلات - منتجات محفوظة للمستخدم"""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='wishlist', verbose_name=_('المستخدم')
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, verbose_name=_('المنتج')
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name=_('تاريخ الإضافة'))

    class Meta:
        verbose_name = _('مفضلة')
        verbose_name_plural = _('المفضلات')
        unique_together = ('user', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.username} - {self.product.name_ar}"


class CartShare(models.Model):
    """رابط مشاركة سلة: عناصر وكميات قابلة للتطبيق على أي سلة."""
    token = models.CharField(_('رمز المشاركة'), max_length=64, unique=True, db_index=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cart_shares', verbose_name=_('أُنشئ بواسطة')
    )
    is_active = models.BooleanField(_('نشط'), default=True)
    views_count = models.PositiveIntegerField(_('مرات الفتح'), default=0)
    applied_count = models.PositiveIntegerField(_('مرات التطبيق'), default=0)
    last_viewed_at = models.DateTimeField(_('آخر فتح'), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('مشاركة سلة')
        verbose_name_plural = _('مشاركات السلة')
        ordering = ['-created_at']

    def __str__(self):
        return f"CartShare {self.token}"


class CartShareItem(models.Model):
    """عنصر داخل رابط مشاركة السلة."""
    cart_share = models.ForeignKey(
        CartShare, on_delete=models.CASCADE,
        related_name='items', verbose_name=_('مشاركة السلة')
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='cart_share_items', verbose_name=_('المنتج')
    )
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, null=True, blank=True,
        related_name='cart_share_items', verbose_name=_('نسخة المنتج')
    )
    quantity = models.PositiveIntegerField(_('الكمية'), default=1)
    price_snapshot = models.DecimalField(_('السعر وقت الإنشاء'), max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = _('عنصر مشاركة سلة')
        verbose_name_plural = _('عناصر مشاركة السلة')
        constraints = [
            models.UniqueConstraint(fields=['cart_share', 'product'], name='unique_cartshare_product'),
        ]

    def __str__(self):
        return f"{self.product_id} x {self.quantity}"


class UserProfile(models.Model):
    """الملف الشخصي للمستخدم"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name=_('المستخدم'))
    phone = models.CharField(_('رقم الجوال'), max_length=20, blank=True)
    ACCOUNT_REGULAR = 'regular'
    ACCOUNT_COURIER = 'courier'
    ACCOUNT_PACKER = 'packer'
    ACCOUNT_CUSTOMER_SERVICE = 'customer_service'
    ACCOUNT_CUSTOMER_SERVICE_MANAGER = 'customer_service_manager'
    ACCOUNT_WAREHOUSE_MANAGER = 'warehouse_manager'
    ACCOUNT_SHIPPING_MANAGER = 'shipping_manager'
    ACCOUNT_TYPE_CHOICES = [
        (ACCOUNT_REGULAR, _('مستخدم عادي')),
        (ACCOUNT_COURIER, _('مندوب شحن')),
        (ACCOUNT_PACKER, _('موظف تجهيز الطلبات')),
        (ACCOUNT_CUSTOMER_SERVICE, _('موظف خدمة العملاء')),
        (ACCOUNT_CUSTOMER_SERVICE_MANAGER, _('مسؤول خدمة العملاء')),
        (ACCOUNT_WAREHOUSE_MANAGER, _('مسؤول المستودع')),
        (ACCOUNT_SHIPPING_MANAGER, _('مسؤول الشحن')),
    ]
    account_type = models.CharField(
        _('نوع الحساب'), max_length=30,
        choices=ACCOUNT_TYPE_CHOICES, default=ACCOUNT_REGULAR
    )
    is_available = models.BooleanField(
        _('متوفر لاستقبال المهام الجديدة'),
        default=True,
        help_text=_('تُطبق على مندوب الشحن وموظف التجهيز فقط.'),
    )
    availability_updated_at = models.DateTimeField(_('آخر تحديث لحالة التوفر'), null=True, blank=True)
    availability_updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='availability_updates',
        verbose_name=_('محدّث حالة التوفر'),
    )
    avatar = models.ImageField(_('الصورة الشخصية'), upload_to='avatars/', blank=True, null=True)
    birth_date = models.DateField(_('تاريخ الميلاد'), blank=True, null=True)
    email_verified_at = models.DateTimeField(
        _('تاريخ التحقق من البريد'),
        null=True,
        blank=True,
        help_text=_('يُعبأ بعد إتمام التحقق (مثلاً OTP التسجيل).'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('ملف شخصي')
        verbose_name_plural = _('الملفات الشخصية')

    def __str__(self):
        return f"Profile of {self.user.username}"


class Address(models.Model):
    """عناوين الشحن المحفوظة"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses', verbose_name=_('المستخدم'))
    title = models.CharField(_('عنوان العنوان'), max_length=100, help_text='مثال: المنزل، العمل، منزل الوالدين')
    full_name = models.CharField(_('الاسم الكامل'), max_length=200)
    phone = models.CharField(_('رقم الجوال'), max_length=20)
    city = models.CharField(_('المدينة'), max_length=100)
    district = models.CharField(_('الحي'), max_length=100)
    street = models.CharField(_('الشارع'), max_length=200)
    building_number = models.CharField(_('رقم المبنى'), max_length=50, blank=True)
    additional_info = models.TextField(_('معلومات إضافية'), blank=True, help_text='علامات مميزة، تعليمات التوصيل')
    is_default = models.BooleanField(_('عنوان افتراضي'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('عنوان')
        verbose_name_plural = _('العناوين')
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.username}"

    def save(self, *args, **kwargs):
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def full_address(self):
        parts = [self.street, self.district, self.city]
        if self.building_number:
            parts.insert(0, f"مبنى {self.building_number}")
        return "، ".join(parts)


class Review(models.Model):
    """تقييم ومراجعة المنتج"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews', verbose_name=_('المنتج'))
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews', verbose_name=_('المستخدم'))
    rating = models.PositiveSmallIntegerField(_('التقييم'), choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField(_('التعليق'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('تقييم')
        verbose_name_plural = _('التقييمات')
        unique_together = ('product', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.product.name_ar} ({self.rating}★)"


class ContactMessage(models.Model):
    """رسائل اتصل بنا"""
    name = models.CharField(_('الاسم'), max_length=150)
    phone = models.CharField(_('رقم الجوال'), max_length=20, default='')
    email = models.EmailField(_('البريد الإلكتروني'))
    subject = models.CharField(_('الموضوع'), max_length=200)
    message = models.TextField(_('الرسالة'))
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(_('تمت القراءة'), default=False)

    class Meta:
        verbose_name = _('رسالة اتصل بنا')
        verbose_name_plural = _('رسائل اتصل بنا')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} - {self.email}"


class SupportThread(models.Model):
    """محادثة خدمة العملاء (عميل/موظف) مع حالة انتظار/نهاية وأرشفة."""

    STATUS_WAITING = 'waiting_for_staff'
    STATUS_ACTIVE = 'active'
    STATUS_ENDED = 'ended'

    STATUS_CHOICES = [
        (STATUS_WAITING, _('بانتظار ممثل خدمة العملاء')),
        (STATUS_ACTIVE, _('نشطة')),
        (STATUS_ENDED, _('منتهية')),
    ]

    customer_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_threads',
        verbose_name=_('العميل (مسجل)'),
    )
    guest_phone = models.CharField(
        _('رقم الجوال (للضيف)'), max_length=20, blank=True, default=''
    )

    status = models.CharField(
        _('حالة المحادثة'),
        max_length=40,
        choices=STATUS_CHOICES,
        default=STATUS_WAITING,
        db_index=True,
    )

    # إسناد موظف (لتقييد ظهور المحادثة على الموظف)
    assigned_staff = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_threads',
        verbose_name=_('الموظف المكلف'),
        db_index=True,
    )
    claimed_at = models.DateTimeField(_('وقت استلام المحادثة'), null=True, blank=True, db_index=True)

    ended_at = models.DateTimeField(_('وقت الإنهاء'), null=True, blank=True)
    ended_by_type = models.CharField(
        _('من أنهى'),
        max_length=20,
        blank=True,
        default='',
        help_text=_('customer|staff|system'),
    )

    last_customer_message_at = models.DateTimeField(
        _('آخر رسالة من العميل'), null=True, blank=True, db_index=True
    )
    last_staff_message_at = models.DateTimeField(
        _('آخر رسالة من الموظف'), null=True, blank=True, db_index=True
    )
    warning_sent_at = models.DateTimeField(_('وقت التنبيه'), null=True, blank=True)

    is_archived = models.BooleanField(_('مؤرشف'), default=False, db_index=True)
    archived_at = models.DateTimeField(_('وقت الأرشفة'), null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('محادثة خدمة العملاء')
        verbose_name_plural = _('محادثات خدمة العملاء')
        indexes = [
            models.Index(fields=['status', 'is_archived']),
        ]

    def __str__(self):
        who = self.customer_user.username if self.customer_user_id else (self.guest_phone or '-')
        return f"محادثة خدمة العملاء - {who}"

    @property
    def customer_display(self):
        return self.customer_user.username if self.customer_user_id else self.guest_phone


class SupportMessage(models.Model):
    """رسالة داخل محادثة خدمة العملاء."""

    SENDER_CUSTOMER = 'customer'
    SENDER_STAFF = 'staff'
    SENDER_SYSTEM = 'system'

    SENDER_CHOICES = [
        (SENDER_CUSTOMER, _('عميل')),
        (SENDER_STAFF, _('موظف')),
        (SENDER_SYSTEM, _('نظام')),
    ]

    thread = models.ForeignKey(
        SupportThread,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name=_('المحادثة'),
        db_index=True,
    )
    sender_type = models.CharField(_('المرسل'), max_length=20, choices=SENDER_CHOICES, default=SENDER_CUSTOMER)
    staff_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_messages',
        verbose_name=_('الموظف'),
    )
    text = models.TextField(_('النص'), blank=True)
    image = models.ImageField(_('صورة مرفقة'), upload_to='support_chat/', null=True, blank=True)
    metadata = models.JSONField(_('بيانات إضافية'), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('رسالة خدمة العملاء')
        verbose_name_plural = _('رسائل خدمة العملاء')
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['thread', 'created_at']),
        ]

    def __str__(self):
        sender_map = {
            self.SENDER_CUSTOMER: 'العميل',
            self.SENDER_STAFF: 'الموظف',
            self.SENDER_SYSTEM: 'النظام',
        }
        return f"رسالة ({sender_map.get(self.sender_type, 'رسالة')})"


class SupportCustomerMessageRead(models.Model):
    """تأكيد قراءة رسالة عميل من المكلف — مطلوب قبل الإرسال."""

    message = models.ForeignKey(
        SupportMessage,
        on_delete=models.CASCADE,
        related_name='customer_reads',
        verbose_name=_('الرسالة'),
        db_index=True,
    )
    reader = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='support_customer_message_reads',
        verbose_name=_('القارئ'),
        db_index=True,
    )
    read_at = models.DateTimeField(_('وقت القراءة'), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('قراءة رسالة عميل')
        verbose_name_plural = _('قراءات رسائل العملاء')
        constraints = [
            models.UniqueConstraint(fields=['message', 'reader'], name='uniq_support_customer_msg_read_reader'),
        ]

    def __str__(self):
        return f"Read #{self.message_id} by {self.reader_id}"


class SupportThreadAuditEvent(models.Model):
    """سجل إشراف زمني لمحادثات خدمة العملاء."""

    EVENT_THREAD_CLAIMED = 'thread_claimed'
    EVENT_MESSAGES_MARKED_READ = 'customer_messages_marked_read'
    EVENT_THREAD_ENDED_STAFF = 'thread_ended_staff'

    EVENT_CHOICES = [
        (EVENT_THREAD_CLAIMED, _('استلام المحادثة')),
        (EVENT_MESSAGES_MARKED_READ, _('تأكيد قراءة رسائل العميل')),
        (EVENT_THREAD_ENDED_STAFF, _('إنهاء من الموظف')),
    ]

    thread = models.ForeignKey(
        SupportThread,
        on_delete=models.CASCADE,
        related_name='audit_events',
        verbose_name=_('المحادثة'),
        db_index=True,
    )
    event_type = models.CharField(_('نوع الحدث'), max_length=60, choices=EVENT_CHOICES, db_index=True)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_thread_audit_actions',
        verbose_name=_('من قام بالإجراء'),
    )
    payload = models.JSONField(_('تفاصيل'), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('حدث إشراف محادثة')
        verbose_name_plural = _('أحداث الإشراف على المحادثات')
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.thread_id} {self.event_type}"


class InternalSupportThread(models.Model):
    """محادثة داخلية بين موظف تشغيل ومسؤول القسم (شحن/مستودع)."""
    DEPT_SHIPPING = 'shipping'
    DEPT_WAREHOUSE = 'warehouse'
    DEPT_CHOICES = [
        (DEPT_SHIPPING, _('الشحن')),
        (DEPT_WAREHOUSE, _('المستودع')),
    ]

    STATUS_WAITING = 'waiting_manager'
    STATUS_ACTIVE = 'active'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_WAITING, _('بانتظار مسؤول القسم')),
        (STATUS_ACTIVE, _('نشطة')),
        (STATUS_CLOSED, _('مغلقة')),
    ]

    department = models.CharField(_('القسم'), max_length=20, choices=DEPT_CHOICES, db_index=True)
    staff_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='internal_support_threads_as_staff', verbose_name=_('الموظف')
    )
    manager_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='internal_support_threads_as_manager', verbose_name=_('المسؤول')
    )
    status = models.CharField(_('الحالة'), max_length=30, choices=STATUS_CHOICES, default=STATUS_WAITING, db_index=True)
    last_staff_message_at = models.DateTimeField(_('آخر رسالة موظف'), null=True, blank=True, db_index=True)
    last_manager_message_at = models.DateTimeField(_('آخر رسالة مسؤول'), null=True, blank=True, db_index=True)
    waiting_notice_sent_at = models.DateTimeField(_('وقت إرسال رسالة الانتظار'), null=True, blank=True)
    closed_at = models.DateTimeField(_('وقت الإغلاق'), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('محادثة داخلية')
        verbose_name_plural = _('المحادثات الداخلية')
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['department', 'status']),
            models.Index(fields=['staff_user', 'status']),
            models.Index(fields=['manager_user', 'status']),
        ]

    def __str__(self):
        return f"{self.get_department_display()} - {self.staff_user.username}"


class InternalSupportMessage(models.Model):
    """رسالة داخل محادثة داخلية تشغيلية."""
    SENDER_STAFF = 'staff'
    SENDER_MANAGER = 'manager'
    SENDER_SYSTEM = 'system'
    SENDER_CHOICES = [
        (SENDER_STAFF, _('الموظف')),
        (SENDER_MANAGER, _('المسؤول')),
        (SENDER_SYSTEM, _('النظام')),
    ]

    thread = models.ForeignKey(
        InternalSupportThread, on_delete=models.CASCADE, related_name='messages', verbose_name=_('المحادثة')
    )
    sender_type = models.CharField(_('المرسل'), max_length=20, choices=SENDER_CHOICES, default=SENDER_STAFF)
    sender_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='internal_support_messages', verbose_name=_('المستخدم')
    )
    text = models.TextField(_('النص'), blank=True)
    image = models.ImageField(_('صورة مرفقة'), upload_to='internal_support/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('رسالة داخلية')
        verbose_name_plural = _('الرسائل الداخلية')
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['thread', 'created_at']),
        ]

    def __str__(self):
        return f"InternalMessage #{self.id}"


class EmailOTP(models.Model):
    """رمز التحقق من البريد الإلكتروني عند التسجيل"""
    email = models.EmailField(_('البريد الإلكتروني'))
    code = models.CharField(_('رمز التحقق'), max_length=6)
    username = models.CharField(_('اسم المستخدم'), max_length=150)
    phone = models.CharField(_('رقم الجوال'), max_length=20, blank=True)
    password_hash = models.CharField(_('كلمة المرور المشفرة'), max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(_('تم التحقق'), default=False)

    class Meta:
        verbose_name = _('رمز التحقق')
        verbose_name_plural = _('رموز التحقق')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} - {self.code}"

    def is_expired(self):
        """هل انتهت صلاحية الرمز؟ (15 دقيقة)"""
        from datetime import timedelta

        from django.utils import timezone
        return timezone.now() > self.created_at + timedelta(minutes=15)


class PasswordResetOTP(models.Model):
    """OTP لإعادة تعيين كلمة المرور عبر البريد (وضع اختبار: يظهر أيضاً في التيرمنال)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_otps', verbose_name=_('المستخدم'))
    email = models.EmailField(_('البريد الإلكتروني'))
    code = models.CharField(_('رمز التحقق'), max_length=6, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('تاريخ الإنشاء'))
    expires_at = models.DateTimeField(verbose_name=_('ينتهي في'))
    is_used = models.BooleanField(_('تم استخدامه'), default=False)

    class Meta:
        verbose_name = _('رمز إعادة تعيين كلمة المرور')
        verbose_name_plural = _('رموز إعادة تعيين كلمة المرور')
        ordering = ['-created_at']

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at


class Return(models.Model):
    """طلب إرجاع منتجات"""

    # ── حالات المرتجع (مسار واضح بلا تخطٍّ) ────────────────────────────
    STATUS_REQUESTED  = 'requested'
    STATUS_REVIEWING  = 'reviewing'
    STATUS_APPROVED   = 'approved'
    STATUS_REJECTED   = 'rejected'
    STATUS_RECEIVED   = 'received'
    STATUS_COMPLETED  = 'completed'
    STATUS_CHOICES = [
        (STATUS_REQUESTED, _('مقدَّم بانتظار المراجعة')),
        (STATUS_REVIEWING, _('قيد المراجعة')),
        (STATUS_APPROVED,  _('موافق عليه')),
        (STATUS_REJECTED,  _('مرفوض')),
        (STATUS_RECEIVED,  _('تم استلام المنتج')),
        (STATUS_COMPLETED, _('مكتمل — تم الاسترداد')),
    ]

    # الانتقالات المسموحة
    ALLOWED_TRANSITIONS = {
        STATUS_REQUESTED: [STATUS_REVIEWING, STATUS_REJECTED],
        STATUS_REVIEWING: [STATUS_APPROVED, STATUS_REJECTED],
        STATUS_APPROVED:  [STATUS_RECEIVED],
        STATUS_REJECTED:  [],
        STATUS_RECEIVED:  [STATUS_COMPLETED],
        STATUS_COMPLETED: [],
    }

    # ── حالة الاسترداد المالي ────────────────────────────────────────────
    REFUND_NOT_REQUIRED = 'not_required'
    REFUND_PENDING      = 'pending'
    REFUND_COMPLETED    = 'completed'
    REFUND_PARTIAL      = 'partial'
    REFUND_STATUS_CHOICES = [
        (REFUND_NOT_REQUIRED, _('غير مطلوب')),
        (REFUND_PENDING,      _('في انتظار الاسترداد')),
        (REFUND_COMPLETED,    _('تم الاسترداد')),
        (REFUND_PARTIAL,      _('استرداد جزئي')),
    ]

    # ── حالة إعادة المخزون ──────────────────────────────────────────────
    STOCK_PENDING   = 'pending'
    STOCK_RESTOCKED = 'restocked'
    STOCK_DAMAGED   = 'damaged'
    STOCK_STATUS_CHOICES = [
        (STOCK_PENDING,   _('لم يُعَد للمخزون')),
        (STOCK_RESTOCKED, _('أُعيد للمخزون')),
        (STOCK_DAMAGED,   _('تالف — لن يُعاد')),
    ]

    # ── أسباب الإرجاع ───────────────────────────────────────────────────
    REASON_DEFECTIVE        = 'defective'
    REASON_WRONG_ITEM       = 'wrong_item'
    REASON_NOT_AS_DESCRIBED = 'not_as_described'
    REASON_CHANGED_MIND     = 'changed_mind'
    REASON_OTHER            = 'other'
    REASON_CHOICES = [
        (REASON_DEFECTIVE,        _('منتج معيب')),
        (REASON_WRONG_ITEM,       _('منتج خاطئ')),
        (REASON_NOT_AS_DESCRIBED, _('لا يطابق الوصف')),
        (REASON_CHANGED_MIND,     _('تغيير الرأي')),
        (REASON_OTHER,            _('سبب آخر')),
    ]

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='returns',
        verbose_name=_('الطلب الأصلي')
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='returns', verbose_name=_('المستخدم')
    )
    status = models.CharField(
        _('حالة المرتجع'), max_length=20,
        choices=STATUS_CHOICES, default=STATUS_REQUESTED
    )
    refund_status = models.CharField(
        _('حالة الاسترداد'), max_length=20,
        choices=REFUND_STATUS_CHOICES, default=REFUND_PENDING
    )
    stock_status = models.CharField(
        _('حالة المخزون'), max_length=20,
        choices=STOCK_STATUS_CHOICES, default=STOCK_PENDING
    )
    reason = models.CharField(
        _('سبب الإرجاع'), max_length=30, choices=REASON_CHOICES, default=REASON_OTHER
    )
    reason_details = models.TextField(_('تفاصيل السبب'), blank=True)
    admin_notes    = models.TextField(_('ملاحظات الإدارة'), blank=True)
    refund_amount  = models.DecimalField(
        _('مبلغ الاسترجاع'), max_digits=10, decimal_places=2, default=0
    )
    created_at   = models.DateTimeField(auto_now_add=True, verbose_name=_('تاريخ الطلب'))
    updated_at   = models.DateTimeField(auto_now=True,     verbose_name=_('آخر تحديث'))
    completed_at = models.DateTimeField(_('تاريخ الإكمال'), null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('مرتجع')
        verbose_name_plural = _('المرتجعات')

    def __str__(self):
        return f"#{self.id} - طلب #{self.order.id} - {self.get_status_display()}"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    def get_allowed_next_statuses(self):
        return self.ALLOWED_TRANSITIONS.get(self.status, [])

    @property
    def can_be_approved(self):
        return self.status in [self.STATUS_REQUESTED, self.STATUS_REVIEWING]

    @property
    def can_be_rejected(self):
        return self.status in [self.STATUS_REQUESTED, self.STATUS_REVIEWING]

    def approve_and_restock(self):
        """للتوافق مع الكود القديم — يستدعي المحرك الجديد"""
        from store.return_engine import advance_return
        try:
            advance_return(self, self.STATUS_APPROVED)
            return True
        except Exception:
            return False


class ReturnItem(models.Model):
    """عنصر في المرتجع"""
    return_request = models.ForeignKey(
        Return, on_delete=models.CASCADE, related_name='items',
        verbose_name=_('طلب المرتجع')
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name=_('المنتج')
    )
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='return_items', verbose_name=_('نسخة المنتج')
    )
    quantity = models.PositiveIntegerField(_('الكمية المرتجعة'), default=1)
    price_at_purchase = models.DecimalField(
        _('السعر عند الشراء'), max_digits=10, decimal_places=2
    )
    condition = models.CharField(
        _('حالة المنتج'), max_length=100, blank=True,
        help_text='حالة المنتج عند الإرجاع'
    )
    product_name_snapshot = models.CharField(_('اسم المنتج عند المرتجع'), max_length=250, blank=True)
    product_sku_snapshot = models.CharField(_('SKU المنتج عند المرتجع'), max_length=120, blank=True)
    variant_label_snapshot = models.CharField(_('وصف النسخة عند المرتجع'), max_length=200, blank=True)

    class Meta:
        verbose_name = _('عنصر مرتجع')
        verbose_name_plural = _('عناصر المرتجع')

    def __str__(self):
        sku = (self.product.sku if self.product_id else self.product_sku_snapshot) or ''
        return f"{sku} × {self.quantity}"

    @property
    def display_product_name(self):
        if self.product_id:
            return self.product.name_ar
        return self.product_name_snapshot or ''

    @property
    def display_product_sku(self):
        if self.product_id and self.product:
            return self.product.sku or ''
        return self.product_sku_snapshot or ''

    @property
    def subtotal(self):
        """المبلغ الإجمالي لهذا العنصر"""
        return self.quantity * self.price_at_purchase


class ReturnStatusHistory(models.Model):
    """سجل زمني لتغييرات حالة طلبات المرتجع"""
    return_request = models.ForeignKey(
        Return, on_delete=models.CASCADE,
        related_name='status_history', verbose_name=_('طلب المرتجع')
    )
    old_status  = models.CharField(_('الحالة السابقة'), max_length=30, blank=True)
    new_status  = models.CharField(_('الحالة الجديدة'), max_length=30)
    changed_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='return_changes', verbose_name=_('بواسطة')
    )
    is_automatic = models.BooleanField(_('تلقائي'), default=False)
    note         = models.TextField(_('ملاحظة'), blank=True)
    created_at   = models.DateTimeField(auto_now_add=True, verbose_name=_('وقت التغيير'))

    class Meta:
        ordering = ['created_at']
        verbose_name = _('سجل حالة المرتجع')
        verbose_name_plural = _('سجلات حالات المرتجعات')

    def __str__(self):
        return f"مرتجع #{self.return_request.id}: {self.old_status} → {self.new_status}"


class ManageSeenMarker(models.Model):
    """
    يُسجّل أن المسؤول اطّلع على صف (قائمة/تفاصيل) لعنصر في لوحة الإدارة.
    المفتاح بصيغة: order:12 أو user:5 أو return_request:3 ...
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='manage_seen_markers',
        verbose_name=_('المسؤول'),
    )
    key = models.CharField(_('المفتاح'), max_length=120, db_index=True)
    seen_at = models.DateTimeField(_('وقت الاطلاع'), default=timezone.now)

    class Meta:
        verbose_name = _('اطلاع مسؤول')
        verbose_name_plural = _('اطلاعات المسؤولين')
        constraints = [
            models.UniqueConstraint(fields=['user', 'key'], name='unique_manage_seen_user_key'),
        ]

    def __str__(self):
        return f"{self.user_id} → {self.key}"
