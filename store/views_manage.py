"""
لوحة الإدارة — نظامك فقط، غير مربوطة بإدارة Django الافتراضية.
تسجيل دخول، لوحة تحكم، وإدارة الخانات / الرفوف / الأصناف / المنتجات / الطلبات.
"""
import csv
import json
import re
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Count, F, Max, Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    CategoryForm,
    CompartmentForm,
    CouponForm,
    ProductForm,
    PromotionForm,
    ShelfForm,
)
from .forms_profile import UserProfileForm
from .manage_decorators import _staff_required, _superuser_required
from .models import (
    Address,
    CartShare,
    CartShareItem,
    Category,
    Compartment,
    ContactMessage,
    Coupon,
    LabelCode,
    Order,
    OrderItem,
    Product,
    ProductGalleryImage,
    ProductVariant,
    ProductVariantImage,
    Promotion,
    Return,
    ReturnItem,
    Shelf,
    Shipment,
    ShippingWaybill,
    UserProfile,
    Wishlist,
)
from .money_display import format_sar_amount
from .revenue_stats import get_revenue_stats_formatted
from .views_manage_auth import (
    forgot_password,
    forgot_password_new_password,
    forgot_password_otp,
    manage_login,
    manage_logout,
)
from .views_manage_backup import site_backup, site_full_wipe
from .views_manage_notifications import (
    manage_mark_seen_bulk_json,
    manage_mark_seen_json,
    manage_notifications_json,
)
from .views_manage_support import (
    support_agent_detail,
    support_archive_agent,
    support_archive_thread,
    support_portal,
    support_portal_signature_json,
    support_team_accounts,
    support_thread_claim_json,
    support_thread_detail,
    support_thread_end_json,
    support_thread_mark_read_json,
    support_thread_messages_json,
    support_thread_send_json,
    support_toggle_availability,
)


def _public_absolute_url(request, path: str) -> str:
    from django.conf import settings

    base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


@_staff_required
def dashboard(request):
    stats = {
        'compartments': Compartment.objects.count(),
        'shelves': Shelf.objects.count(),
        'categories': Category.objects.count(),
        'products': Product.objects.count(),
        'orders': Order.objects.count(),
        'orders_pending': Order.objects.filter(status=Order.STATUS_PENDING).count(),
    }
    recent_orders = Order.objects.all()[:10]
    return render(request, 'manage/dashboard.html', {'stats': stats, 'recent_orders': recent_orders})


# ——— الخانات ———
@_staff_required
def compartment_list(request):
    items_list = (
        Compartment.objects.all()
        .annotate(shelves_count=Count('shelves', distinct=True))
        .order_by('order', 'id')
    )
    paginator = Paginator(items_list, 20)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_string = query_params.urlencode()
    return render(request, 'manage/compartment_list.html', {
        'items': items,
        'query_string': query_string,
    })


@_staff_required
def compartment_add(request):
    form = CompartmentForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        messages.success(request, _('تمت إضافة الخانة.'))
        return redirect('manage:compartment_list')
    return render(request, 'manage/compartment_form.html', {'form': form, 'title': _('إضافة خانة')})


@_staff_required
def compartment_edit(request, pk):
    obj = get_object_or_404(Compartment, pk=pk)
    form = CompartmentForm(request.POST or None, request.FILES or None, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم تحديث الخانة.'))
        return redirect('manage:compartment_list')
    return render(request, 'manage/compartment_form.html', {'form': form, 'title': _('تعديل خانة'), 'obj': obj})


@_staff_required
def compartment_delete(request, pk):
    obj = get_object_or_404(Compartment, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, _('تم حذف الخانة.'))
        return redirect('manage:compartment_list')
    return render(request, 'manage/confirm_delete.html', {'obj': obj, 'back_url': 'manage:compartment_list', 'name': obj.name_ar})


# ——— الرفوف ———
@_staff_required
def shelf_list(request):
    items = (
        Shelf.objects.select_related('compartment')
        .annotate(categories_count=Count('categories', distinct=True))
    )

    # فلتر بالخانة
    compartment_id = request.GET.get('compartment')
    if compartment_id:
        items = items.filter(compartment_id=compartment_id)

    # بحث بالاسم
    search = request.GET.get('search', '').strip()
    if search:
        items = items.filter(name_ar__icontains=search)

    items = items.order_by('compartment__order', 'compartment__id', 'order', 'id')

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    compartments = Compartment.objects.all().order_by('order', 'id')
    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/shelf_list.html', {
        'items': items,
        'compartments': compartments,
        'current_compartment': compartment_id,
        'search_query': search,
        'query_string': q.urlencode(),
    })


@_staff_required
def shelf_add(request):
    form = ShelfForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        messages.success(request, _('تمت إضافة الرف.'))
        return redirect('manage:shelf_list')
    return render(request, 'manage/shelf_form.html', {'form': form, 'title': _('إضافة رف')})


@_staff_required
def shelf_edit(request, pk):
    obj = get_object_or_404(Shelf, pk=pk)
    form = ShelfForm(request.POST or None, request.FILES or None, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم تحديث الرف.'))
        return redirect('manage:shelf_list')
    return render(request, 'manage/shelf_form.html', {'form': form, 'title': _('تعديل رف'), 'obj': obj})


@_staff_required
def shelf_delete(request, pk):
    obj = get_object_or_404(Shelf, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, _('تم حذف الرف.'))
        return redirect('manage:shelf_list')
    return render(request, 'manage/confirm_delete.html', {'obj': obj, 'back_url': 'manage:shelf_list', 'name': obj.name_ar})


# ——— الأصناف ———
@_staff_required
def category_list(request):
    items = (
        Category.objects.select_related('shelf', 'shelf__compartment')
        .annotate(products_count=Count('products', distinct=True))
    )

    # فلتر بالخانة
    compartment_id = request.GET.get('compartment')
    if compartment_id:
        items = items.filter(shelf__compartment_id=compartment_id)

    # فلتر بالرف
    shelf_id = request.GET.get('shelf')
    if shelf_id:
        items = items.filter(shelf_id=shelf_id)

    # بحث
    search = request.GET.get('search', '').strip()
    if search:
        items = items.filter(name_ar__icontains=search)

    items = items.order_by(
        'shelf__compartment__order',
        'shelf__compartment__id',
        'shelf__order',
        'shelf__id',
        'order',
        'id',
    )

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    compartments = Compartment.objects.all().order_by('order', 'id')
    shelves = Shelf.objects.select_related('compartment').all().order_by('compartment__order', 'compartment__id', 'order', 'id')
    if compartment_id:
        shelves = shelves.filter(compartment_id=compartment_id)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/category_list.html', {
        'items': items,
        'compartments': compartments,
        'shelves': shelves,
        'current_compartment': compartment_id,
        'current_shelf': shelf_id,
        'search_query': search,
        'query_string': q.urlencode(),
    })


@_staff_required
def category_add(request):
    form = CategoryForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        messages.success(request, _('تمت إضافة الصنف.'))
        return redirect('manage:category_list')
    return render(request, 'manage/category_form.html', {'form': form, 'title': _('إضافة صنف')})


@_staff_required
def category_edit(request, pk):
    obj = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, request.FILES or None, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم تحديث الصنف.'))
        return redirect('manage:category_list')
    return render(request, 'manage/category_form.html', {'form': form, 'title': _('تعديل صنف'), 'obj': obj})


@_staff_required
def category_delete(request, pk):
    obj = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, _('تم حذف الصنف.'))
        return redirect('manage:category_list')
    return render(request, 'manage/confirm_delete.html', {'obj': obj, 'back_url': 'manage:category_list', 'name': obj.name_ar})


# ——— المنتجات ———
@_staff_required
def product_list(request):
    items = (
        Product.objects.select_related('category', 'category__shelf', 'category__shelf__compartment')
        .annotate(variants_count=Count('variants', distinct=True))
    )

    # فلتر بالخانة
    compartment_id = request.GET.get('compartment')
    if compartment_id:
        items = items.filter(category__shelf__compartment_id=compartment_id)

    # فلتر بالرف
    shelf_id = request.GET.get('shelf')
    if shelf_id:
        items = items.filter(category__shelf_id=shelf_id)

    # فلتر بالصنف
    category_id = request.GET.get('category')
    if category_id:
        items = items.filter(category_id=category_id)

    # بحث
    search = request.GET.get('search', '').strip()
    if search:
        items = items.filter(name_ar__icontains=search)

    items = items.order_by(
        'category__shelf__compartment__order',
        'category__shelf__compartment__id',
        'category__shelf__order',
        'category__shelf__id',
        'category__order',
        'category__id',
        'order',
        'id',
    )

    compartments = Compartment.objects.all().order_by('order', 'id')
    shelves = Shelf.objects.select_related('compartment').all().order_by('compartment__order', 'compartment__id', 'order', 'id')
    if compartment_id:
        shelves = shelves.filter(compartment_id=compartment_id)

    categories = Category.objects.select_related('shelf', 'shelf__compartment').all().order_by(
        'shelf__compartment__order',
        'shelf__compartment__id',
        'shelf__order',
        'shelf__id',
        'order',
        'id',
    )
    if shelf_id:
        categories = categories.filter(shelf_id=shelf_id)
    elif compartment_id:
        categories = categories.filter(shelf__compartment_id=compartment_id)

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/product_list.html', {
        'items': items,
        'compartments': compartments,
        'shelves': shelves,
        'categories': categories,
        'current_compartment': compartment_id,
        'current_shelf': shelf_id,
        'current_category': category_id,
        'search_query': search,
        'query_string': q.urlencode(),
    })


@_staff_required
def product_add(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        messages.success(request, _('تمت إضافة المنتج.'))
        return redirect('manage:product_list')
    return render(request, 'manage/product_form.html', {'form': form, 'title': _('إضافة منتج')})


@_staff_required
def product_edit(request, pk):
    obj = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم تحديث المنتج.'))
        return redirect('manage:product_list')
    return render(request, 'manage/product_form.html', {'form': form, 'title': _('تعديل منتج'), 'obj': obj})


@_staff_required
def product_variants_manage(request, pk):
    product = get_object_or_404(Product, pk=pk)
    variants = product.variants.prefetch_related('images').order_by('sort_order', 'id')
    gallery_images = product.gallery_images.order_by('sort_order', 'id')

    def _next_variant_code() -> str:
        base = (product.sku or f"P{product.id}").strip()
        used_codes = set(
            ProductVariant.objects.filter(product=product)
            .values_list('code', flat=True)
        )
        max_n = 0
        pattern = re.compile(rf"^{re.escape(base)}-V(\d+)$")
        for code in used_codes:
            m = pattern.match((code or '').strip())
            if m:
                max_n = max(max_n, int(m.group(1)))
        n = max_n + 1
        while True:
            candidate = f"{base}-V{n:03d}"
            if candidate not in used_codes:
                return candidate
            n += 1

    def _normalize_color_hex(value: str) -> str:
        val = (value or '').strip()
        if not val:
            return ''
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', val):
            raise ValueError(_('قيمة HEX غير صحيحة. الصيغة المطلوبة: #RRGGBB'))
        return val.upper()

    def _parse_decimal_input(value: str):
        raw = (value or '').strip()
        if not raw:
            return None
        normalized = raw.replace('٬', '').replace(',', '.')
        trans = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
        normalized = normalized.translate(trans)
        try:
            return Decimal(normalized)
        except (InvalidOperation, ValueError):
            raise ValueError(_('الرجاء إدخال سعر صحيح.'))

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        def _ok(message, **extra):
            if is_ajax:
                payload = {'success': True, 'message': str(message), 'action': action}
                payload.update(extra)
                return JsonResponse(payload)
            messages.success(request, message)
            return redirect('manage:product_variants_manage', pk=product.pk)

        def _err(message, status=400, **extra):
            if is_ajax:
                payload = {'success': False, 'error': str(message), 'action': action}
                payload.update(extra)
                return JsonResponse(payload, status=status)
            messages.error(request, message)
            return redirect('manage:product_variants_manage', pk=product.pk)

        if action == 'add_variant':
            code = (request.POST.get('code') or '').strip()
            if not code:
                code = _next_variant_code()
            if ProductVariant.objects.filter(product=product, code=code).exists():
                return _err(_('رمز النسخة مستخدم مسبقًا لهذا المنتج.'))
            try:
                color_hex = _normalize_color_hex(request.POST.get('color_hex'))
            except ValueError as e:
                return _err(str(e))
            try:
                price_val = _parse_decimal_input(request.POST.get('price'))
            except ValueError as e:
                return _err(str(e))
            ProductVariant.objects.create(
                product=product,
                code=code,
                title=(request.POST.get('title') or '').strip(),
                color_name=(request.POST.get('color_name') or '').strip(),
                color_hex=color_hex,
                price=price_val,
                stock_quantity=max(0, int(request.POST.get('stock_quantity') or 0)),
                sort_order=max(0, int(request.POST.get('sort_order') or 0)),
                is_active=(request.POST.get('is_active') == 'on'),
            )
            return _ok(_('تمت إضافة النسخة.'), requires_refresh=True)

        variant_required_actions = {
            'update_variant',
            'duplicate_variant',
            'delete_variant',
            'set_primary_image',
            'delete_image',
            'reorder_images',
        }
        variant = None
        if action in variant_required_actions:
            variant_id = (request.POST.get('variant_id') or '').strip()
            variant = get_object_or_404(ProductVariant, pk=variant_id, product=product) if variant_id.isdigit() else None
            if not variant:
                return _err(_('تعذر تحديد النسخة المطلوبة.'))

        if action == 'update_variant':
            code = (request.POST.get('code') or '').strip()
            if not code:
                code = _next_variant_code()
            duplicate = ProductVariant.objects.filter(product=product, code=code).exclude(pk=variant.pk).exists()
            if duplicate:
                return _err(_('رمز النسخة مستخدم مسبقًا لهذا المنتج.'))
            if variant.order_items.exists() and code != variant.code:
                return _err(_('لا يمكن تعديل SKU لهذه النسخة لأنها مرتبطة بطلبات سابقة.'))
            try:
                color_hex = _normalize_color_hex(request.POST.get('color_hex'))
            except ValueError as e:
                return _err(str(e))
            variant.code = code
            variant.title = (request.POST.get('title') or '').strip()
            variant.color_name = (request.POST.get('color_name') or '').strip()
            variant.color_hex = color_hex
            try:
                variant.price = _parse_decimal_input(request.POST.get('price'))
            except ValueError as e:
                return _err(str(e))
            variant.stock_quantity = max(0, int(request.POST.get('stock_quantity') or 0))
            variant.sort_order = max(0, int(request.POST.get('sort_order') or 0))
            variant.is_active = (request.POST.get('is_active') == 'on')
            variant.save()
            file_obj = request.FILES.get('variant_image')
            if file_obj:
                variant.images.all().delete()
                new_img = ProductVariantImage.objects.create(
                    variant=variant,
                    image=file_obj,
                    sort_order=1,
                    is_primary=True,
                )
                return _ok(
                    _('تم حفظ التعديلات وصورة اللون.'),
                    variant_id=variant.id,
                    variant_image={
                        'id': new_img.id,
                        'url': request.build_absolute_uri(new_img.image.url),
                        'is_primary': True,
                    },
                )
            else:
                return _ok(_('تم حفظ التعديلات.'), variant_id=variant.id)

        if action == 'duplicate_variant':
            new_variant = ProductVariant.objects.create(
                product=product,
                code=_next_variant_code(),
                title=variant.title,
                color_name=variant.color_name,
                color_hex=variant.color_hex,
                price=variant.price,
                stock_quantity=variant.stock_quantity,
                sort_order=variant.sort_order + 1,
                is_active=variant.is_active,
            )
            for img in variant.images.all().order_by('sort_order', 'id'):
                ProductVariantImage.objects.create(
                    variant=new_variant,
                    image=img.image.name,
                    alt_text=img.alt_text,
                    sort_order=img.sort_order,
                    is_primary=img.is_primary,
                )
            return _ok(
                _('تم إنشاء نسخة لون جديدة تحت نفس المنتج (لون/صورة إضافية).'),
                requires_refresh=True,
            )

        if action == 'delete_variant':
            if variant.open_order_items_exist:
                return _err(
                    _('لا يمكن حذف النسخة لوجود طلب لم يُكتمل توصيله بعد (حتى تصبح حالة الطلب «تم التوصيل» أو «ملغي»).'),
                )
            variant_pk = variant.pk
            try:
                variant.delete()
            except ProtectedError:
                return _err(_('لا يمكن حذف النسخة لأنها مستخدمة في عمليات قائمة.'))
            return _ok(_('تم حذف النسخة.'), variant_id=variant_pk, remove_variant=True)

        if action in {'set_primary_image', 'delete_image', 'reorder_images'}:
            image_id = (request.POST.get('image_id') or '').strip()
            image_obj = (
                get_object_or_404(ProductVariantImage, pk=image_id, variant=variant)
                if image_id.isdigit() else None
            )

            if action == 'set_primary_image' and image_obj:
                variant.images.update(is_primary=False)
                image_obj.is_primary = True
                image_obj.save(update_fields=['is_primary'])
                return _ok(_('تم تعيين الصورة الرئيسية.'), variant_id=variant.id, image_id=image_obj.id)

            if action == 'delete_image' and image_obj:
                was_primary = image_obj.is_primary
                deleted_image_pk = image_obj.pk
                image_obj.delete()
                new_primary_id = None
                if was_primary:
                    new_primary = variant.images.order_by('sort_order', 'id').first()
                    if new_primary:
                        new_primary.is_primary = True
                        new_primary.save(update_fields=['is_primary'])
                        new_primary_id = new_primary.id
                return _ok(
                    _('تم حذف الصورة.'),
                    variant_id=variant.id,
                    image_id=deleted_image_pk,
                    removed_image=True,
                    removed_from='variant',
                    new_primary_id=new_primary_id,
                )

            if action == 'reorder_images':
                ordered_ids_raw = (request.POST.get('ordered_ids') or '').strip()
                if not ordered_ids_raw:
                    return _err(_('تعذر حفظ الترتيب الجديد للصور.'))
                ids = []
                for token in ordered_ids_raw.split(','):
                    token = token.strip()
                    if token.isdigit():
                        ids.append(int(token))
                valid_images = {img.id: img for img in variant.images.filter(id__in=ids)}
                order_num = 1
                for image_id in ids:
                    img = valid_images.get(image_id)
                    if not img:
                        continue
                    if img.sort_order != order_num:
                        img.sort_order = order_num
                        img.save(update_fields=['sort_order'])
                    order_num += 1
                return _ok(_('تم حفظ ترتيب الصور.'), variant_id=variant.id)

        if action == 'upload_product_gallery':
            files = request.FILES.getlist('product_gallery_images')
            if not files:
                return _err(_('لم يتم اختيار صور للرفع.'))
            start_order = (product.gallery_images.aggregate(max_order=Max('sort_order')).get('max_order') or 0) + 1
            has_primary = product.gallery_images.filter(is_primary=True).exists()
            for idx, file_obj in enumerate(files):
                ProductGalleryImage.objects.create(
                    product=product,
                    image=file_obj,
                    title=product.name_ar,
                    price=product.price,
                    stock_quantity=int(product.stock or 0),
                    sort_order=start_order + idx,
                    is_primary=(not has_primary and idx == 0),
                )
            return _ok(_('تم رفع صور معرض المنتج.'), requires_refresh=True)

        if action == 'set_primary_gallery_image':
            image_id = (request.POST.get('image_id') or '').strip()
            image_obj = get_object_or_404(ProductGalleryImage, pk=image_id, product=product)
            product.gallery_images.update(is_primary=False)
            image_obj.is_primary = True
            image_obj.save(update_fields=['is_primary'])
            return _ok(_('تم تعيين صورة المنتج الرئيسية من المعرض.'), image_id=image_obj.id)

        if action == 'delete_gallery_image':
            image_id = (request.POST.get('image_id') or '').strip()
            image_obj = get_object_or_404(ProductGalleryImage, pk=image_id, product=product)
            was_primary = image_obj.is_primary
            deleted_gallery_pk = image_obj.pk
            image_obj.delete()
            if was_primary:
                fallback = product.gallery_images.order_by('sort_order', 'id').first()
                if fallback:
                    fallback.is_primary = True
                    fallback.save(update_fields=['is_primary'])
            return _ok(
                _('تم حذف صورة المعرض.'),
                image_id=deleted_gallery_pk,
                removed_image=True,
                removed_from='gallery',
            )

        if action == 'update_gallery_meta':
            image_id = (request.POST.get('image_id') or '').strip()
            image_obj = get_object_or_404(ProductGalleryImage, pk=image_id, product=product)
            image_obj.title = (request.POST.get('title') or '').strip() or product.name_ar
            try:
                image_obj.price = _parse_decimal_input(request.POST.get('price'))
                image_obj.stock_quantity = max(0, int(request.POST.get('stock_quantity') or 0))
            except (TypeError, ValueError):
                return _err(_('الرجاء إدخال قيم صحيحة للسعر والكمية.'))
            image_obj.save(update_fields=['title', 'price', 'stock_quantity'])
            return _ok(_('تم تحديث بيانات الصورة.'), image_id=image_obj.id)

        if action == 'update_gallery_meta_bulk':
            ordered_ids_raw = (request.POST.get('ordered_ids') or '').strip()
            if ordered_ids_raw:
                ids_order = [int(t) for t in ordered_ids_raw.split(',') if t.strip().isdigit()]
                valid_order = {img.id: img for img in product.gallery_images.filter(id__in=ids_order)}
                order_num = 1
                for oid in ids_order:
                    img_o = valid_order.get(oid)
                    if not img_o:
                        continue
                    if img_o.sort_order != order_num:
                        img_o.sort_order = order_num
                        img_o.save(update_fields=['sort_order'])
                    order_num += 1
            image_ids = request.POST.getlist('gallery_image_id')
            updated = 0
            for image_id in image_ids:
                if not str(image_id).isdigit():
                    continue
                image_obj = ProductGalleryImage.objects.filter(pk=int(image_id), product=product).first()
                if not image_obj:
                    continue
                title_key = f'title_{image_obj.id}'
                price_key = f'price_{image_obj.id}'
                stock_key = f'stock_{image_obj.id}'
                try:
                    image_obj.title = (request.POST.get(title_key) or '').strip() or product.name_ar
                    image_obj.price = _parse_decimal_input(request.POST.get(price_key))
                    image_obj.stock_quantity = max(0, int(request.POST.get(stock_key) or 0))
                except (TypeError, ValueError):
                    return _err(_('تعذر حفظ بعض القيم. تأكد من السعر والكمية.'))
                image_obj.save(update_fields=['title', 'price', 'stock_quantity'])
                updated += 1
            return _ok(_('تم حفظ جميع تعديلات المعرض (%(count)s صورة).') % {'count': updated})

        if action == 'reorder_gallery_images':
            ordered_ids_raw = (request.POST.get('ordered_ids') or '').strip()
            ids = [int(t) for t in ordered_ids_raw.split(',') if t.strip().isdigit()]
            valid_images = {img.id: img for img in product.gallery_images.filter(id__in=ids)}
            order_num = 1
            for image_id in ids:
                img = valid_images.get(image_id)
                if not img:
                    continue
                if img.sort_order != order_num:
                    img.sort_order = order_num
                    img.save(update_fields=['sort_order'])
                order_num += 1
            return _ok(_('تم حفظ ترتيب معرض المنتج.'))

        return _err(_('الإجراء غير معروف.'))

    return render(request, 'manage/product_variants_manage.html', {
        'product': product,
        'variants': variants,
        'gallery_images': gallery_images,
    })


@_staff_required
def product_delete(request, pk):
    """حذف المنتج من الكتالوج: يُسمح مع الإبقاء على سجل الطلبات (SET_NULL + لقطات نصية).
    يُرفض فقط عند وجود طلب مرتبط غير مُسلَّم وغير ملغٍ — يشمل كل النسخ لأن OrderItem يشير دائماً للمنتج."""
    obj = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        blocking_orders = obj.orderitem_set.exclude(
            order__status__in=[Order.STATUS_DELIVERED, Order.STATUS_CANCELLED]
        )
        linked_variants = obj.variants.count()
        if blocking_orders.exists():
            messages.error(
                request,
                _('لا يمكن حذف المنتج لوجود طلبات لم تُكتمل بعد (حتى تصبح حالة الطلب «تم التوصيل» أو «ملغي»).'),
            )
            return redirect('manage:product_list')
        try:
            obj.delete()
        except ProtectedError:
            messages.error(
                request,
                _('لا يمكن حذف المنتج لأنه مستخدم في النظام. احذف الارتباطات أولاً (النسخ: %(variants)s).')
                % {'variants': linked_variants}
            )
            return redirect('manage:product_list')
        messages.success(request, _('تم حذف المنتج.'))
        return redirect('manage:product_list')
    return render(request, 'manage/confirm_delete.html', {'obj': obj, 'back_url': 'manage:product_list', 'name': obj.name_ar})


# ——— الطلبات ———
@_staff_required
def order_list(request):
    """قائمة الطلبات مع فلترة متقدمة وإحصائيات"""
    items = Order.objects.select_related('user').all()

    # ── فلاتر ────────────────────────────────────────────────────────
    status_filter       = request.GET.get('status', '').strip()
    pay_status_filter   = request.GET.get('pay_status', '').strip()
    customer_type_filter= request.GET.get('customer_type', '').strip()
    search_query        = request.GET.get('search', '').strip()

    if status_filter:
        items = items.filter(status=status_filter)
    if pay_status_filter:
        items = items.filter(payment_status=pay_status_filter)
    if customer_type_filter:
        items = items.filter(customer_type=customer_type_filter)
    if search_query:
        items = items.filter(
            Q(id__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query)
        )

    # ── إحصائيات ─────────────────────────────────────────────────────
    revenue = get_revenue_stats_formatted()
    stats = {
        'all':        Order.objects.count(),
        'pending':    Order.objects.filter(status=Order.STATUS_PENDING).count(),
        'confirmed':  Order.objects.filter(status=Order.STATUS_CONFIRMED).count(),
        'processing': Order.objects.filter(status=Order.STATUS_PROCESSING).count(),
        'shipped':    Order.objects.filter(status=Order.STATUS_SHIPPED).count(),
        'delivered':  Order.objects.filter(status=Order.STATUS_DELIVERED).count(),
        'cancelled':  Order.objects.filter(status=Order.STATUS_CANCELLED).count(),
        'guests':     Order.objects.filter(customer_type=Order.CUSTOMER_GUEST).count(),
        'unpaid_gateway': Order.objects.filter(
            payment_method=Order.PAYMENT_GATEWAY,
            payment_status=Order.PAY_STATUS_PENDING
        ).count(),
        **revenue,
    }

    items = items.order_by('-created_at')

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/order_list.html', {
        'items': items,
        'stats': stats,
        'current_status':        status_filter,
        'current_pay_status':    pay_status_filter,
        'current_customer_type': customer_type_filter,
        'search_query':          search_query,
        'query_string':          q.urlencode(),
        'status_choices':        Order.STATUS_CHOICES,
        'pay_status_choices':    Order.PAYMENT_STATUS_CHOICES,
        'customer_type_choices': Order.CUSTOMER_TYPE_CHOICES,
    })


# ——— نظرة شاملة ———
@_staff_required
# ========== إدارة المستخدمين ==========

@_superuser_required
def users_list(request):
    """قائمة المستخدمين العاديين فقط (غير المسؤولين)"""
    search_query = request.GET.get('search', '').strip()

    users = User.objects.filter(is_staff=False, is_superuser=False).annotate(
        orders_count=Count('orders'),
        wishlist_count=Count('wishlist')
    )

    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )

    users = users.order_by('-date_joined')

    paginator = Paginator(users, 25)
    page = request.GET.get('page', 1)
    try:
        users = paginator.page(page)
    except PageNotAnInteger:
        users = paginator.page(1)
    except EmptyPage:
        users = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/users_list.html', {
        'users': users,
        'search_query': search_query,
        'query_string': q.urlencode(),
    })


@_superuser_required
def user_detail(request, user_id):
    """تفاصيل مستخدم - مع تعديل نوع الحساب"""
    user_obj = get_object_or_404(User, pk=user_id)
    from .manage_seen_utils import mark_seen_kind_pk
    mark_seen_kind_pk(request.user, 'user', user_obj.pk)
    orders = Order.objects.filter(user=user_obj).prefetch_related('items__product')[:10]
    wishlist = Wishlist.objects.filter(user=user_obj).select_related('product')[:10]
    addresses = Address.objects.filter(user=user_obj).order_by('-is_default', '-id')[:10]

    stats = {
        'total_orders': Order.objects.filter(user=user_obj).count(),
        'wishlist_count': Wishlist.objects.filter(user=user_obj).count(),
        'total_spent': sum(order.total for order in Order.objects.filter(user=user_obj)),
    }
    profile_obj = UserProfile.objects.filter(user=user_obj).only(
        'account_type', 'is_available', 'availability_updated_at'
    ).first()
    account_type = profile_obj.account_type if profile_obj else UserProfile.ACCOUNT_REGULAR
    is_available = bool(getattr(profile_obj, 'is_available', True))
    availability_updated_at = getattr(profile_obj, 'availability_updated_at', None)

    if request.method == 'POST':
        action = request.POST.get('manage_user_action') or request.POST.get('action')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if action == 'change_role':
            new_role = request.POST.get('role')
            changed = False
            error_message = ''
            success_message = ''
            if user_obj.is_superuser and new_role != 'superuser':
                error_message = 'لا يمكن تغيير صلاحيات المدير الرئيسي'
                messages.error(request, error_message)
            elif new_role == 'regular':
                user_obj.is_staff = False
                user_obj.is_superuser = False
                user_obj.save()
                # إن كان لديه بروفايل اجعله مستخدم عادي
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_REGULAR
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم تغيير {user_obj.username} إلى مستخدم عادي'
                messages.success(request, success_message)
            elif new_role == 'staff':
                user_obj.is_staff = True
                user_obj.is_superuser = False
                user_obj.save()
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_REGULAR
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم ترقية {user_obj.username} إلى مسؤول'
                messages.success(request, success_message)
            elif new_role == 'customer_service':
                # موظف خدمة العملاء: is_staff لكنه محدود لرؤية بوابة خدمة العملاء فقط
                user_obj.is_staff = True
                user_obj.is_superuser = False
                user_obj.save()
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_CUSTOMER_SERVICE
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم تحويل {user_obj.username} إلى موظف خدمة العملاء'
                messages.success(request, success_message)
            elif new_role == 'customer_service_manager':
                # مسؤول خدمة العملاء: صلاحيات متقدمة داخل بوابة خدمة العملاء
                user_obj.is_staff = True
                user_obj.is_superuser = False
                user_obj.save()
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم تحويل {user_obj.username} إلى مسؤول خدمة العملاء'
                messages.success(request, success_message)
            elif new_role == 'courier':
                # مندوب شحن: لا يملك صلاحيات لوحة الإدارة /manage/
                user_obj.is_staff = False
                user_obj.is_superuser = False
                user_obj.save()
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_COURIER
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم تحويل {user_obj.username} إلى مندوب شحن'
                messages.success(request, success_message)
            elif new_role == 'packer':
                # موظف تجهيز: لا يملك صلاحيات لوحة الإدارة /manage/
                user_obj.is_staff = False
                user_obj.is_superuser = False
                user_obj.save()
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_PACKER
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم تحويل {user_obj.username} إلى موظف تجهيز'
                messages.success(request, success_message)
            elif new_role == 'warehouse_manager':
                user_obj.is_staff = False
                user_obj.is_superuser = False
                user_obj.save()
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_WAREHOUSE_MANAGER
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم تحويل {user_obj.username} إلى مسؤول المستودع'
                messages.success(request, success_message)
            elif new_role == 'shipping_manager':
                user_obj.is_staff = False
                user_obj.is_superuser = False
                user_obj.save()
                profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                profile.account_type = UserProfile.ACCOUNT_SHIPPING_MANAGER
                profile.save(update_fields=['account_type'])
                changed = True
                success_message = f'تم تحويل {user_obj.username} إلى مسؤول الشحن'
                messages.success(request, success_message)
            elif new_role == 'superuser':
                if not request.user.is_superuser:
                    error_message = 'فقط المدير الرئيسي يمكنه منح صلاحيات المدير'
                    messages.error(request, error_message)
                else:
                    user_obj.is_staff = True
                    user_obj.is_superuser = True
                    user_obj.save()
                    profile, _ = UserProfile.objects.get_or_create(user=user_obj)
                    profile.account_type = UserProfile.ACCOUNT_REGULAR
                    profile.save(update_fields=['account_type'])
                    changed = True
                    success_message = f'تم ترقية {user_obj.username} إلى مدير رئيسي'
                    messages.success(request, success_message)

            if is_ajax:
                if error_message:
                    return JsonResponse({'success': False, 'error': error_message}, status=400)
                profile_obj = UserProfile.objects.filter(user=user_obj).only('account_type').first()
                account_type = profile_obj.account_type if profile_obj else UserProfile.ACCOUNT_REGULAR
                role_display_map = {
                    UserProfile.ACCOUNT_REGULAR: '👤 مستخدم عادي',
                    UserProfile.ACCOUNT_COURIER: '🚚 مندوب شحن',
                    UserProfile.ACCOUNT_PACKER: '🧰 موظف تجهيز',
                    UserProfile.ACCOUNT_CUSTOMER_SERVICE: '🛡️ موظف خدمة العملاء',
                    UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER: '🧭 مسؤول خدمة العملاء',
                    UserProfile.ACCOUNT_WAREHOUSE_MANAGER: '📦 مسؤول المستودع',
                    UserProfile.ACCOUNT_SHIPPING_MANAGER: '🚛 مسؤول الشحن',
                }
                if user_obj.is_superuser:
                    role_display = '👑 مدير رئيسي'
                elif account_type in (
                    UserProfile.ACCOUNT_CUSTOMER_SERVICE,
                    UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER,
                ):
                    role_display = role_display_map.get(account_type, '💬 خدمة العملاء')
                elif user_obj.is_staff:
                    role_display = '🛡️ مسؤول (Staff)'
                else:
                    role_display = role_display_map.get(account_type, '👤 مستخدم عادي')

                return JsonResponse({
                    'success': bool(changed),
                    'message': success_message or 'تم حفظ التغيير.',
                    'account_type': account_type,
                    'is_staff': bool(user_obj.is_staff),
                    'is_superuser': bool(user_obj.is_superuser),
                    'role_display': role_display,
                })
            return redirect('manage:user_detail', user_id=user_id)

    return render(request, 'manage/user_detail.html', {
        'user_profile': user_obj,
        'profile_obj': profile_obj,
        'account_type': account_type,
        'is_available': is_available,
        'availability_updated_at': availability_updated_at,
        'recent_orders': orders,
        'wishlist_items': wishlist,
        'addresses': addresses,
        'stats': stats,
    })


def _role_accounts_list_view(request, *, account_type, page_title, icon, clear_url_name):
    search_query = request.GET.get('search', '').strip()
    users = User.objects.filter(
        profile__account_type=account_type
    ).exclude(is_superuser=True).select_related('profile').annotate(
        orders_count=Count('orders'),
        wishlist_count=Count('wishlist'),
    )

    if search_query:
        users = users.filter(
            Q(username__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(profile__phone__icontains=search_query)
        )

    users = users.order_by('-date_joined')
    paginator = Paginator(users, 25)
    page = request.GET.get('page', 1)
    try:
        users = paginator.page(page)
    except PageNotAnInteger:
        users = paginator.page(1)
    except EmptyPage:
        users = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/role_accounts_list.html', {
        'users': users,
        'search_query': search_query,
        'query_string': q.urlencode(),
        'page_title': page_title,
        'icon': icon,
        'clear_url_name': clear_url_name,
    })


@_superuser_required
def shipping_managers_list(request):
    return _role_accounts_list_view(
        request,
        account_type=UserProfile.ACCOUNT_SHIPPING_MANAGER,
        page_title='مسؤولو الشحن',
        icon='🚛',
        clear_url_name='manage:shipping_managers_list',
    )


@_superuser_required
def warehouse_managers_list(request):
    return _role_accounts_list_view(
        request,
        account_type=UserProfile.ACCOUNT_WAREHOUSE_MANAGER,
        page_title='مسؤولو المستودع',
        icon='📦',
        clear_url_name='manage:warehouse_managers_list',
    )


@_superuser_required
def customer_service_accounts_list(request):
    return _role_accounts_list_view(
        request,
        account_type=UserProfile.ACCOUNT_CUSTOMER_SERVICE,
        page_title='موظفو خدمة العملاء',
        icon='💬',
        clear_url_name='manage:customer_service_accounts_list',
    )


@_superuser_required
def customer_service_managers_list(request):
    return _role_accounts_list_view(
        request,
        account_type=UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER,
        page_title='مسؤولو خدمة العملاء',
        icon='🧭',
        clear_url_name='manage:customer_service_managers_list',
    )


@_superuser_required
def admins_list(request):
    """قائمة المسؤولين (is_staff أو is_superuser)"""
    search_query = request.GET.get('search', '').strip()

    admins = User.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True)
    ).annotate(
        orders_count=Count('orders'),
    )

    if search_query:
        admins = admins.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    admins = admins.order_by('-is_superuser', '-date_joined')

    paginator = Paginator(admins, 25)
    page = request.GET.get('page', 1)
    try:
        admins = paginator.page(page)
    except PageNotAnInteger:
        admins = paginator.page(1)
    except EmptyPage:
        admins = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/admins_list.html', {
        'admins': admins,
        'search_query': search_query,
        'query_string': q.urlencode(),
    })


@_superuser_required
def user_profile_edit(request, user_id):
    user_obj = get_object_or_404(User, pk=user_id)
    if user_obj.is_superuser:
        messages.error(request, 'لا يمكن تعديل حساب المدير الرئيسي من هذه الصفحة.')
        return redirect('manage:user_detail', user_id=user_obj.id)

    profile_obj, _ = UserProfile.objects.get_or_create(user=user_obj)

    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip()
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        password1 = request.POST.get('new_password') or ''
        password2 = request.POST.get('confirm_password') or ''
        remove_avatar = request.POST.get('remove_avatar') == '1'

        profile_form = UserProfileForm(request.POST, request.FILES, instance=profile_obj, user=user_obj)
        has_error = False

        if not username:
            messages.error(request, 'اسم المستخدم مطلوب.')
            has_error = True
        elif User.objects.filter(username__iexact=username).exclude(pk=user_obj.pk).exists():
            messages.error(request, 'اسم المستخدم مستخدم مسبقاً.')
            has_error = True

        if email and User.objects.filter(email__iexact=email).exclude(pk=user_obj.pk).exists():
            messages.error(request, 'البريد الإلكتروني مستخدم مسبقاً.')
            has_error = True

        if (password1 or password2) and password1 != password2:
            messages.error(request, 'كلمتا المرور غير متطابقتين.')
            has_error = True

        if (password1 or password2) and len(password1) < 8:
            messages.error(request, 'كلمة المرور يجب أن تكون 8 أحرف على الأقل.')
            has_error = True

        if not has_error and not profile_form.is_valid():
            for field, errs in profile_form.errors.items():
                for err in errs:
                    messages.error(request, f'{field}: {err}')
            has_error = True

        if not has_error:
            user_obj.username = username
            user_obj.email = email
            user_obj.first_name = first_name
            user_obj.last_name = last_name
            user_obj.save(update_fields=['username', 'email', 'first_name', 'last_name'])

            profile_saved = profile_form.save(commit=False)
            if remove_avatar and profile_saved.avatar:
                profile_saved.avatar.delete(save=False)
                profile_saved.avatar = None
            profile_saved.save()

            if password1:
                try:
                    validate_password(password1, user_obj)
                    user_obj.set_password(password1)
                    user_obj.save(update_fields=['password'])
                except Exception as exc:
                    messages.error(request, f'لم يتم تغيير كلمة المرور: {exc}')
                    return redirect('manage:user_profile_edit', user_id=user_obj.id)

            messages.success(request, f'تم تحديث بيانات الحساب {user_obj.username} بنجاح.')
            return redirect('manage:user_detail', user_id=user_obj.id)
    else:
        profile_form = UserProfileForm(instance=profile_obj, user=user_obj)

    return render(request, 'manage/user_profile_edit.html', {
        'target_user': user_obj,
        'profile_form': profile_form,
    })


@_superuser_required
@require_POST
def user_toggle_active(request, user_id):
    """تفعيل/تعطيل مستخدم"""
    user_obj = get_object_or_404(User, pk=user_id)

    if user_obj.is_superuser:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'cannot_toggle_superuser'}, status=400)
        messages.error(request, 'لا يمكن تعطيل حساب المدير الرئيسي')
        return redirect('manage:users_list')

    user_obj.is_active = not user_obj.is_active
    user_obj.save()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'user_id': user_obj.id,
            'is_active': bool(user_obj.is_active),
            'badge_text': '✓ نشط' if user_obj.is_active else '✗ معطل',
            'badge_class': 'badge-active' if user_obj.is_active else 'badge-inactive',
            'button_text': '🔒 تعطيل' if user_obj.is_active else '✅ تفعيل',
            'button_class': 'btn-danger' if user_obj.is_active else 'btn-success',
        })

    status = 'تم تفعيل' if user_obj.is_active else 'تم تعطيل'
    messages.success(request, f'{status} حساب {user_obj.username}')

    if user_obj.is_staff:
        return redirect('manage:admins_list')
    return redirect('manage:users_list')


def overview(request):
    """صفحة النظرة الشاملة - الهيكل الكامل قابل للطي."""
    compartments = Compartment.objects.prefetch_related(
        'shelves__categories__products'
    ).order_by('order')

    data = []
    for comp in compartments:
        comp_data = {
            'compartment': comp,
            'shelves': []
        }
        for shelf in comp.shelves.all().order_by('order'):
            shelf_data = {
                'shelf': shelf,
                'categories': []
            }
            for cat in shelf.categories.all().order_by('order'):
                cat_data = {
                    'category': cat,
                    'product_count': cat.products.count(),
                    'products': cat.products.all().order_by('order')[:5]
                }
                shelf_data['categories'].append(cat_data)
            comp_data['shelves'].append(shelf_data)
        data.append(comp_data)

    return render(request, 'manage/overview.html', {'data': data})


def _can_customer_service_edit_order_basics(user, order) -> bool:
    if not user or not user.is_authenticated:
        return False
    if order.status == Order.STATUS_DELIVERED:
        return False
    if user.is_superuser:
        return True
    try:
        account_type = getattr(getattr(user, 'profile', None), 'account_type', '') or ''
    except Exception:
        account_type = ''
    if account_type not in (
        UserProfile.ACCOUNT_CUSTOMER_SERVICE,
        UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER,
    ):
        return False
    return True


def _is_customer_service_agent_only(user) -> bool:
    if not user or not user.is_authenticated or user.is_superuser:
        return False
    try:
        account_type = getattr(getattr(user, 'profile', None), 'account_type', '') or ''
    except Exception:
        account_type = ''
    return account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE


def _can_open_full_order_edit(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        account_type = getattr(getattr(user, 'profile', None), 'account_type', '') or ''
    except Exception:
        account_type = ''
    return account_type == UserProfile.ACCOUNT_CUSTOMER_SERVICE_MANAGER


@_staff_required
def order_detail(request, pk):
    from .models import OrderStatusHistory, ShippingWaybill
    from .order_engine import (
        PAY_STATUS_ICONS,
        STATUS_ICONS,
        OrderTransitionError,
        advance_order,
        cancel_order,
        mark_payment,
    )

    order = get_object_or_404(
        Order.objects.prefetch_related('items__product', 'items__product__gallery_images', 'items__variant__images', 'items__selected_gallery_image').select_related('shipping_waybill'),
        pk=pk,
    )
    from .manage_seen_utils import mark_seen_kind_pk
    mark_seen_kind_pk(request.user, 'order', order.pk)
    history = OrderStatusHistory.objects.filter(order=order).select_related('changed_by')
    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None
    couriers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_COURIER,
        profile__is_available=True,
        is_active=True
    ).order_by('username')

    can_edit_customer_basics = _can_customer_service_edit_order_basics(request.user, order)
    is_customer_service_agent_only = _is_customer_service_agent_only(request.user)
    can_manage_order_operations = not is_customer_service_agent_only

    if request.method == 'POST':
        action = request.POST.get('action', '')
        note   = request.POST.get('note', '').strip()
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        response_message = ''
        allowed_actions_for_agent = {'edit_customer_basic'}

        if is_customer_service_agent_only and action not in allowed_actions_for_agent:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)
            messages.error(request, 'صلاحيات ممثل خدمة العملاء تسمح فقط بتعديل بيانات الطلب الأساسية.')
            return redirect('manage:order_detail', pk=pk)

        def _order_snapshot_payload(msg=''):
            order.refresh_from_db()
            sh = None
            try:
                sh = order.shipment
            except Exception:
                sh = None
            status_icon = STATUS_ICONS.get(order.status, ('', '', ''))[0]
            pay_icon = PAY_STATUS_ICONS.get(order.payment_status, ('', ''))[0]
            next_statuses = [
                {
                    'code': s,
                    'label': dict(Order.STATUS_CHOICES).get(s, s),
                }
                for s in order.get_allowed_next_statuses()
                if s != Order.STATUS_CANCELLED
            ]
            return {
                'success': True,
                'action': action,
                'message': msg,
                'order_status': order.status,
                'order_status_display': order.get_status_display(),
                'order_status_icon': status_icon,
                'payment_status': order.payment_status,
                'payment_status_display': order.get_payment_status_display(),
                'payment_status_icon': pay_icon,
                'hide_actions': order.status in [Order.STATUS_CANCELLED, Order.STATUS_DELIVERED],
                'shipment_exists': bool(sh),
                'shipment_tracking_number': (sh.tracking_number if sh else ''),
                'shipment_status_display': (sh.get_status_display() if sh else ''),
                'shipment_last_event': (sh.last_event if sh else ''),
                'next_statuses': next_statuses,
                'show_mark_paid': bool(
                    order.payment_method == Order.PAYMENT_GATEWAY
                    and order.payment_status == Order.PAY_STATUS_PENDING
                ),
                'can_be_cancelled': bool(order.can_be_cancelled),
            }

        try:
            if action == 'advance':
                new_status = request.POST.get('new_status', '')
                advance_order(order, new_status, actor=request.user, note=note)
                response_message = f'تم تحديث حالة الطلب إلى: {order.get_status_display()}'
                messages.success(request, f'تم تحديث حالة الطلب إلى: {order.get_status_display()}')

            elif action == 'cancel':
                reason = request.POST.get('cancel_reason', 'admin_decision')
                cancel_order(order, reason=reason, note=note, actor=request.user)
                response_message = 'تم إلغاء الطلب وإعادة المخزون تلقائياً.'
                messages.success(request, 'تم إلغاء الطلب وإعادة المخزون تلقائياً.')

            elif action == 'mark_paid':
                mark_payment(order, Order.PAY_STATUS_PAID, actor=request.user, note=note)
                response_message = 'تم تحديث حالة الدفع إلى: مدفوع'
                messages.success(request, 'تم تحديث حالة الدفع إلى: مدفوع')

            elif action == 'mark_refunded':
                mark_payment(order, Order.PAY_STATUS_REFUNDED, actor=request.user, note=note)
                messages.success(request, 'تم تحديث حالة الدفع إلى: تم الاسترداد')

            elif action == 'shipment_create':
                if shipment:
                    if is_ajax:
                        return JsonResponse({'success': False, 'error': 'shipment_exists'}, status=400)
                    messages.info(request, 'الشحنة موجودة مسبقاً.')
                else:
                    import secrets
                    shipment = Shipment.objects.create(
                        order=order,
                        tracking_number=f"FAKE-{secrets.randbelow(10**8):08d}",
                        status=Shipment.STATUS_PICKED,
                        last_event='تم إنشاء الشحنة من لوحة الإدارة (محاكاة)',
                    )
                    from .notifications import notify_order_status
                    notify_order_status(
                        order,
                        title="تم إنشاء الشحنة",
                        extra=f"رقم التتبع: {shipment.tracking_number}\nالحالة: {shipment.get_status_display()}"
                    )
                    response_message = f'تم إنشاء شحنة (محاكاة). رقم التتبع: {shipment.tracking_number}'
                    messages.success(request, f'تم إنشاء شحنة (محاكاة). رقم التتبع: {shipment.tracking_number}')

            elif action == 'shipment_advance':
                if not shipment:
                    if is_ajax:
                        return JsonResponse({'success': False, 'error': 'shipment_missing'}, status=400)
                    messages.error(request, 'لا توجد شحنة لهذا الطلب. أنشئ شحنة أولاً.')
                else:
                    flow = [
                        Shipment.STATUS_CREATED,
                        Shipment.STATUS_PICKED,
                        Shipment.STATUS_IN_TRANSIT,
                        Shipment.STATUS_OUT_FOR_DELIVERY,
                        Shipment.STATUS_DELIVERED,
                    ]
                    try:
                        idx = flow.index(shipment.status)
                    except ValueError:
                        idx = 0
                    if idx >= len(flow) - 1:
                        if is_ajax:
                            return JsonResponse({'success': False, 'error': 'shipment_already_delivered'}, status=400)
                        messages.info(request, 'الشحنة وصلت بالفعل.')
                    else:
                        shipment.status = flow[idx + 1]
                        shipment.last_event = f'تحديث تلقائي من الإدارة → {shipment.get_status_display()}'
                        shipment.save(update_fields=['status', 'last_event', 'updated_at'])
                        from .notifications import notify_order_status
                        notify_order_status(
                            order,
                            title="تحديث حالة الشحن",
                            extra=f"رقم التتبع: {shipment.tracking_number}\nالحالة: {shipment.get_status_display()}"
                        )
                        response_message = f'تم تحديث الشحنة إلى: {shipment.get_status_display()}'
                        messages.success(request, f'تم تحديث الشحنة إلى: {shipment.get_status_display()}')

            elif action == 'shipment_assign_courier':
                if not shipment:
                    if is_ajax:
                        return JsonResponse({'success': False, 'error': 'shipment_missing'}, status=400)
                    messages.error(request, 'لا توجد شحنة. أنشئ شحنة أولاً.')
                else:
                    courier_id = request.POST.get('courier_id', '').strip()
                    courier = None
                    if courier_id:
                        courier = User.objects.filter(
                            pk=courier_id,
                            profile__account_type=UserProfile.ACCOUNT_COURIER,
                            profile__is_available=True,
                            is_active=True
                        ).first()
                    shipment.courier = courier
                    shipment.save(update_fields=['courier', 'updated_at'])
                    if courier:
                        response_message = f'تم إسناد الشحنة إلى المندوب: {courier.username}'
                        messages.success(request, f'تم إسناد الشحنة إلى المندوب: {courier.username}')
                    else:
                        response_message = 'تم إلغاء إسناد المندوب عن الشحنة'
                        messages.success(request, 'تم إلغاء إسناد المندوب عن الشحنة')

            elif action == 'waybill_restore':
                if order.status == Order.STATUS_CANCELLED:
                    messages.error(request, _('لا يمكن استعادة بوليصة لطلب ملغى.'))
                else:
                    from .shipping_waybill_service import ensure_shipping_waybill_for_order

                    _wb_m, created, _lbl_m = ensure_shipping_waybill_for_order(
                        order,
                        actor=request.user,
                        source_line=str(_('استعادة/تجديد تسجيل البوليصة من لوحة الإدارة.')),
                    )
                    if created:
                        messages.success(
                            request,
                            _('تم إنشاء سجل بوليصة الشحن الموحّد من كود الملصق.'),
                        )
                    else:
                        messages.success(
                            request,
                            _('تم تحديث سجل بوليصة الشحن ليتطابق مع كود الملصق الحالي.'),
                        )

            elif action == 'create_share_cart':
                import secrets
                token = secrets.token_urlsafe(10)
                while CartShare.objects.filter(token=token).exists():
                    token = secrets.token_urlsafe(10)

                share = CartShare.objects.create(
                    token=token,
                    created_by=request.user,
                    is_active=True,
                )
                created_items = 0
                for it in order.items.select_related('product', 'variant').all():
                    CartShareItem.objects.create(
                        cart_share=share,
                        product=it.product,
                        variant=it.variant,
                        quantity=max(1, int(it.quantity)),
                        price_snapshot=it.price,
                    )
                    created_items += 1

                share_url = _public_absolute_url(request, reverse('cart_share_view', args=[share.token]))
                request.session['manage_last_cart_share_url'] = share_url
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'action': 'create_share_cart',
                        'created_items': created_items,
                        'share_url': share_url,
                        'message': f'تم إنشاء رابط سلة من الطلب ({created_items} منتج).',
                    })
                messages.success(request, f'تم إنشاء رابط سلة من الطلب ({created_items} منتج).')

            elif action == 'edit_customer_basic':
                if not can_edit_customer_basics:
                    if is_ajax:
                        return JsonResponse({'success': False, 'error': 'forbidden'}, status=403)
                    messages.error(request, 'لا تملك صلاحية تعديل بيانات الطلب في هذه المرحلة.')
                    return redirect('manage:order_detail', pk=pk)
                from .models import OrderStatusHistory
                customer_name = (request.POST.get('customer_name') or '').strip()
                customer_phone = (request.POST.get('customer_phone') or '').strip()
                address = (request.POST.get('address') or '').strip()
                notes_val = (request.POST.get('order_notes') or '').strip()
                if not customer_name or not customer_phone or not address:
                    messages.error(request, 'الاسم والجوال والعنوان حقول مطلوبة.')
                    return redirect('manage:order_detail', pk=pk)
                before = {
                    'customer_name': order.customer_name or '',
                    'customer_phone': order.customer_phone or '',
                    'address': order.address or '',
                    'notes': order.notes or '',
                }
                order.customer_name = customer_name
                order.customer_phone = customer_phone
                order.address = address
                order.notes = notes_val
                order.save(update_fields=['customer_name', 'customer_phone', 'address', 'notes', 'updated_at'])
                after = {
                    'customer_name': order.customer_name or '',
                    'customer_phone': order.customer_phone or '',
                    'address': order.address or '',
                    'notes': order.notes or '',
                }
                changes = []
                if before['customer_name'] != after['customer_name']:
                    changes.append(f"الاسم: '{before['customer_name']}' → '{after['customer_name']}'")
                if before['customer_phone'] != after['customer_phone']:
                    changes.append(f"الجوال: '{before['customer_phone']}' → '{after['customer_phone']}'")
                if before['address'] != after['address']:
                    changes.append("العنوان: تم التعديل")
                if before['notes'] != after['notes']:
                    changes.append("ملاحظات الطلب: تم التعديل")
                if changes:
                    changes_block = '\n'.join([f'- {c}' for c in changes])
                    OrderStatusHistory.objects.create(
                        order=order,
                        old_status=order.status,
                        new_status=order.status,
                        old_payment_status=order.payment_status,
                        new_payment_status=order.payment_status,
                        changed_by=request.user,
                        is_automatic=False,
                        note='تعديل بيانات العميل الأساسية:\n' + changes_block,
                    )
                response_message = 'تم تحديث بيانات الطلب الأساسية بنجاح.'
                messages.success(request, response_message)

        except OrderTransitionError as e:
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(request, str(e))

        if is_ajax:
            return JsonResponse(_order_snapshot_payload(response_message))
        return redirect('manage:order_detail', pk=pk)

    next_statuses = [
        (s, dict(Order.STATUS_CHOICES).get(s, s))
        for s in order.get_allowed_next_statuses()
        if s != Order.STATUS_CANCELLED
    ]

    try:
        shipping_waybill = order.shipping_waybill
    except ShippingWaybill.DoesNotExist:
        shipping_waybill = None

    cart_share_url = request.session.pop('manage_last_cart_share_url', '')

    return render(request, 'manage/order_detail.html', {
        'order': order,
        'history': history,
        'shipment': shipment,
        'shipping_waybill': shipping_waybill,
        'couriers': couriers,
        'next_statuses': next_statuses,
        'status_icons': STATUS_ICONS,
        'pay_status_icons': PAY_STATUS_ICONS,
        'cancel_reasons': Order.CANCEL_REASON_CHOICES,
        'cart_share_url': cart_share_url,
        'can_edit_customer_basics': can_edit_customer_basics,
        'can_manage_order_operations': can_manage_order_operations,
        'can_open_full_order_edit': _can_open_full_order_edit(request.user),
    })


@_staff_required
def order_edit(request, pk):
    order = get_object_or_404(
        Order.objects.prefetch_related(
            'items__product',
            'items__variant',
            'items__selected_gallery_image',
        ),
        pk=pk,
    )
    if not _can_open_full_order_edit(request.user):
        messages.error(request, 'هذه الصفحة متاحة للمدير الرئيسي أو مسؤول خدمة العملاء فقط.')
        return redirect('manage:order_detail', pk=pk)
    if order.status in [Order.STATUS_DELIVERED, Order.STATUS_CANCELLED]:
        messages.error(request, 'لا يمكن تعديل الطلب بعد اكتماله أو إلغائه.')
        return redirect('manage:order_detail', pk=pk)

    editable_items = list(order.items.all())
    active_products = Product.objects.filter(is_active=True).order_by('name_ar')[:300]
    active_variants = ProductVariant.objects.filter(is_active=True).select_related('product').order_by('product__name_ar', 'id')[:500]
    preview = None
    changes_summary = []
    def _image_for_selection(product, variant=None, selected_gallery_image=None):
        try:
            if variant:
                images = list(variant.images.all())
                primary = next((img for img in images if img.is_primary), None) or (images[0] if images else None)
                if primary and getattr(primary, 'image', None):
                    return primary.image.url
            if selected_gallery_image and getattr(selected_gallery_image, 'image', None):
                return selected_gallery_image.image.url
            if product:
                gallery = product.gallery_images.filter(is_primary=True).order_by('sort_order', 'id').first()
                if not gallery:
                    gallery = product.gallery_images.order_by('sort_order', 'id').first()
                if gallery and getattr(gallery, 'image', None):
                    return gallery.image.url
        except Exception:
            return ''
        return ''

    edit_history = list(
        order.status_history.select_related('changed_by')
        .filter(note__icontains='تعديل شامل')
        .order_by('-created_at')[:30]
    )
    parsed_edit_history = []
    operation_re = re.compile(
        r'^\d+\)\s*(?P<action>[^|]+)\s*\|\s*قبل:\s*(?P<before>.*?)\s*\|\s*بعد:\s*(?P<after>.*)$'
    )
    for h in edit_history:
        operations = []
        marker = 'ORDER_EDIT_LOG_JSON::'
        marker_pos = (h.note or '').find(marker)
        if marker_pos >= 0:
            json_part = (h.note or '')[marker_pos + len(marker):].strip()
            try:
                payload = json.loads(json_part)
                if isinstance(payload, list):
                    for op in payload:
                        operations.append(
                            {
                                'action': op.get('action_label') or op.get('change_type') or '-',
                                'before': op.get('before_compact') or '-',
                                'after': op.get('after_compact') or '-',
                                'before_name': op.get('before_name') or '-',
                                'before_variant': op.get('before_variant') or '-',
                                'before_sku': op.get('before_sku') or '-',
                                'before_qty': op.get('before_qty', 0),
                                'before_image_url': op.get('before_image_url') or '',
                                'before_base_price': op.get('before_base_price') or '-',
                                'before_final_price': op.get('before_final_price') or '-',
                                'before_discount': op.get('before_discount') or '-',
                                'after_name': op.get('after_name') or '-',
                                'after_variant': op.get('after_variant') or '-',
                                'after_sku': op.get('after_sku') or '-',
                                'after_qty': op.get('after_qty', 0),
                                'after_image_url': op.get('after_image_url') or '',
                                'after_base_price': op.get('after_base_price') or '-',
                                'after_final_price': op.get('after_final_price') or '-',
                                'after_discount': op.get('after_discount') or '-',
                            }
                        )
            except Exception:
                operations = []
        for line in (h.note or '').splitlines():
            if line.strip().startswith(marker):
                continue
            match = operation_re.match(line.strip())
            if not match:
                continue
            operations.append(
                {
                    'action': (match.group('action') or '').strip(),
                    'before': (match.group('before') or '-').strip(),
                    'after': (match.group('after') or '-').strip(),
                }
            )
        parsed_edit_history.append(
            {
                'history': h,
                'operations': operations,
            }
        )
    editable_rows = [
        {
            'item': it,
            'qty': int(it.quantity or 1),
            'repl_product': '',
            'repl_variant': '',
            'remove': False,
        }
        for it in editable_items
    ]

    if request.method == 'POST':
        item_map = {str(it.id): it for it in editable_items}
        edited_lines = []
        item_ids = request.POST.getlist('item_id')
        for iid in item_ids:
            base = item_map.get(str(iid))
            if not base:
                continue
            remove_flag = (request.POST.get(f'remove_{iid}') or '').strip().lower() in ('1', 'true', 'on', 'yes')
            qty_raw = (request.POST.get(f'qty_{iid}') or '').strip()
            qty = int(qty_raw) if qty_raw.isdigit() else 0
            repl_variant_id = (request.POST.get(f'repl_variant_{iid}') or '').strip()
            repl_product_id = (request.POST.get(f'repl_product_{iid}') or '').strip()

            for row in editable_rows:
                if row['item'].id == base.id:
                    row['qty'] = qty if qty_raw.isdigit() else (qty_raw or '')
                    row['repl_product'] = repl_product_id
                    row['repl_variant'] = repl_variant_id
                    row['remove'] = remove_flag
                    break

            if remove_flag:
                before_base = base.variant.effective_price if base.variant else (
                    base.selected_gallery_image.effective_price if base.selected_gallery_image else base.product.price
                )
                before_final = Decimal(str(base.price or 0))
                before_discount = max(Decimal(str(before_base or 0)) - before_final, Decimal('0'))
                changes_summary.append(
                    {
                        'change_type': 'remove',
                        'action_label': 'حذف',
                        'before_name': base.display_product_name,
                        'before_variant': base.display_variant_label or '-',
                        'before_sku': base.display_sku or '-',
                        'before_qty': int(base.quantity or 0),
                        'before_image_url': base.display_image_url or '',
                        'before_base_price': format_sar_amount(before_base),
                        'before_final_price': format_sar_amount(before_final),
                        'before_discount': format_sar_amount(before_discount),
                        'before_subtotal': format_sar_amount((base.quantity or 0) * base.price),
                        'after_name': '-',
                        'after_variant': '-',
                        'after_sku': '-',
                        'after_qty': 0,
                        'after_image_url': '',
                        'after_base_price': '-',
                        'after_final_price': '-',
                        'after_discount': '-',
                        'after_subtotal': '-',
                        'after_key': '',
                        'before_compact': f"{base.display_product_name} ({base.display_variant_label or '-'}) x{int(base.quantity or 0)}",
                        'after_compact': '-',
                    }
                )
                continue
            if qty <= 0:
                continue

            product = base.product
            variant = base.variant
            selected_gallery_image = base.selected_gallery_image
            if repl_variant_id.isdigit():
                new_variant = ProductVariant.objects.filter(pk=int(repl_variant_id), is_active=True).select_related('product').first()
                if not new_variant:
                    messages.error(request, 'النسخة البديلة غير متاحة.')
                    return redirect('manage:order_edit', pk=pk)
                product = new_variant.product
                variant = new_variant
                selected_gallery_image = None
            elif repl_product_id.isdigit():
                new_product = Product.objects.filter(pk=int(repl_product_id), is_active=True).first()
                if not new_product:
                    messages.error(request, 'المنتج البديل غير متاح.')
                    return redirect('manage:order_edit', pk=pk)
                product = new_product
                variant = None
                selected_gallery_image = None

            new_unit_price = variant.effective_price if variant else (
                selected_gallery_image.effective_price if selected_gallery_image else product.price
            )
            before_base = base.variant.effective_price if base.variant else (
                base.selected_gallery_image.effective_price if base.selected_gallery_image else base.product.price
            )
            before_final = Decimal(str(base.price or 0))
            before_discount = max(Decimal(str(before_base or 0)) - before_final, Decimal('0'))
            before_signature = f'{base.product_id}:{base.variant_id or 0}:{base.selected_gallery_image_id or 0}:{int(base.quantity or 0)}'
            after_signature = f'{product.id}:{variant.id if variant else 0}:{selected_gallery_image.id if selected_gallery_image else 0}:{qty}'
            after_price_key = f'{product.id}:{variant.id if variant else 0}:{qty}'
            if before_signature != after_signature:
                change_type = 'replace' if (base.product_id != product.id or (base.variant_id or 0) != (variant.id if variant else 0)) else 'update_qty'
                changes_summary.append(
                    {
                        'change_type': change_type,
                        'action_label': 'استبدال' if change_type == 'replace' else 'تعديل كمية',
                        'before_name': base.display_product_name,
                        'before_variant': base.display_variant_label or '-',
                        'before_sku': base.display_sku or '-',
                        'before_qty': int(base.quantity or 0),
                        'before_image_url': base.display_image_url or '',
                        'before_base_price': format_sar_amount(before_base),
                        'before_final_price': format_sar_amount(before_final),
                        'before_discount': format_sar_amount(before_discount),
                        'before_subtotal': format_sar_amount((base.quantity or 0) * base.price),
                        'after_name': product.name_ar,
                        'after_variant': (variant.color_name or variant.title or variant.code) if variant else '-',
                        'after_sku': (variant.code if variant else (product.sku or '-')),
                        'after_qty': qty,
                        'after_image_url': _image_for_selection(product, variant, selected_gallery_image),
                        'after_base_price': format_sar_amount(new_unit_price),
                        'after_final_price': format_sar_amount(new_unit_price),
                        'after_discount': format_sar_amount(Decimal('0')),
                        'after_subtotal': format_sar_amount(Decimal(str(new_unit_price)) * qty),
                        'after_key': after_price_key,
                        'before_compact': f"{base.display_product_name} ({base.display_variant_label or '-'}) x{int(base.quantity or 0)}",
                        'after_compact': f"{product.name_ar} ({(variant.color_name or variant.title or variant.code) if variant else '-'}) x{qty}",
                    }
                )
            edited_lines.append(
                {
                    'product': product,
                    'variant': variant,
                    'selected_gallery_image': selected_gallery_image,
                    'quantity': qty,
                }
            )
        try:
            from .order_edit_service import apply_order_edit, preview_order_edit

            pricing_preview = preview_order_edit(order=order, edited_lines=edited_lines, include_line_details=True)
            detail_map = {}
            for det in pricing_preview.get('line_details', []):
                key = (
                    f"{int(det.get('product_id') or 0)}:"
                    f"{int(det.get('variant_id') or 0)}:0:"
                    f"{int(det.get('quantity') or 0)}"
                )
                detail_map.setdefault(key, []).append(det)
            for ch in changes_summary:
                if ch.get('change_type') == 'remove':
                    continue
                key = ch.get('after_key') or ''
                bucket = detail_map.get(key) or []
                if not bucket:
                    continue
                det = bucket.pop(0)
                base_u = Decimal(str(det.get('base_unit_price') or 0))
                final_u = Decimal(str(det.get('unit_price_final') or 0))
                disc_u = max(base_u - final_u, Decimal('0'))
                ch['after_base_price'] = format_sar_amount(base_u)
                ch['after_final_price'] = format_sar_amount(final_u)
                ch['after_discount'] = format_sar_amount(disc_u)
                ch['after_subtotal'] = format_sar_amount(Decimal(str(det.get('line_total_final') or 0)))

            edit_action = (request.POST.get('edit_action') or 'preview').strip()
            if edit_action == 'apply':
                apply_order_edit(
                    order=order,
                    edited_lines=edited_lines,
                    actor=request.user,
                    edit_log_lines=changes_summary,
                )
                messages.success(request, 'تم تطبيق تعديل الطلب بنجاح مع تسوية المخزون وإعادة التسعير.')
                return redirect('manage:order_detail', pk=pk)
            preview = preview_order_edit(order=order, edited_lines=edited_lines)
        except ValueError as e:
            messages.error(request, str(e))

    return render(request, 'manage/order_edit.html', {
        'order': order,
        'editable_items': editable_items,
        'active_products': active_products,
        'active_variants': active_variants,
        'preview': preview,
        'editable_rows': editable_rows,
        'changes_summary': changes_summary,
        'parsed_edit_history': parsed_edit_history,
    })


@_staff_required
def order_detail_live_state(request, pk):
    """حالة حيّة خفيفة لصفحة تفاصيل الطلب بالإدارة (بدون رفرش كامل)."""
    from .order_engine import PAY_STATUS_ICONS, STATUS_ICONS
    order = get_object_or_404(Order, pk=pk)
    sh = None
    try:
        sh = order.shipment
    except Exception:
        sh = None
    next_statuses = [
        {
            'code': s,
            'label': dict(Order.STATUS_CHOICES).get(s, s),
        }
        for s in order.get_allowed_next_statuses()
        if s != Order.STATUS_CANCELLED
    ]
    status_icon = STATUS_ICONS.get(order.status, ('', '', ''))[0]
    pay_icon = PAY_STATUS_ICONS.get(order.payment_status, ('', ''))[0]
    signature = '|'.join([
        str(order.status or ''),
        str(order.payment_status or ''),
        str(sh.status if sh else ''),
        order.updated_at.isoformat() if order.updated_at else '',
        sh.updated_at.isoformat() if sh and sh.updated_at else '',
    ])
    return JsonResponse({
        'success': True,
        'signature': signature,
        'order_status': order.status,
        'order_status_display': order.get_status_display(),
        'order_status_icon': status_icon,
        'payment_status': order.payment_status,
        'payment_status_display': order.get_payment_status_display(),
        'payment_status_icon': pay_icon,
        'hide_actions': order.status in [Order.STATUS_CANCELLED, Order.STATUS_DELIVERED],
        'shipment_exists': bool(sh),
        'shipment_tracking_number': (sh.tracking_number if sh else ''),
        'shipment_status_display': (sh.get_status_display() if sh else ''),
        'shipment_last_event': (sh.last_event if sh else ''),
        'next_statuses': next_statuses,
        'show_mark_paid': bool(
            order.payment_method == Order.PAYMENT_GATEWAY
            and order.payment_status == Order.PAY_STATUS_PENDING
        ),
        'can_be_cancelled': bool(order.can_be_cancelled),
    })


@_staff_required
def order_waybill_qr_png(request, pk):
    """صورة QR لكود الملصق (نفس محتوى البوليصة) — للعرض في تفاصيل الطلب بالإدارة."""
    import io

    import qrcode

    order = get_object_or_404(Order, pk=pk)
    code = None
    try:
        code = order.label_code.code
    except LabelCode.DoesNotExist:
        pass
    if not code:
        try:
            wb = order.shipping_waybill
            c = (wb.linked_internal_code or '').strip()
            if c:
                code = c
        except ShippingWaybill.DoesNotExist:
            pass
    if not code:
        return HttpResponse(status=404)

    payload = f'DLBK:{code}'
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@_staff_required
def manage_order_shipping_label(request, pk):
    """طباعة بوليصة الشحن من الإدارة (نسخة مطابقة للمستودع) — لأي طلب غير ملغى."""
    from .shipping_waybill_service import ensure_shipping_waybill_for_order

    order = get_object_or_404(Order.objects.prefetch_related('items__product', 'items__product__gallery_images', 'items__variant__images', 'items__selected_gallery_image'), pk=pk)
    if order.status == Order.STATUS_CANCELLED:
        messages.error(request, _('لا يمكن طباعة بوليصة لطلب ملغى.'))
        return redirect('manage:order_detail', pk=pk)

    _wb, _created_wb, label = ensure_shipping_waybill_for_order(
        order,
        actor=request.user,
        source_line=str(_('طباعة بوليصة الشحن من لوحة الإدارة.')),
    )
    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None

    return render(request, 'manage/order_shipping_label_print.html', {
        'order': order,
        'shipment': shipment,
        'label': label,
    })


@_staff_required
def variants_inventory_export_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="variants_inventory.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Product ID', 'Product SKU', 'Product Name', 'Variant ID', 'Variant SKU', 'Variant Label', 'Color HEX', 'Stock', 'Active'])
    qs = ProductVariant.objects.select_related('product').order_by('product_id', 'sort_order', 'id')
    for v in qs:
        writer.writerow([
            v.product_id,
            v.product.sku or '',
            v.product.name_ar or '',
            v.id,
            v.code,
            v.color_name or v.title or v.code,
            v.color_hex or '',
            v.stock_quantity,
            '1' if v.is_active else '0',
        ])
    return response


@_staff_required
def variant_stock_json(request, variant_id):
    variant = get_object_or_404(ProductVariant.objects.select_related('product'), pk=variant_id)
    return JsonResponse({
        'success': True,
        'variant_id': variant.id,
        'variant_code': variant.code,
        'product_id': variant.product_id,
        'product_sku': variant.product.sku or '',
        'stock_quantity': int(variant.stock_quantity or 0),
        'is_active': bool(variant.is_active),
        'effective_price': str(variant.effective_price),
    })


# ===========================
# الشحن داخل لوحة الإدارة
# ===========================

@_staff_required
def shipments_list_manage(request):
    """قائمة الشحنات (لإدارة الإسناد والمتابعة)"""
    status_filter = request.GET.get('status', '').strip()
    courier_filter = request.GET.get('courier', '').strip()
    search_query = request.GET.get('search', '').strip()

    items = Shipment.objects.select_related('order', 'courier', 'courier__profile').all()
    if status_filter:
        items = items.filter(status=status_filter)
    if courier_filter:
        if courier_filter == 'unassigned':
            items = items.filter(courier__isnull=True)
        else:
            items = items.filter(courier_id=courier_filter)
    if search_query:
        items = items.filter(
            Q(order__id__icontains=search_query) |
            Q(tracking_number__icontains=search_query) |
            Q(order__customer_name__icontains=search_query) |
            Q(order__customer_phone__icontains=search_query)
        )

    items = items.order_by('-updated_at')
    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)

    couriers = User.objects.filter(profile__account_type=UserProfile.ACCOUNT_COURIER).order_by('username')

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/shipments_list.html', {
        'items': items,
        'status_filter': status_filter,
        'courier_filter': courier_filter,
        'search_query': search_query,
        'status_choices': Shipment.STATUS_CHOICES,
        'couriers': couriers,
        'query_string': q.urlencode(),
    })


@_staff_required
def shipment_detail_manage(request, pk):
    """تفاصيل الشحنة + إسناد المندوب"""
    shipment = get_object_or_404(Shipment.objects.select_related('order', 'courier'), pk=pk)
    from .manage_seen_utils import mark_seen_kind_pk
    mark_seen_kind_pk(request.user, 'shipment', shipment.pk)
    couriers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_COURIER,
        profile__is_available=True,
        is_active=True
    ).order_by('username')

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'assign':
            courier_id = request.POST.get('courier_id', '').strip()
            courier = None
            if courier_id:
                courier = User.objects.filter(
                    pk=courier_id,
                    profile__account_type=UserProfile.ACCOUNT_COURIER,
                    profile__is_available=True,
                    is_active=True
                ).first()
            shipment.courier = courier
            shipment.save(update_fields=['courier', 'updated_at'])
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'shipment_id': shipment.id,
                    'courier_id': courier.id if courier else None,
                    'courier_username': courier.username if courier else '',
                    'updated_at': shipment.updated_at.strftime('%Y-%m-%d %H:%M'),
                })
            messages.success(request, 'تم تحديث إسناد المندوب.')
            return redirect('manage:shipment_detail_manage', pk=pk)

    return render(request, 'manage/shipment_detail_manage.html', {
        'shipment': shipment,
        'couriers': couriers,
    })


@_staff_required
def couriers_list(request):
    """قائمة مناديب الشحن (عرض فقط + تفعيل/تعطيل)"""
    search_query = request.GET.get('search', '').strip()
    availability_filter = request.GET.get('availability', '').strip()
    couriers = User.objects.filter(profile__account_type=UserProfile.ACCOUNT_COURIER).select_related('profile')
    if search_query:
        couriers = couriers.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(profile__phone__icontains=search_query)
        )
    if availability_filter == 'available':
        couriers = couriers.filter(profile__is_available=True)
    elif availability_filter == 'unavailable':
        couriers = couriers.filter(profile__is_available=False)
    couriers = couriers.order_by('-is_active', 'username')

    paginator = Paginator(couriers, 25)
    page = request.GET.get('page', 1)
    try:
        couriers = paginator.page(page)
    except PageNotAnInteger:
        couriers = paginator.page(1)
    except EmptyPage:
        couriers = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/couriers_list.html', {
        'couriers': couriers,
        'search_query': search_query,
        'availability_filter': availability_filter,
        'query_string': q.urlencode(),
    })


@_staff_required
def packers_list(request):
    """قائمة مناديب/موظفي المستودع (تجهيز الطلبات)"""
    search_query = request.GET.get('search', '').strip()
    availability_filter = request.GET.get('availability', '').strip()
    packers = User.objects.filter(profile__account_type=UserProfile.ACCOUNT_PACKER).select_related('profile')
    if search_query:
        packers = packers.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(profile__phone__icontains=search_query)
        )
    if availability_filter == 'available':
        packers = packers.filter(profile__is_available=True)
    elif availability_filter == 'unavailable':
        packers = packers.filter(profile__is_available=False)
    packers = packers.order_by('-is_active', 'username')

    paginator = Paginator(packers, 25)
    page = request.GET.get('page', 1)
    try:
        packers = paginator.page(page)
    except PageNotAnInteger:
        packers = paginator.page(1)
    except EmptyPage:
        packers = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/packers_list.html', {
        'packers': packers,
        'search_query': search_query,
        'availability_filter': availability_filter,
        'query_string': q.urlencode(),
    })


@_staff_required
@require_GET
def packers_availability_live(request):
    """GET — حالة التوفر لمهيّزين محددين (مزامنة قائمة /manage/packers/)."""
    raw = request.GET.get('ids', '').strip()
    if not raw:
        return JsonResponse({'success': True, 'users': {}})
    parts = [p.strip() for p in raw.split(',') if p.strip().isdigit()]
    parts = parts[:150]
    int_ids = [int(p) for p in parts]
    rows = User.objects.filter(
        pk__in=int_ids,
        profile__account_type=UserProfile.ACCOUNT_PACKER,
    ).values('id', 'profile__is_available')
    users = {}
    for row in rows:
        uid = row['id']
        avail = bool(row['profile__is_available'])
        users[str(uid)] = {
            'is_available': avail,
            'badge_text': '🟢 متوفر' if avail else '⚪ غير متوفر',
            'button_text': 'إيقاف التوفر' if avail else 'تفعيل التوفر',
            'button_class': 'btn-secondary' if avail else 'btn-primary',
        }
    return JsonResponse({'success': True, 'users': users})


@_staff_required
@require_GET
def couriers_availability_live(request):
    """GET — حالة التوفر لمندوبي شحن محددين (مزامنة قائمة /manage/couriers/)."""
    raw = request.GET.get('ids', '').strip()
    if not raw:
        return JsonResponse({'success': True, 'users': {}})
    parts = [p.strip() for p in raw.split(',') if p.strip().isdigit()]
    parts = parts[:150]
    int_ids = [int(p) for p in parts]
    rows = User.objects.filter(
        pk__in=int_ids,
        profile__account_type=UserProfile.ACCOUNT_COURIER,
    ).values('id', 'profile__is_available')
    users = {}
    for row in rows:
        uid = row['id']
        avail = bool(row['profile__is_available'])
        users[str(uid)] = {
            'is_available': avail,
            'badge_text': '🟢 متوفر' if avail else '⚪ غير متوفر',
            'button_text': 'إيقاف التوفر' if avail else 'تفعيل التوفر',
            'button_class': 'btn-secondary' if avail else 'btn-primary',
        }
    return JsonResponse({'success': True, 'users': users})


@_staff_required
@require_POST
def user_toggle_availability(request, user_id):
    user_obj = get_object_or_404(User, pk=user_id)
    profile_obj, _ = UserProfile.objects.get_or_create(user=user_obj)
    if profile_obj.account_type not in (UserProfile.ACCOUNT_COURIER, UserProfile.ACCOUNT_PACKER):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'not_supported_for_role'}, status=400)
        messages.error(request, 'هذه الخاصية متاحة فقط لمناديب الشحن والتجهيز.')
        return redirect(request.POST.get('next') or 'manage:user_detail', user_id=user_id)

    force_value = (request.POST.get('is_available') or '').strip().lower()
    if force_value in ('1', 'true', 'yes', 'on'):
        profile_obj.is_available = True
    elif force_value in ('0', 'false', 'no', 'off'):
        profile_obj.is_available = False
    else:
        profile_obj.is_available = not profile_obj.is_available
    profile_obj.availability_updated_at = timezone.now()
    profile_obj.availability_updated_by = request.user
    profile_obj.save(update_fields=['is_available', 'availability_updated_at', 'availability_updated_by'])

    role_text = 'مندوب الشحن' if profile_obj.account_type == UserProfile.ACCOUNT_COURIER else 'مندوب التجهيز'
    status_text = 'متوفر' if profile_obj.is_available else 'غير متوفر'

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'user_id': user_obj.id,
            'is_available': bool(profile_obj.is_available),
            'badge_text': '🟢 متوفر' if profile_obj.is_available else '⚪ غير متوفر',
            'badge_class': 'badge-active' if profile_obj.is_available else 'badge-unavailable',
            'button_text': 'إيقاف التوفر' if profile_obj.is_available else 'تفعيل التوفر',
            'button_class': 'btn-secondary' if profile_obj.is_available else 'btn-primary',
            'availability_updated_at': profile_obj.availability_updated_at.strftime('%Y-%m-%d %H:%M') if profile_obj.availability_updated_at else '',
            'updated_at': profile_obj.availability_updated_at.isoformat() if profile_obj.availability_updated_at else '',
            'role_text': role_text,
        })

    messages.success(request, f'تم تحديث حالة {role_text} إلى: {status_text}')
    return redirect(request.POST.get('next') or 'manage:user_detail', user_id=user_id)



@_staff_required
def warehouse_orders_manage(request):
    """إدارة المستودع: متابعة طلبات التجهيز وإسنادها"""
    status_filter = request.GET.get('status', 'all').strip() or 'all'
    packer_filter = request.GET.get('packer', '').strip()
    search_query = request.GET.get('search', '').strip()

    orders = Order.objects.select_related('user', 'packer', 'packer__profile').prefetch_related('items__product').all()
    if status_filter != 'all':
        orders = orders.filter(status=status_filter)

    if packer_filter:
        if packer_filter == 'unassigned':
            orders = orders.filter(packer__isnull=True)
        else:
            orders = orders.filter(packer_id=packer_filter)

    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query)
        )

    orders = orders.order_by('-created_at')
    paginator = Paginator(orders, 25)
    page = request.GET.get('page', 1)
    try:
        orders = paginator.page(page)
    except PageNotAnInteger:
        orders = paginator.page(1)
    except EmptyPage:
        orders = paginator.page(paginator.num_pages)

    packers = User.objects.filter(
        profile__account_type=UserProfile.ACCOUNT_PACKER,
        profile__is_available=True
    ).order_by('username')
    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/warehouse_orders_manage.html', {
        'orders': orders,
        'status_filter': status_filter,
        'packer_filter': packer_filter,
        'search_query': search_query,
        'status_choices': Order.STATUS_CHOICES,
        'packers': packers,
        'query_string': q.urlencode(),
    })


@_staff_required
def contact_messages_list(request):
    """قائمة رسائل اتصل بنا"""
    items = ContactMessage.objects.all().order_by('-created_at')
    paginator = Paginator(items, 20)
    page = request.GET.get('page', 1)
    try:
        items = paginator.page(page)
    except PageNotAnInteger:
        items = paginator.page(1)
    except EmptyPage:
        items = paginator.page(paginator.num_pages)
    q = request.GET.copy()
    q.pop('page', None)
    return render(request, 'manage/contact_messages_list.html', {
        'items': items,
        'query_string': q.urlencode(),
    })


# ===== إدارة المرتجعات =====

@_staff_required
def returns_list(request):
    """قائمة جميع المرتجعات"""
    from django.db.models import Sum

    status_filter = request.GET.get('status', '')
    returns = Return.objects.all().select_related('order', 'user').prefetch_related('items__product')

    total_refund_raw = Return.objects.filter(
        status__in=[Return.STATUS_APPROVED, Return.STATUS_COMPLETED]
    ).aggregate(Sum('refund_amount'))['refund_amount__sum'] or 0

    stats = {
        'all': Return.objects.count(),
        'pending': Return.objects.filter(status__in=[Return.STATUS_REQUESTED, Return.STATUS_REVIEWING]).count(),
        'approved': Return.objects.filter(status=Return.STATUS_APPROVED).count(),
        'rejected': Return.objects.filter(status=Return.STATUS_REJECTED).count(),
        'completed': Return.objects.filter(status=Return.STATUS_COMPLETED).count(),
        'total_refund': format_sar_amount(total_refund_raw),
    }

    if status_filter:
        returns = returns.filter(status=status_filter)

    returns = returns.order_by('-created_at')

    paginator = Paginator(returns, 20)
    page = request.GET.get('page', 1)
    try:
        returns = paginator.page(page)
    except PageNotAnInteger:
        returns = paginator.page(1)
    except EmptyPage:
        returns = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)

    return render(request, 'manage/returns_list.html', {
        'returns': returns,
        'query_string': q.urlencode(),
        'status_filter': status_filter,
        'status_choices': Return.STATUS_CHOICES,
        'stats': stats,
        'can_view_revenue_panel': bool(request.user.is_superuser),
    })


@_staff_required
def return_detail(request, pk):
    """تفاصيل مرتجع محدد مع محرك انتقال الحالات"""
    from .models import ReturnStatusHistory
    from .return_engine import (
        REFUND_STATUS_ICONS,
        RETURN_STATUS_ICONS,
        ReturnTransitionError,
        advance_return,
        build_return_timeline,
        reject_return,
        render_return_timeline_html,
    )

    return_obj = get_object_or_404(
        Return.objects.select_related('order', 'user').prefetch_related(
            Prefetch(
                'status_history',
                queryset=ReturnStatusHistory.objects.select_related('changed_by').order_by('created_at'),
            ),
            'items__product',
        ),
        pk=pk,
    )
    from .manage_seen_utils import mark_seen_kind_pk
    mark_seen_kind_pk(request.user, 'return_request', return_obj.pk)
    history = ReturnStatusHistory.objects.filter(return_request=return_obj)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        note   = request.POST.get('note', '').strip()
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        response_message = ''

        def _return_snapshot_payload(msg=''):
            return_obj.refresh_from_db()
            next_adv = [
                {'code': s, 'label': str(dict(Return.STATUS_CHOICES).get(s, s))}
                for s in return_obj.get_allowed_next_statuses()
                if s != Return.STATUS_REJECTED
            ]
            show_reject = return_obj.status in [
                Return.STATUS_REQUESTED,
                Return.STATUS_REVIEWING,
            ]
            return {
                'success': True,
                'action': action,
                'message': msg,
                'status': return_obj.status,
                'status_display': return_obj.get_status_display(),
                'refund_status': return_obj.refund_status,
                'refund_status_display': return_obj.get_refund_status_display(),
                'stock_status': return_obj.stock_status,
                'stock_status_display': return_obj.get_stock_status_display(),
                'refund_amount': str(return_obj.refund_amount),
                'updated_at': return_obj.updated_at.strftime('%Y-%m-%d %H:%M'),
                'next_statuses': next_adv,
                'show_reject_button': show_reject,
                'timeline_html': render_return_timeline_html(return_obj),
            }

        try:
            if action == 'advance':
                new_status = request.POST.get('new_status', '')
                advance_return(return_obj, new_status, actor=request.user, note=note)
                response_message = f'تم تحديث حالة المرتجع إلى: {return_obj.get_status_display()}'
                messages.success(request, f'تم تحديث حالة المرتجع إلى: {return_obj.get_status_display()}')
            elif action == 'reject':
                reject_return(return_obj, note=note, actor=request.user)
                response_message = 'تم رفض المرتجع.'
                messages.success(request, 'تم رفض المرتجع.')
            elif action == 'update_notes':
                return_obj.admin_notes = request.POST.get('admin_notes', '')
                new_refund = request.POST.get('refund_amount', '')
                if new_refund:
                    from decimal import Decimal
                    return_obj.refund_amount = Decimal(new_refund)
                return_obj.save()
                if is_ajax:
                    payload = _return_snapshot_payload('تم تحديث الملاحظات.')
                    payload['admin_notes'] = return_obj.admin_notes or ''
                    return JsonResponse(payload)
                messages.success(request, 'تم تحديث الملاحظات.')
        except ReturnTransitionError as e:
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(request, str(e))

        if is_ajax:
            return JsonResponse(_return_snapshot_payload(response_message))
        return redirect('manage:return_detail', pk=pk)

    next_statuses = [
        (s, dict(Return.STATUS_CHOICES).get(s, s))
        for s in return_obj.get_allowed_next_statuses()
        if s != Return.STATUS_REJECTED
    ]

    return render(request, 'manage/return_detail.html', {
        'return_obj':    return_obj,
        'history':       history,
        'next_statuses': next_statuses,
        'status_icons':  RETURN_STATUS_ICONS,
        'refund_icons':  REFUND_STATUS_ICONS,
        'return_timeline': build_return_timeline(return_obj),
    })


@_staff_required
def return_detail_live_state(request, pk):
    """GET — polling خفيف لحالة المرتجع في لوحة الإدارة بدون reload."""
    from .models import ReturnStatusHistory
    from .return_engine import build_return_timeline, render_return_timeline_html

    return_obj = get_object_or_404(
        Return.objects.select_related('order', 'user').prefetch_related(
            Prefetch(
                'status_history',
                queryset=ReturnStatusHistory.objects.select_related('changed_by').order_by('created_at'),
            ),
        ),
        pk=pk,
    )
    next_statuses = [
        {'code': s, 'label': str(dict(Return.STATUS_CHOICES).get(s, s))}
        for s in return_obj.get_allowed_next_statuses()
        if s != Return.STATUS_REJECTED
    ]
    signature = '|'.join([
        str(return_obj.status or ''),
        str(return_obj.refund_status or ''),
        str(return_obj.stock_status or ''),
        return_obj.updated_at.isoformat() if return_obj.updated_at else '',
    ])
    return JsonResponse({
        'success': True,
        'signature': signature,
        'status': return_obj.status or '',
        'status_display': return_obj.get_status_display(),
        'refund_status': return_obj.refund_status or '',
        'refund_status_display': return_obj.get_refund_status_display(),
        'stock_status': return_obj.stock_status or '',
        'stock_status_display': return_obj.get_stock_status_display(),
        'next_statuses': next_statuses,
        'show_reject_button': return_obj.status in [
            Return.STATUS_REQUESTED,
            Return.STATUS_REVIEWING,
        ],
        'timeline_html': render_return_timeline_html(return_obj),
    })


# ——— الخصومات / العروض / الكوبونات ———

@_staff_required
def promotion_list(request):
    items = Promotion.objects.all().prefetch_related('products', 'variants')
    search = request.GET.get('search', '').strip()
    if search:
        items = items.filter(Q(name__icontains=search) | Q(description__icontains=search))

    items = (
        items.annotate(
            products_count=Count('products', distinct=True),
            variants_count=Count('variants', distinct=True),
        )
        .order_by('-updated_at', 'id')
    )

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items_page = paginator.page(page)
    except PageNotAnInteger:
        items_page = paginator.page(1)
    except EmptyPage:
        items_page = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)

    # حالة العرض الحالية حسب التاريخ (حتى لو admin ما عدلش is_active)
    now = timezone.now()
    for item in items_page:
        is_currently_active = bool(item.is_active)
        if item.start_at and now < item.start_at:
            is_currently_active = False
        if item.end_at and now > item.end_at:
            is_currently_active = False
        item.is_currently_active = is_currently_active

    # إحصائيات الاستخدام/المبيعات حسب سطور OrderItem التي تم ربطها بالعرض وقت الطلب
    promo_ids = [item.id for item in items_page]
    sold_quantity_by_promo = {pid: 0 for pid in promo_ids}
    users_key_by_promo: dict[int, set[str]] = {pid: set() for pid in promo_ids}

    if promo_ids:
        order_items_qs = (
            OrderItem.objects.filter(
                applied_promotion_id__in=promo_ids
            )
            .exclude(order__status=Order.STATUS_CANCELLED)
            .select_related('order')
            .only('applied_promotion_id', 'quantity', 'order__user_id', 'order__customer_phone')
        )

        for oi in order_items_qs:
            pid = oi.applied_promotion_id
            if not pid:
                continue
            sold_quantity_by_promo[pid] = sold_quantity_by_promo.get(pid, 0) + int(oi.quantity or 0)

            order = oi.order
            if order and order.user_id:
                users_key_by_promo[pid].add(f"user:{order.user_id}")
            else:
                guest_phone = (getattr(order, 'customer_phone', '') or '').strip()
                if guest_phone:
                    users_key_by_promo[pid].add(f"guest:{guest_phone}")

    for item in items_page:
        item.users_count = len(users_key_by_promo.get(item.id, set()))
        item.sold_products_count = sold_quantity_by_promo.get(item.id, 0)

    return render(request, 'manage/promotion_list.html', {
        'items': items_page,
        'search_query': search,
        'query_string': q.urlencode(),
    })


@_staff_required
def promotion_add(request):
    form = PromotionForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم إضافة العرض.'))
        return redirect('manage:promotion_list')
    return render(request, 'manage/promotion_form.html', {'form': form, 'title': _('إضافة عرض')})


@_staff_required
def promotion_edit(request, pk):
    obj = get_object_or_404(Promotion, pk=pk)
    form = PromotionForm(request.POST or None, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم تحديث العرض.'))
        return redirect('manage:promotion_list')
    return render(request, 'manage/promotion_form.html', {'form': form, 'title': _('تعديل عرض'), 'obj': obj})


@_staff_required
def promotion_delete(request, pk):
    obj = get_object_or_404(Promotion, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, _('تم حذف العرض.'))
        return redirect('manage:promotion_list')
    return render(request, 'manage/confirm_delete.html', {
        'obj': obj,
        'back_url': 'manage:promotion_list',
        'name': obj.name,
    })


@_staff_required
@require_POST
def promotion_toggle_active(request, pk):
    obj = get_object_or_404(Promotion, pk=pk)
    obj.is_active = not obj.is_active
    obj.save(update_fields=['is_active'])
    now = timezone.now()

    is_currently_active = bool(obj.is_active)
    if obj.start_at and now < obj.start_at:
        is_currently_active = False
    if obj.end_at and now > obj.end_at:
        is_currently_active = False

    if is_currently_active:
        badge_text = '✓ نشط'
        badge_class = 'badge-active'
    else:
        if obj.is_active:
            badge_text = '⏳ منتهي (التاريخ)'
        else:
            badge_text = '✗ غير نشط'
        badge_class = 'badge-inactive'

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'id': obj.id,
            'is_active': obj.is_active,
            'is_currently_active': is_currently_active,
            'badge_text': badge_text,
            'badge_class': badge_class,
        })

    status = _('تم تعطيل العرض') if not obj.is_active else _('تم تفعيل العرض')
    messages.success(request, f"{status}: {obj.name}")
    return redirect('manage:promotion_list')


@_staff_required
def coupon_list(request):
    now = timezone.now()
    items = Coupon.objects.all().annotate(used_users_count=Count('redemptions', distinct=True))
    search = request.GET.get('search', '').strip()
    if search:
        items = items.filter(code__icontains=search)

    items = items.order_by('-updated_at', 'id')

    paginator = Paginator(items, 25)
    page = request.GET.get('page', 1)
    try:
        items_page = paginator.page(page)
    except PageNotAnInteger:
        items_page = paginator.page(1)
    except EmptyPage:
        items_page = paginator.page(paginator.num_pages)

    q = request.GET.copy()
    q.pop('page', None)

    # تجهيـز بيانات إضافية لعرض حد الاستخدام/المستخدمين + تعطيل تلقائي
    for item in items_page:
        allowed_users = int(item.max_uses_total or 0)
        used_users = int(getattr(item, 'used_users_count', 0) or 0)
        item.allowed_users = allowed_users
        item.used_users = used_users
        item.remaining_users = max(allowed_users - used_users, 0)

        # تعطيل تلقائي إذا تم استهلاك الحد (حتى لو admin لم يفتح/لم يتم تطبيق الكوبون مؤخراً)
        if item.is_active and allowed_users > 0 and used_users >= allowed_users:
            Coupon.objects.filter(pk=item.pk, is_active=True).update(is_active=False)
            item.is_active = False

        is_currently_active = bool(item.is_active)
        if item.start_at and now < item.start_at:
            is_currently_active = False
        if item.end_at and now > item.end_at:
            is_currently_active = False
        if allowed_users > 0 and used_users >= allowed_users:
            is_currently_active = False
        item.is_currently_active = is_currently_active

    # إحصائيات "المبيعات" المرتبطة بالكوبون:
    # - الربط يعتمد على CouponRedemption (user/guest_phone) وربطها بآخر Order قبل redeemed_at
    import bisect

    from django.db.models import Sum

    from .models import CouponRedemption  # local import to keep module load light

    coupon_ids = [getattr(item, "id", None) for item in items_page]
    coupon_ids = [cid for cid in coupon_ids if cid]

    for item in items_page:
        item.sold_products_count = 0

    if coupon_ids:
        redemptions = (
            CouponRedemption.objects.filter(coupon_id__in=coupon_ids)
            .only('coupon_id', 'user_id', 'guest_phone', 'redeemed_at', 'id')
            .order_by('coupon_id', 'redeemed_at')
        )

        # تجهيز مفاتيح الطلبات الممكنة (حسب user أو guest_phone)
        user_keys = {}
        phone_keys = {}
        redemptions_list = list(redemptions)
        for r in redemptions_list:
            # بعض السجلات القديمة قد تحتوي redeemed_at = None (أو مفاتيح غير مبدوءة)
            if not r.redeemed_at:
                continue

            if r.user_id:
                prev = user_keys.get(r.user_id)
                if not prev or r.redeemed_at > prev:
                    user_keys[r.user_id] = r.redeemed_at
            elif r.guest_phone:
                prev = phone_keys.get(r.guest_phone)
                if not prev or r.redeemed_at > prev:
                    phone_keys[r.guest_phone] = r.redeemed_at

        # جلب Orders (مستبعد cancelled) لكل مفتاح مع created_at <= max(redeemed_at)
        orders_by_user = {}
        if user_keys:
            latest_user_redeem_at = max(user_keys.values()) if user_keys.values() else timezone.now()
            order_qs = (
                Order.objects.filter(
                    user_id__in=list(user_keys.keys()),
                    created_at__lte=latest_user_redeem_at,
                )
                .exclude(status=Order.STATUS_CANCELLED)
                .only('id', 'user_id', 'created_at', 'status')
                .order_by('user_id', 'created_at')
            )
            for o in order_qs:
                orders_by_user.setdefault(o.user_id, []).append(o)

        orders_by_phone = {}
        if phone_keys:
            latest_guest_redeem_at = max(phone_keys.values()) if phone_keys.values() else timezone.now()
            order_qs = (
                Order.objects.filter(
                    customer_phone__in=list(phone_keys.keys()),
                    created_at__lte=latest_guest_redeem_at,
                )
                .exclude(status=Order.STATUS_CANCELLED)
                .only('id', 'customer_phone', 'created_at', 'status')
                .order_by('customer_phone', 'created_at')
            )
            for o in order_qs:
                orders_by_phone.setdefault(o.customer_phone, []).append(o)

        # اختيار Order لكل redemption ثم حساب مجموع قطع الطلب
        order_ids_by_coupon: dict[int, set[int]] = {cid: set() for cid in coupon_ids}

        for r in redemptions_list:
            chosen_order = None
            if r.user_id:
                candidates = orders_by_user.get(r.user_id) or []
                # نأخذ آخر order.created_at <= redeemed_at
                created_times = [o.created_at for o in candidates]
                idx = bisect.bisect_right(created_times, r.redeemed_at) - 1
                if idx >= 0:
                    chosen_order = candidates[idx]
            else:
                candidates = orders_by_phone.get(r.guest_phone) or []
                created_times = [o.created_at for o in candidates]
                idx = bisect.bisect_right(created_times, r.redeemed_at) - 1
                if idx >= 0:
                    chosen_order = candidates[idx]

            if chosen_order:
                order_ids_by_coupon[r.coupon_id].add(int(chosen_order.id))

        all_order_ids = set()
        for s in order_ids_by_coupon.values():
            all_order_ids |= s

        if all_order_ids:
            qty_by_order = (
                OrderItem.objects.filter(order_id__in=list(all_order_ids))
                .values('order_id')
                .annotate(qty_sum=Sum('quantity'))
            )
            qty_map = {row['order_id']: int(row['qty_sum'] or 0) for row in qty_by_order}

            for cid, oid_set in order_ids_by_coupon.items():
                total_qty = 0
                for oid in oid_set:
                    total_qty += qty_map.get(oid, 0)
                # ضع القيمة في الـ item المناسب
                for item in items_page:
                    if item.id == cid:
                        item.sold_products_count = total_qty

    return render(request, 'manage/coupon_list.html', {
        'items': items_page,
        'search_query': search,
        'query_string': q.urlencode(),
    })


@_staff_required
def coupon_add(request):
    form = CouponForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم إضافة الكوبون.'))
        return redirect('manage:coupon_list')
    return render(request, 'manage/coupon_form.html', {
        'form': form,
        'title': _('إضافة كوبون'),
        'used_users_count': None,
        'remaining_users': None,
    })


@_staff_required
def coupon_edit(request, pk):
    obj = get_object_or_404(Coupon, pk=pk)
    form = CouponForm(request.POST or None, instance=obj)
    if form.is_valid():
        form.save()
        messages.success(request, _('تم تحديث الكوبون.'))
        return redirect('manage:coupon_list')
    allowed_users = int(obj.max_uses_total or 0)
    used_users_count = obj.redemptions.count()
    remaining_users = max(allowed_users - used_users_count, 0)

    return render(request, 'manage/coupon_form.html', {
        'form': form,
        'title': _('تعديل كوبون'),
        'obj': obj,
        'used_users_count': used_users_count,
        'remaining_users': remaining_users,
        'allowed_users': allowed_users,
    })


@_staff_required
def coupon_delete(request, pk):
    obj = get_object_or_404(Coupon, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, _('تم حذف الكوبون.'))
        return redirect('manage:coupon_list')
    return render(request, 'manage/confirm_delete.html', {
        'obj': obj,
        'back_url': 'manage:coupon_list',
        'name': obj.code,
    })


@_staff_required
@require_POST
def coupon_toggle_active(request, pk):
    obj = get_object_or_404(Coupon, pk=pk)
    obj.is_active = not obj.is_active
    obj.save(update_fields=['is_active'])
    now = timezone.now()

    allowed_users = int(obj.max_uses_total or 0)
    used_users = obj.redemptions.count()
    remaining_users = max(allowed_users - used_users, 0)

    # تعطيل تلقائي إذا تم استهلاك الحد
    if obj.is_active and allowed_users > 0 and used_users >= allowed_users:
        if obj.is_active:
            obj.is_active = False
            obj.save(update_fields=['is_active'])

    is_currently_active = bool(obj.is_active)
    if obj.start_at and now < obj.start_at:
        is_currently_active = False
    if obj.end_at and now > obj.end_at:
        is_currently_active = False
    if allowed_users > 0 and used_users >= allowed_users:
        is_currently_active = False

    if is_currently_active:
        badge_text = '✓ نشط'
        badge_class = 'badge-active'
    else:
        if remaining_users == 0 and allowed_users > 0:
            badge_text = '⛔ منتهي'
        else:
            badge_text = '✗ غير نشط'
        badge_class = 'badge-inactive'

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'id': obj.id,
            'is_active': obj.is_active,
            'is_currently_active': is_currently_active,
            'allowed_users': allowed_users,
            'used_users': used_users,
            'remaining_users': remaining_users,
            'badge_text': badge_text,
            'badge_class': badge_class,
        })

    status = _('تم تعطيل الكوبون') if not obj.is_active else _('تم تفعيل الكوبون')
    messages.success(request, f"{status}: {obj.code}")
    return redirect('manage:coupon_list')

