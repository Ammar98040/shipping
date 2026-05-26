"""
Django Admin: إدارة الخانات، الرفوف، الأصناف، المنتجات، الطلبات، المرتجعات.
عربي فقط.
"""
from django.contrib import admin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import (
    Category,
    Compartment,
    Coupon,
    CouponRedemption,
    Order,
    OrderItem,
    Product,
    Promotion,
    Return,
    ReturnItem,
    Shelf,
    ShippingWaybill,
)


@admin.register(Compartment)
class CompartmentAdmin(admin.ModelAdmin):
    list_display = ('name_ar', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    search_fields = ('name_ar',)
    ordering = ('order',)


class ShelfInline(admin.TabularInline):
    model = Shelf
    extra = 0
    fields = ('name_ar', 'order', 'is_active')


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = ('name_ar', 'compartment', 'order', 'is_active')
    list_filter = ('compartment',)
    list_editable = ('order', 'is_active')
    search_fields = ('name_ar',)
    ordering = ('compartment', 'order')
    raw_id_fields = ('compartment',)


class CategoryInline(admin.TabularInline):
    model = Category
    extra = 0
    fields = ('name_ar', 'order', 'is_active')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name_ar', 'shelf', 'order', 'is_active')
    list_filter = ('shelf', 'shelf__compartment')
    list_editable = ('order', 'is_active')
    search_fields = ('name_ar',)
    ordering = ('shelf', 'order')
    raw_id_fields = ('shelf',)


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0
    fields = ('sku', 'name_ar', 'price', 'stock', 'is_active')
    readonly_fields = ('sku',)
    show_change_link = True


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name_ar', 'category', 'price', 'stock', 'is_active', 'updated_at')
    list_filter = ('category', 'category__shelf__compartment')
    list_editable = ('price', 'stock', 'is_active')
    search_fields = ('name_ar', 'sku')
    ordering = ('category', 'order')
    raw_id_fields = ('category',)
    date_hierarchy = 'updated_at'
    readonly_fields = ('sku', 'created_at', 'updated_at')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price', 'subtotal_display')

    def subtotal_display(self, obj):
        return obj.subtotal if obj.pk else '-'
    subtotal_display.short_description = _('المجموع')


class ShippingWaybillInline(admin.StackedInline):
    model = ShippingWaybill
    extra = 0
    max_num = 1
    can_delete = False
    fk_name = 'order'
    verbose_name = _('بوليصة الشحن')
    verbose_name_plural = _('بوليصة الشحن')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer_name', 'customer_phone', 'status', 'total_display', 'created_at')
    list_filter = ('status',)
    list_editable = ('status',)
    search_fields = ('customer_name', 'customer_phone', 'customer_email')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [OrderItemInline, ShippingWaybillInline]
    date_hierarchy = 'created_at'

    def total_display(self, obj):
        return obj.total if obj.pk else '-'
    total_display.short_description = _('المجموع')


@admin.register(ShippingWaybill)
class ShippingWaybillAdmin(admin.ModelAdmin):
    list_display = ('waybill_number', 'order', 'linked_internal_code', 'created_at', 'created_by')
    list_filter = ('created_at',)
    search_fields = ('waybill_number', 'barcode_value', 'linked_internal_code', 'order__id')
    raw_id_fields = ('order', 'shipment', 'created_by', 'updated_by')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product', 'quantity', 'price', 'subtotal_display')
    list_filter = ('order',)
    raw_id_fields = ('order', 'product')

    def subtotal_display(self, obj):
        return obj.subtotal
    subtotal_display.short_description = _('المجموع')


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    extra = 0
    fields = ('product', 'quantity', 'price_at_purchase', 'condition', 'subtotal_display')
    readonly_fields = ('subtotal_display',)
    raw_id_fields = ('product',)

    def subtotal_display(self, obj):
        return obj.subtotal if obj.pk else '-'
    subtotal_display.short_description = _('المجموع')


@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'order', 'user_display', 'status', 'reason',
        'total_items', 'refund_amount', 'created_at'
    )
    list_filter = ('status', 'reason', 'created_at')
    list_editable = ('status',)
    search_fields = ('order__id', 'order__customer_name', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    inlines = [ReturnItemInline]
    date_hierarchy = 'created_at'
    fieldsets = (
        (_('معلومات أساسية'), {
            'fields': ('order', 'user', 'status')
        }),
        (_('سبب الإرجاع'), {
            'fields': ('reason', 'reason_details')
        }),
        (_('معلومات مالية'), {
            'fields': ('refund_amount',)
        }),
        (_('ملاحظات'), {
            'fields': ('admin_notes',)
        }),
        (_('التواريخ'), {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    actions = ['approve_returns', 'reject_returns', 'complete_returns']

    def user_display(self, obj):
        return obj.user.username if obj.user else obj.order.customer_name
    user_display.short_description = _('العميل')

    def approve_returns(self, request, queryset):
        """الموافقة على المرتجعات وإرجاع الكميات للمخزون"""
        approved_count = 0
        for return_obj in queryset.filter(status=Return.STATUS_PENDING):
            if return_obj.approve_and_restock():
                approved_count += 1

        self.message_user(
            request,
            f'تمت الموافقة على {approved_count} مرتجع وإرجاع الكميات للمخزون'
        )
    approve_returns.short_description = _('✅ الموافقة وإرجاع للمخزون')

    def reject_returns(self, request, queryset):
        """رفض المرتجعات"""
        count = queryset.filter(status=Return.STATUS_PENDING).update(status=Return.STATUS_REJECTED)
        self.message_user(request, f'تم رفض {count} مرتجع')
    reject_returns.short_description = _('❌ رفض المرتجعات')

    def complete_returns(self, request, queryset):
        """تمييز المرتجعات كمكتملة"""
        count = queryset.filter(status=Return.STATUS_APPROVED).update(
            status=Return.STATUS_COMPLETED,
            completed_at=timezone.now()
        )
        self.message_user(request, f'تم تمييز {count} مرتجع كمكتمل')
    complete_returns.short_description = _('🔄 تمييز كمكتمل')


@admin.register(ReturnItem)
class ReturnItemAdmin(admin.ModelAdmin):
    list_display = ('return_request', 'product', 'quantity', 'price_at_purchase', 'subtotal_display')
    list_filter = ('return_request__status',)
    search_fields = ('product__name_ar', 'product__sku')
    raw_id_fields = ('return_request', 'product')

    def subtotal_display(self, obj):
        return obj.subtotal
    subtotal_display.short_description = _('المجموع')


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_type', 'discount_value', 'is_active', 'start_at', 'end_at', 'min_quantity')
    list_filter = ('is_active', 'discount_type')
    search_fields = ('name', 'description')
    filter_horizontal = ('products', 'variants')
    ordering = ('-updated_at', 'id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'is_active', 'discount_type', 'discount_value', 'max_uses_total', 'created_at')
    list_filter = ('is_active', 'discount_type')
    search_fields = ('code',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ('coupon', 'user', 'guest_phone', 'redeemed_at')
    list_filter = ('coupon', 'redeemed_at')
    search_fields = ('coupon__code', 'guest_phone', 'user__username')
    raw_id_fields = ('coupon', 'user')
