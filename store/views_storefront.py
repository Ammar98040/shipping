"""
واجهة المتجر (دولاب، سلة، طلبات، مستخدمون) — منفصلة عن الدعم والـ webhooks.
"""
import re
import secrets
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .cart import Cart
from .forms import ContactForm
from .forms_auth import UserLoginForm, UserRegisterForm
from .forms_profile import AddressForm, UserProfileForm
from .models import (
    Address,
    Category,
    Compartment,
    EmailOTP,
    Order,
    OrderItem,
    Product,
    ProductGalleryImage,
    Promotion,
    ProductVariant,
    Return,
    ReturnItem,
    ReturnStatusHistory,
    Review,
    Shelf,
    UserProfile,
    Wishlist,
)


# رسائل الكوبون (واجهة العميل) — بدون إشارة لرقم ضيف؛ كوبونات الخصم للمسجلين فقط
STOREFRONT_COUPON_DENIED_GUEST_MSG = 'يجب تسجيل الدخول لاستخدام كوبونات الخصم.'
STOREFRONT_COUPON_INVALID_LOGGED_MSG = (
    'تعذر تطبيق الكوبون: الرمز غير صالح أو منتهي، أو غير مناسب لهذه السلة، أو تم استخدامه مسبقاً من حسابك.'
)


def _public_absolute_url(request, path: str) -> str:
    """رابط قابل للمشاركة: يستخدم PUBLIC_BASE_URL إن وُجد."""
    base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


def _variants_for_teaser_prefetch():
    """نسخ نشطة فقط، حقول الحد الأدنى لحساب is_distinct_customer_choice."""
    return Prefetch(
        'variants',
        queryset=ProductVariant.objects.filter(is_active=True).only(
            'id', 'product_id', 'title', 'color_name', 'color_hex', 'is_active',
        ),
    )


def _attach_storefront_listing_state(products_page):
    """إلحاق حالة عرض المتجر: التلميح + سعر/مخزون موحّدين في القوائم."""
    if products_page is None:
        return
    from decimal import Decimal

    from .discount_engine import preview_best_unit_price_for_product
    for p in products_page:
        distinct = [v for v in p.variants.all() if v.is_distinct_customer_choice]
        n = len(distinct)
        gallery_count = getattr(p, 'gallery_count', None)
        if gallery_count is None:
            gallery_count = len(getattr(p, 'gallery_images').all()) if hasattr(p, 'gallery_images') else 0
        gallery_extra = int(gallery_count or 0) > 1
        # نسخة ظاهرة للعميل، أو أكثر من صورة في المعرض العام → تلميح «اكتشف المزيد»
        p.has_storefront_variants = n >= 1 or gallery_extra
        if n >= 1:
            primary = distinct[0]
            p.listing_price = primary.effective_price
            p.listing_stock = int(primary.stock_quantity or 0)
        else:
            p.listing_price = p.price
            p.listing_stock = int(p.stock or 0)

        # عرض السعر الأصلي + بعد خصم عروض المنتجات (بدون كوبون) في القوائم
        prev = preview_best_unit_price_for_product(
            product=p,
            variant_id=(int(distinct[0].id) if n >= 1 else None),
            base_unit_price=Decimal(str(p.listing_price)),
            quantity=1,
        )
        p.listing_price_original = p.listing_price
        p.listing_price_discounted = prev["unit_price_final"]
        p.listing_discount_label = prev.get("discount_label")
        p.has_listing_discount = bool(prev["discount_amount"] and prev["discount_amount"] > 0)


def _match_product_from_path(path_text: str):
    """استخراج منتج من مسار رابط (/p/slug أو /product/<id>/)."""
    if not path_text:
        return None
    path = unquote(path_text).strip()
    if not path:
        return None

    by_id = re.search(r'/product/(?P<id>\d+)(?:/|$)', path)
    if by_id:
        return Product.objects.filter(pk=int(by_id.group('id')), is_active=True).first()

    by_slug = re.search(r'/p/(?P<slug>[^/?#]+)(?:/|$)', path)
    if by_slug:
        return Product.objects.filter(slug=by_slug.group('slug').strip(), is_active=True).first()
    return None


def _resolve_product_from_query(query_text: str):
    """يدعم البحث برابط منتج كامل أو مسار مختصر."""
    q = (query_text or '').strip()
    if not q:
        return None

    # 1) مسار مباشر مكتوب داخل البحث
    p = _match_product_from_path(q)
    if p:
        return p

    # 2) رابط كامل: https://domain/.../p/slug أو /product/id
    if q.lower().startswith(('http://', 'https://')):
        try:
            parsed = urlparse(q)
            p = _match_product_from_path(parsed.path)
            if p:
                return p
        except Exception:
            return None

    return None


def wardrobe_view(request):
    """الصفحة الرئيسية: عرض الدولاب (الخانات الأربع)."""
    compartments = Compartment.objects.filter(is_active=True).order_by('order')
    return render(request, 'store/wardrobe.html', {'compartments': compartments})


def compartment_view(request, compartment_id):
    """صفحة خانة واحدة: عرض الرفوف."""
    compartment = get_object_or_404(Compartment, pk=compartment_id, is_active=True)
    shelves = compartment.shelves.filter(is_active=True).order_by('order')
    return render(request, 'store/compartment.html', {
        'compartment': compartment,
        'shelves': shelves,
    })


def shelf_view(request, shelf_id):
    """صفحة رف واحد: عرض الأصناف."""
    shelf = get_object_or_404(Shelf, pk=shelf_id, is_active=True)
    categories = shelf.categories.filter(is_active=True).order_by('order')
    return render(request, 'store/shelf.html', {
        'shelf': shelf,
        'categories': categories,
    })


def category_view(request, category_id):
    """صفحة صنف واحد: عرض المنتجات."""
    category = get_object_or_404(Category, pk=category_id, is_active=True)
    products_list = (
        category.products.filter(is_active=True)
        .order_by('order')
        .annotate(gallery_count=Count('gallery_images', distinct=True))
        .prefetch_related(_variants_for_teaser_prefetch())
    )

    paginator = Paginator(products_list, 12)
    page = request.GET.get('page', 1)

    try:
        products = paginator.page(page)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    _attach_storefront_listing_state(products)

    # قائمة المنتجات في المفضلة والسلة
    wishlist_product_ids = []
    if request.user.is_authenticated:
        wishlist_product_ids = list(Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True))

    cart = Cart(request)
    cart_product_ids = [int(item['product'].id) for item in cart]

    return render(request, 'store/category.html', {
        'category': category,
        'products': products,
        'wishlist_product_ids': wishlist_product_ids,
        'cart_product_ids': cart_product_ids,
    })


def _build_products_promo_strip_items():
    """بناء عناصر شريط العروض لصفحة كل المنتجات (عروض فقط بدون كوبونات)."""
    now = timezone.now()
    active_promotions = list(
        Promotion.objects.filter(is_active=True)
        .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
        .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
        .prefetch_related('compartments', 'shelves', 'categories', 'products', 'variants__product')
        .order_by('-updated_at', 'id')[:12]
    )

    promo_strip_items = []

    def _fmt_discount(val):
        s = str(val or '').strip()
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        return s

    for promo in active_promotions:
        target_url = reverse('products_all')
        target_hint = "عرض على كل المنتجات"
        scope_target_name = "كل المنتجات"
        bg_image_url = ''
        if promo.scope == Promotion.SCOPE_COMPARTMENTS:
            comp = promo.compartments.first()
            if comp:
                target_url = reverse('compartment', args=[comp.id])
                target_hint = f"انتقل إلى خانة: {comp.name_ar}"
                scope_target_name = comp.name_ar
                if getattr(comp, 'image', None):
                    bg_image_url = comp.image.url
        elif promo.scope == Promotion.SCOPE_SHELVES:
            shelf = promo.shelves.first()
            if shelf:
                target_url = reverse('shelf', args=[shelf.id])
                target_hint = f"انتقل إلى رف: {shelf.name_ar}"
                scope_target_name = shelf.name_ar
                if getattr(shelf, 'image', None):
                    bg_image_url = shelf.image.url
        elif promo.scope == Promotion.SCOPE_CATEGORIES:
            category = promo.categories.first()
            if category:
                target_url = reverse('category', args=[category.id])
                target_hint = f"انتقل إلى صنف: {category.name_ar}"
                scope_target_name = category.name_ar
                if getattr(category, 'image', None):
                    bg_image_url = category.image.url
        elif promo.scope == Promotion.SCOPE_PRODUCTS:
            product = promo.products.first()
            if product:
                target_url = reverse('product', args=[product.id])
                target_hint = f"انتقل إلى المنتج: {product.name_ar}"
                scope_target_name = product.name_ar
                if getattr(product, 'image', None):
                    bg_image_url = product.image.url
        elif promo.scope == Promotion.SCOPE_VARIANTS:
            variant = promo.variants.first()
            if variant and variant.product_id:
                target_url = reverse('product', args=[variant.product_id])
                target_hint = f"انتقل إلى المنتج المرتبط بالنسخة: {variant.product.name_ar}"
                scope_target_name = variant.product.name_ar
                if getattr(variant.product, 'image', None):
                    bg_image_url = variant.product.image.url

        discount_display = (
            f"{_fmt_discount(promo.discount_value)}%"
            if promo.discount_type == Promotion.DISCOUNT_PERCENT
            else f"{_fmt_discount(promo.discount_value)} ر.س"
        )
        promo_strip_items.append(
            {
                'kind': 'promotion',
                'title': f"عرض على {promo.get_scope_display()}",
                'promo_name': promo.name,
                'url': target_url,
                'hint': target_hint,
                'icon': '🏷️',
                'discount_display': discount_display,
                'scope_target_name': scope_target_name,
                'bg_image_url': bg_image_url,
            }
        )
    return promo_strip_items


def products_all_view(request):
    """صفحة كل المنتجات المتوفرة."""
    products_list = (
        Product.objects.filter(
            Q(stock__gt=0) | Q(variants__is_active=True, variants__stock_quantity__gt=0),
            is_active=True,
        )
        .select_related('category__shelf__compartment')
        .order_by('order', 'id')
        .distinct()
        .annotate(gallery_count=Count('gallery_images', distinct=True))
        .prefetch_related(_variants_for_teaser_prefetch())
    )

    paginator = Paginator(products_list, 20)
    page = request.GET.get('page', 1)

    try:
        products = paginator.page(page)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    _attach_storefront_listing_state(products)

    wishlist_product_ids = []
    if request.user.is_authenticated:
        wishlist_product_ids = list(Wishlist.objects.filter(user=request.user).values_list('product_id', flat=True))

    cart = Cart(request)
    cart_product_ids = [int(item['product'].id) for item in cart]

    promo_strip_items = _build_products_promo_strip_items()
    promo_slides = (
        [promo_strip_items[i : i + 3] for i in range(0, len(promo_strip_items), 3)]
        if promo_strip_items
        else []
    )
    return render(request, 'store/products_all.html', {
        'products': products,
        'wishlist_product_ids': wishlist_product_ids,
        'cart_product_ids': cart_product_ids,
        'promo_strip_items': promo_strip_items,
        'promo_slides': promo_slides,
    })


def product_view(request, product_id):
    """صفحة منتج واحد مع التقييمات."""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    if not product.slug:
        product.save()
    variants = product.variants.filter(is_active=True).order_by('sort_order', 'id').prefetch_related('images')
    variants_list = list(variants)
    meaningful_variants = [v for v in variants_list if v.is_distinct_customer_choice]

    product_gallery = list(product.gallery_images.order_by('sort_order', 'id'))
    selected_variant = None
    variant_options = []
    selected_main_image = ''
    # تجهيز بيانات المعرض مع حساب خصم عروض المنتجات (بدون كوبون)
    product_gallery_items = []

    # Thumb للصورة الرئيسية للمنتج (Product.image) حتى يستطيع العميل اختيارها
    if getattr(product, "image", None):
        from decimal import Decimal

        from .discount_engine import preview_best_unit_price_for_product
        main_base_price = Decimal(str(getattr(product, "price", 0) or 0))
        main_prev = preview_best_unit_price_for_product(
            product=product,
            variant_id=None,
            base_unit_price=main_base_price,
            quantity=1,
        )
        product_gallery_items.append({
            'id': '',
            'url': product.image.url,
            'title': product.name_ar,
            'price_original': main_base_price,
            'price_final': main_prev["unit_price_final"],
            'has_offer_discount': bool((main_prev.get("discount_amount") or Decimal("0")) > 0),
            'discount_label': main_prev.get("discount_label"),
            'stock': int(product.stock or 0),
            'code': '',
        })

    for img in product_gallery:
        if not getattr(img, 'image', None):
            continue
        from decimal import Decimal

        from .discount_engine import preview_best_unit_price_for_product
        img_base_price = Decimal(str(img.effective_price or 0))
        img_prev = preview_best_unit_price_for_product(
            product=product,
            variant_id=None,
            base_unit_price=img_base_price,
            quantity=1,
        )
        img_has_offer = bool((img_prev.get("discount_amount") or Decimal("0")) > 0)
        product_gallery_items.append({
            'id': img.id,
            'url': img.image.url,
            'title': img.title or product.name_ar,
            'price_original': img_base_price,
            'price_final': img_prev["unit_price_final"],
            'has_offer_discount': img_has_offer,
            'discount_label': img_prev.get("discount_label"),
            'stock': img.effective_stock,
            'code': img.code,
        })
    primary_gallery = next((img for img in product_gallery if img.is_primary), None) or (product_gallery[0] if product_gallery else None)
    if product.image:
        selected_main_image = product.image.url
    elif primary_gallery and getattr(primary_gallery, 'image', None):
        selected_main_image = primary_gallery.image.url

    selected_variant_id_param = ''
    initial_override_image = False
    if meaningful_variants:
        selected_variant_id_param = request.GET.get('v', '').strip()
        meaningful_ids = {v.id for v in meaningful_variants}
        if selected_variant_id_param.isdigit() and int(selected_variant_id_param) in meaningful_ids:
            pick_id = int(selected_variant_id_param)
            selected_variant = next((v for v in meaningful_variants if v.id == pick_id), None)
        if not selected_variant:
            selected_variant = meaningful_variants[0]
        initial_override_image = bool(selected_variant_id_param.isdigit() and int(selected_variant_id_param) in meaningful_ids)
        for v in meaningful_variants:
            images = list(v.images.all())
            primary_obj = next((img for img in images if img.is_primary), None) or (images[0] if images else None)
            primary_url = primary_obj.image.url if primary_obj and getattr(primary_obj, 'image', None) else selected_main_image

            # عروض المنتجات فقط (بدون كوبون) لكل نسخة لعرضها في الواجهة
            from decimal import Decimal

            from .discount_engine import preview_best_unit_price_for_product
            v_base_price = Decimal(str(v.effective_price or 0))
            v_prev = preview_best_unit_price_for_product(
                product=product,
                variant_id=int(v.id),
                base_unit_price=v_base_price,
                quantity=1,
            )
            v_discount_amount = v_prev.get("discount_amount") or Decimal("0")

            variant_options.append({
                'id': v.id,
                'label': v.customer_variant_button_label,
                'price_original': v_base_price,
                'price_final': v_prev["unit_price_final"],
                'has_offer_discount': v_discount_amount > 0,
                'discount_label': v_prev.get("discount_label"),
                'stock': int(v.stock_quantity or 0),
                'primary_image': primary_url,
                'color_hex': (v.color_hex or '').strip(),
            })
            # لا نغيّر صورة المنتج الأساسية عند اختيار النسخة تلقائياً
            if initial_override_image and selected_variant and v.id == selected_variant.id:
                selected_main_image = primary_url or selected_main_image
        show_variant_picker = len(meaningful_variants) > 0
    else:
        show_variant_picker = False

    page_stock = int(product.stock or 0)
    if selected_variant:
        page_stock = int(selected_variant.stock_quantity or 0)

    # عرض خصومات عروض المنتجات فقط (بدون كوبون)
    from decimal import Decimal

    from .discount_engine import preview_best_unit_price_for_product

    base_unit_price = Decimal(str((selected_variant.effective_price if selected_variant else product.price) or 0))
    variant_id_for_preview = (int(selected_variant.id) if selected_variant else None)
    prev = preview_best_unit_price_for_product(
        product=product,
        variant_id=variant_id_for_preview,
        base_unit_price=base_unit_price,
        quantity=1,
    )

    page_price_original = base_unit_price
    page_price_discounted = prev["unit_price_final"]
    page_has_offer_discount = bool((prev.get("discount_amount") or Decimal("0")) > 0)
    page_offer_discount_label = prev.get("discount_label")

    reviews = product.reviews.select_related('user').order_by('-created_at')

    # فحص إذا كان المستخدم قيّم المنتج
    user_review = None
    if request.user.is_authenticated:
        user_review = reviews.filter(user=request.user).first()

    return render(request, 'store/product.html', {
        'product': product,
        'variants': variants,
        'variant_options': variant_options,
        'show_variant_picker': show_variant_picker,
        'selected_variant': selected_variant,
        'product_gallery_items': product_gallery_items,
        'selected_main_image': selected_main_image,
        # page_price يبقى كما هو (للتوافق)، لكن في القالب نعرض الأصل/المخفض إذا وُجد عرض.
        'page_price': page_price_discounted if page_has_offer_discount else page_price_original,
        'page_price_original': page_price_original,
        'page_price_discounted': page_price_discounted,
        'page_has_offer_discount': page_has_offer_discount,
        'page_offer_discount_label': page_offer_discount_label,
        'page_stock': page_stock,
        'reviews': reviews,
        'user_review': user_review,
        'product_share_url': _public_absolute_url(request, reverse('product_by_slug', args=[product.slug])),
    })


def product_view_by_slug(request, slug):
    """رابط منتج قابل للمشاركة."""
    product = get_object_or_404(Product, slug=slug, is_active=True)
    return redirect('product', product_id=product.id)


# ========== السلة والطلبات ==========

def cart_add(request, product_id):
    """إضافة منتج للسلة."""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    cart = Cart(request)
    quantity = int(request.POST.get('quantity', 1))
    variant_id = (request.POST.get('variant_id') or '').strip()
    selected_gallery_image_id = (request.POST.get('selected_gallery_image_id') or '').strip()
    variant = None
    selected_gallery_image = None
    available_stock = int(product.stock or 0)
    item_label = product.name_ar
    if variant_id.isdigit():
        cand = ProductVariant.objects.filter(pk=int(variant_id), product=product, is_active=True).first()
        if cand is None:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': 'النسخة المحددة غير متاحة.'}, status=400)
            messages.error(request, 'النسخة المحددة غير متاحة.')
            return redirect(request.META.get('HTTP_REFERER', 'wardrobe'))
        if cand.is_distinct_customer_choice:
            variant = cand
    if variant:
        available_stock = int(variant.stock_quantity or 0)
        item_label = f"{product.name_ar} - {variant.color_name}" if variant.color_name else product.name_ar
    elif selected_gallery_image_id.isdigit():
        selected_gallery_image = ProductGalleryImage.objects.filter(pk=int(selected_gallery_image_id), product=product).first()
        if selected_gallery_image:
            available_stock = int(selected_gallery_image.effective_stock)
            item_label = selected_gallery_image.title or product.name_ar

    # للطلبات AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if quantity > available_stock:
            return JsonResponse({
                'success': False,
                'message': f'الكمية المطلوبة غير متوفرة. المتوفر: {available_stock}'
            })
        else:
            cart.add(product, quantity, variant=variant, selected_gallery_image=selected_gallery_image)
            return JsonResponse({
                'success': True,
                'message': f'تمت إضافة {item_label} للسلة',
                'cart_count': len(cart),
                'cart_total': float(cart.get_total())
            })

    # للطلبات العادية
    if quantity > available_stock:
        messages.error(request, f'الكمية المطلوبة غير متوفرة. المتوفر: {available_stock}')
    else:
        cart.add(product, quantity, variant=variant, selected_gallery_image=selected_gallery_image)
        messages.success(request, f'تمت إضافة {item_label} للسلة')

    return redirect(request.META.get('HTTP_REFERER', 'wardrobe'))


def cart_view(request):
    """عرض السلة."""
    cart = Cart(request)
    if not request.user.is_authenticated:
        cart.clear_coupon()
    from decimal import Decimal

    from .discount_engine import price_cart

    cart_items = list(cart)
    coupon_code = cart.get_coupon_code()
    guest_phone = cart.get_coupon_guest_phone()
    pricing = price_cart(
        cart_items,
        user=request.user,
        guest_phone=(guest_phone or None),
        coupon_code=(coupon_code or None),
    )

    # سطور للعرض: نبدّل totals حسب الخصومات
    cart_rows = []
    for idx, item in enumerate(cart_items):
        line = pricing['lines'][idx]
        unit_final = line['unit_price_final']
        cart_rows.append({
            **item,
            'price_original': Decimal(str(item.get('price') or 0)),
            'price_final': unit_final,
            'total': line['line_total_final'],
            'has_line_discount': bool(line['offer_discount_allocated'] or line.get('coupon_discount_allocated')),
        })

    # فحص إذا كان هناك منتج غير متوفر بالكمية المطلوبة
    has_stock_issue = False
    for item in cart_items:
        if item['available_stock'] < item['quantity']:
            has_stock_issue = True
            break

    return render(request, 'store/cart.html', {
        'cart': cart_rows,
        'has_stock_issue': has_stock_issue
        ,
        'cart_subtotal_original': Decimal(str(Cart(request).get_total())),
        'cart_subtotal_discounted': pricing['final_subtotal'],
        'product_discount_total': pricing['product_discount_total'],
        'coupon_discount_total': pricing['coupon_discount_total'],
        'applied_coupon_code': pricing.get('applied_coupon_code'),
        'coupon_code_input': coupon_code,
        'coupon_guest_phone_input': guest_phone,
    })


@require_POST
def cart_coupon_apply(request):
    """تطبيق/تخزين كوبون في السلة (بالجلسة)."""
    cart = Cart(request)
    code = (request.POST.get('coupon_code') or '').strip()

    if not request.user.is_authenticated:
        cart.clear_coupon()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': STOREFRONT_COUPON_DENIED_GUEST_MSG})
        messages.error(request, STOREFRONT_COUPON_DENIED_GUEST_MSG)
        return redirect('cart_view')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from decimal import Decimal

        from .discount_engine import price_cart

        cart_items = list(cart)
        coupon_code_input = code if code else None

        # حساب السعر مع (أو بدون) الكوبون — للمسجلين فقط
        pricing = price_cart(
            cart_items,
            user=request.user,
            guest_phone=None,
            coupon_code=coupon_code_input,
        )

        applied_coupon_code = pricing.get('applied_coupon_code')
        if applied_coupon_code:
            cart.set_coupon(code=applied_coupon_code, guest_phone='')
            success = True
            message = 'تم الخصم بنجاح.'
        else:
            cart.clear_coupon()
            success = False
            if not code:
                success = True
                message = 'تم إزالة الكوبون.'
            else:
                message = STOREFRONT_COUPON_INVALID_LOGGED_MSG

        line_updates = []
        for idx, line in enumerate(pricing['lines']):
            src_item = cart_items[idx]
            unit_original: Decimal
            if src_item.get('variant'):
                unit_original = Decimal(str(src_item['variant'].effective_price))
            elif src_item.get('selected_gallery_image'):
                unit_original = Decimal(str(src_item['selected_gallery_image'].effective_price))
            else:
                unit_original = Decimal(str(src_item['product'].price))

            line_updates.append({
                'cart_key': src_item.get('cart_key'),
                'quantity': src_item.get('quantity'),
                'item_total': float(line['line_total_final']),
                'unit_price_original': float(unit_original),
                'unit_price_final': float(line['unit_price_final']),
                'has_line_discount': bool(line.get('offer_discount_allocated')) or bool(line.get('coupon_discount_allocated')),
            })

        return JsonResponse({
            'success': success,
            'message': message,
            'applied_coupon_code': applied_coupon_code,
            'product_discount_total': float(pricing['product_discount_total']),
            'coupon_discount_total': float(pricing['coupon_discount_total']),
            'cart_count': cart.get_items_count(),
            'cart_total': float(pricing['final_subtotal']),
            'line_updates': line_updates,
        })

    if not code:
        cart.clear_coupon()
        messages.success(request, 'تم إزالة الكوبون.')
        return redirect('cart_view')

    from .discount_engine import price_cart
    pricing = price_cart(list(cart), user=request.user, guest_phone=None, coupon_code=code)
    if pricing.get('applied_coupon_code'):
        cart.set_coupon(code=pricing['applied_coupon_code'], guest_phone='')
        messages.success(request, f'تم تطبيق الكوبون: {pricing["applied_coupon_code"]}')
    else:
        cart.clear_coupon()
        messages.error(request, STOREFRONT_COUPON_INVALID_LOGGED_MSG)

    return redirect('cart_view')


@require_POST
def cart_share_create(request):
    """إنشاء رابط مشاركة للسلة الحالية."""
    cart = Cart(request)
    if len(cart) == 0:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'السلة فارغة'}, status=400)
        messages.warning(request, 'لا يمكن مشاركة سلة فارغة.')
        return redirect('cart_view')

    from .models import CartShare, CartShareItem
    token = secrets.token_urlsafe(10)
    while CartShare.objects.filter(token=token).exists():
        token = secrets.token_urlsafe(10)

    share = CartShare.objects.create(
        token=token,
        created_by=request.user if request.user.is_authenticated else None,
        is_active=True,
    )

    for item in cart:
        CartShareItem.objects.create(
            cart_share=share,
            product=item['product'],
            variant=item.get('variant'),
            quantity=item['quantity'],
            price_snapshot=item.get('variant').effective_price if item.get('variant') else item['product'].price,
        )

    share_url = _public_absolute_url(request, reverse('cart_share_view', args=[share.token]))
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'share_url': share_url})
    messages.success(request, 'تم إنشاء رابط مشاركة السلة.')
    return redirect('cart_share_view', token=share.token)


def cart_share_view(request, token):
    """عرض محتوى سلة مشتركة."""
    from .models import CartShare
    share = get_object_or_404(CartShare.objects.prefetch_related('items__product'), token=token, is_active=True)

    if share.last_viewed_at is None:
        share.views_count = share.views_count + 1
    else:
        share.views_count = share.views_count + 1
    share.last_viewed_at = timezone.now()
    share.save(update_fields=['views_count', 'last_viewed_at'])

    rows = []
    total = 0.0
    for row in share.items.all():
        product = row.product
        variant = row.variant
        qty = int(row.quantity or 0)
        stock_qty = int(variant.stock_quantity) if variant else int(product.stock)
        unit = float(variant.effective_price if variant else product.price)
        subtotal = unit * qty
        rows.append({
            'product': product,
            'variant': variant,
            'quantity': qty,
            'unit_price': unit,
            'subtotal': subtotal,
            'available': product.is_active and stock_qty > 0,
        })
        total += subtotal

    return render(request, 'store/cart_share.html', {
        'share': share,
        'rows': rows,
        'rows_total': total,
    })


@require_POST
def cart_share_apply(request, token):
    """تطبيق سلة مشاركة على سلة المستخدم الحالية (merge أو replace)."""
    from .models import CartShare
    share = get_object_or_404(CartShare.objects.prefetch_related('items__product'), token=token, is_active=True)
    mode = (request.POST.get('mode') or 'merge').strip().lower()
    if mode not in ('merge', 'replace'):
        mode = 'merge'

    cart = Cart(request)
    if mode == 'replace':
        cart.clear()
        cart = Cart(request)

    applied_count = 0
    skipped_count = 0
    for item in share.items.all():
        product = item.product
        variant = item.variant
        stock_qty = int(variant.stock_quantity) if variant else int(product.stock)
        if (not product.is_active) or stock_qty <= 0:
            skipped_count += 1
            continue

        qty = max(1, int(item.quantity or 1))
        cart_key = Cart.make_key(product.id, variant.id if variant else None)
        existing_qty = int(cart.cart.get(cart_key, {}).get('quantity', 0))
        if mode == 'merge':
            target_qty = existing_qty + qty
        else:
            target_qty = qty
        final_qty = min(target_qty, stock_qty)
        if final_qty <= 0:
            skipped_count += 1
            continue
        if cart_key not in cart.cart:
            cart.add(product, final_qty, variant=variant)
        else:
            cart.update(cart_key, final_qty)
        applied_count += 1

    share.applied_count = share.applied_count + 1
    share.save(update_fields=['applied_count'])

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if applied_count:
        if mode == 'replace':
            success_msg = f'تم استبدال السلة من الرابط وإضافة {applied_count} منتج.'
            messages.success(request, success_msg)
        else:
            success_msg = f'تم دمج سلة الرابط وإضافة {applied_count} منتج.'
            messages.success(request, success_msg)
    else:
        success_msg = 'لم تتم إضافة عناصر جديدة من الرابط.'
    if skipped_count:
        warn_msg = f'تم تجاهل {skipped_count} منتج غير متاح حالياً.'
        messages.warning(request, warn_msg)
    else:
        warn_msg = ''
    if is_ajax:
        return JsonResponse({
            'success': True,
            'applied_count': applied_count,
            'skipped_count': skipped_count,
            'message': success_msg,
            'warning': warn_msg,
            'redirect_url': reverse('cart_view'),
        })
    return redirect('cart_view')


def cart_update(request, product_id):
    """تحديث كمية منتج في السلة."""
    if request.method == 'POST':
        cart = Cart(request)
        product = get_object_or_404(Product, pk=product_id, is_active=True)
        cart_key = (request.POST.get('cart_key') or '').strip()
        variant_id = (request.POST.get('variant_id') or '').strip()
        variant = None
        if variant_id.isdigit():
            variant = ProductVariant.objects.filter(pk=int(variant_id), product=product, is_active=True).first()
        try:
            quantity = int(request.POST.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1
        quantity = max(1, quantity)
        selected_gallery_image = None
        selected_gallery_image_id = (request.POST.get('selected_gallery_image_id') or '').strip()
        if not variant and selected_gallery_image_id.isdigit():
            selected_gallery_image = ProductGalleryImage.objects.filter(pk=int(selected_gallery_image_id), product=product).first()
        stock_qty = int(variant.stock_quantity) if variant else int(selected_gallery_image.effective_stock if selected_gallery_image else product.stock)
        quantity = min(quantity, stock_qty)
        if not cart_key:
            cart_key = Cart.make_key(product.id, variant.id if variant else None, selected_gallery_image.id if selected_gallery_image else None)
        cart.update(cart_key, quantity)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # أعِد حساب الخصومات للعرض الفوري داخل السلة
            from decimal import Decimal

            from .discount_engine import price_cart

            cart_items = list(cart)
            coupon_code = cart.get_coupon_code() if request.user.is_authenticated else None

            pricing = price_cart(
                cart_items,
                user=request.user,
                guest_phone=None,
                coupon_code=(coupon_code or None),
            )

            line_updates = []
            for idx, line in enumerate(pricing['lines']):
                src_item = cart_items[idx]
                unit_original: Decimal
                if src_item.get('variant'):
                    unit_original = Decimal(str(src_item['variant'].effective_price))
                elif src_item.get('selected_gallery_image'):
                    unit_original = Decimal(str(src_item['selected_gallery_image'].effective_price))
                else:
                    unit_original = Decimal(str(src_item['product'].price))

                line_updates.append({
                    'cart_key': src_item.get('cart_key'),
                    'quantity': src_item.get('quantity'),
                    'item_total': float(line['line_total_final']),
                    'unit_price_original': float(unit_original),
                    'unit_price_final': float(line['unit_price_final']),
                    'has_line_discount': bool(line.get('offer_discount_allocated')) or bool(line.get('coupon_discount_allocated')),
                })

            return JsonResponse({
                'success': True,
                'product_id': int(product_id),
                'cart_key': cart_key,
                'quantity': quantity,
                'cart_count': cart.get_items_count(),  # عدد الأسطر (cart|length)
                'cart_total': float(pricing['final_subtotal']),
                'line_updates': line_updates,
            })
        messages.success(request, 'تم تحديث السلة')
    return redirect('cart_view')


def cart_remove(request, product_id):
    """حذف منتج من السلة."""
    cart = Cart(request)
    cart_key = (request.POST.get('cart_key') or request.GET.get('key') or '').strip()
    if cart_key:
        cart.remove(cart_key)
    else:
        cart.remove(product_id)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from decimal import Decimal

        from .discount_engine import price_cart

        cart_items_count = cart.get_items_count()
        cart_items = list(cart)
        coupon_code = cart.get_coupon_code() if request.user.is_authenticated else None

        pricing = price_cart(
            cart_items,
            user=request.user,
            guest_phone=None,
            coupon_code=(coupon_code or None),
        )

        line_updates = []
        for idx, line in enumerate(pricing['lines']):
            src_item = cart_items[idx]
            unit_original: Decimal
            if src_item.get('variant'):
                unit_original = Decimal(str(src_item['variant'].effective_price))
            elif src_item.get('selected_gallery_image'):
                unit_original = Decimal(str(src_item['selected_gallery_image'].effective_price))
            else:
                unit_original = Decimal(str(src_item['product'].price))

            line_updates.append({
                'cart_key': src_item.get('cart_key'),
                'quantity': src_item.get('quantity'),
                'item_total': float(line['line_total_final']),
                'unit_price_original': float(unit_original),
                'unit_price_final': float(line['unit_price_final']),
                'has_line_discount': bool(line.get('offer_discount_allocated')) or bool(line.get('coupon_discount_allocated')),
            })

        return JsonResponse({
            'success': True,
            'product_id': int(product_id),
            'cart_key': cart_key,
            'cart_count': cart_items_count,
            'cart_total': float(pricing['final_subtotal']),
            'line_updates': line_updates,
        })
    messages.success(request, 'تم حذف المنتج من السلة')
    return redirect('cart_view')


def checkout(request):
    """صفحة إتمام الطلب مع دعم العناوين المحفوظة وطريقة الدفع ورسوم التوصيل."""
    cart = Cart(request)
    if len(cart) == 0:
        messages.warning(request, 'السلة فارغة')
        return redirect('cart_view')

    if not request.user.is_authenticated:
        cart.clear_coupon()

    # حساب المجموع الفرعي ورسوم التوصيل والمجموع الكلي (مع خصومات عروض المنتجات التجريبية)
    from decimal import Decimal

    from .discount_engine import price_cart

    delivery_fee_amount = getattr(settings, 'DELIVERY_FEE', 0)
    try:
        delivery_fee_amount = Decimal(str(delivery_fee_amount))
    except (TypeError, ValueError, ArithmeticError):
        delivery_fee_amount = Decimal('0')

    cart_items = list(cart)
    coupon_code_session = (cart.get_coupon_code() or None) if request.user.is_authenticated else None
    guest_phone_session = None
    pricing_offers = price_cart(
        cart_items,
        user=request.user,
        guest_phone=guest_phone_session,
        coupon_code=coupon_code_session,
    )

    base_subtotal = Decimal(str(cart.get_total()))
    subtotal = base_subtotal
    subtotal_after_product_offers = pricing_offers['subtotal_after_product_offers']
    # بعد خصم عروض المنتجات ثم الكوبون (إن وُجد)
    discounted_subtotal = pricing_offers['final_subtotal']
    subtotal_after_all_discounts = discounted_subtotal
    product_discount_total = pricing_offers['product_discount_total']
    coupon_discount_total = pricing_offers['coupon_discount_total']
    applied_coupon_code = pricing_offers.get('applied_coupon_code')
    coupon_code_input = ''

    total_with_delivery = discounted_subtotal + delivery_fee_amount

    def _build_checkout_cart_rows(pricing: dict) -> list[dict]:
        rows = []
        for idx, line in enumerate(pricing['lines']):
            src = cart_items[idx]
            rows.append({
                'name': src['name'],
                'quantity': src['quantity'],
                'total': line['line_total_final'],
                'unit_price_final': line['unit_price_final'],
                'best_promo_id': line.get('best_promo_id'),
                'product': src['product'],
                'variant': src.get('variant'),
                'selected_gallery_image': src.get('selected_gallery_image'),
            })
        return rows

    checkout_cart_rows = _build_checkout_cart_rows(pricing_offers)

    # للمستخدمين المسجلين: جلب العناوين المحفوظة
    saved_addresses = []
    default_address = None
    if request.user.is_authenticated:
        saved_addresses = Address.objects.filter(user=request.user)
        default_address = saved_addresses.filter(is_default=True).first()

    if request.method == 'POST':
        # فحص إذا اختار عنوان محفوظ
        saved_address_id = request.POST.get('saved_address_id', '').strip()

        if saved_address_id:
            # استخدام عنوان محفوظ
            address_obj = get_object_or_404(Address, pk=saved_address_id, user=request.user)
            name = address_obj.full_name
            phone = address_obj.phone
            email = request.user.email
            address = address_obj.full_address
            if address_obj.additional_info:
                address += f"\n{address_obj.additional_info}"
        else:
            # استخدام بيانات يدوية
            name = request.POST.get('customer_name', '').strip()
            phone = request.POST.get('customer_phone', '').strip()
            email = request.POST.get('customer_email', '').strip()

            # بناء العنوان من الحقول المفصلة
            country = request.POST.get('country', '').strip()
            city = request.POST.get('city', '').strip()
            district = request.POST.get('district', '').strip()
            postal_code = request.POST.get('postal_code', '').strip()
            national_address = request.POST.get('national_address', '').strip()
            street = request.POST.get('street', '').strip()
            building_number = request.POST.get('building_number', '').strip()
            additional_info = request.POST.get('additional_info', '').strip()

            # بناء العنوان الكامل
            address_parts = []
            if country:
                address_parts.append(f"البلد: {country}")
            if city:
                address_parts.append(f"المدينة: {city}")
            if district:
                address_parts.append(f"الحي: {district}")
            if street:
                address_parts.append(f"الشارع: {street}")
            if building_number:
                address_parts.append(f"رقم العمارة: {building_number}")
            if national_address:
                address_parts.append(f"العنوان الوطني: {national_address}")
            if postal_code:
                address_parts.append(f"الرمز البريدي: {postal_code}")
            if additional_info:
                address_parts.append(f"معلومات إضافية: {additional_info}")

            address = "\n".join(address_parts)

        notes = request.POST.get('notes', '').strip()
        payment_method = request.POST.get('payment_method', '').strip()

        # التحقق من اختيار طريقة الدفع
        if not payment_method or payment_method not in [Order.PAYMENT_CASH, Order.PAYMENT_GATEWAY]:
            messages.error(request, 'الرجاء اختيار طريقة الدفع')
            return render(request, 'store/checkout.html', {
                'cart': checkout_cart_rows,
                'saved_addresses': saved_addresses,
                'default_address': default_address,
                'subtotal': subtotal,
                'subtotal_after_product_offers': subtotal_after_product_offers,
                'subtotal_after_all_discounts': subtotal_after_all_discounts,
                'delivery_fee': delivery_fee_amount,
                'total_with_delivery': total_with_delivery,
                'product_discount_total': product_discount_total,
                'coupon_discount_total': coupon_discount_total,
                'applied_coupon_code': applied_coupon_code,
                'coupon_code_input': coupon_code_input,
            })

        # التحقق من الحقول المطلوبة
        if not name or not phone:
            messages.error(request, 'الرجاء ملء الاسم ورقم الجوال')
            return render(request, 'store/checkout.html', {
                'cart': checkout_cart_rows,
                'saved_addresses': saved_addresses,
                'default_address': default_address,
                'subtotal': subtotal,
                'subtotal_after_product_offers': subtotal_after_product_offers,
                'subtotal_after_all_discounts': subtotal_after_all_discounts,
                'delivery_fee': delivery_fee_amount,
                'total_with_delivery': total_with_delivery,
                'product_discount_total': product_discount_total,
                'coupon_discount_total': coupon_discount_total,
                'applied_coupon_code': applied_coupon_code,
                'coupon_code_input': coupon_code_input,
            })

        # التحقق من العنوان (إذا لم يكن عنوان محفوظ، يجب ملء الحقول المطلوبة)
        if not saved_address_id:
            if not city or not street or not building_number or not national_address:
                messages.error(request, 'الرجاء ملء جميع حقول العنوان المطلوبة (المدينة، الشارع، رقم العمارة، العنوان الوطني)')
                return render(request, 'store/checkout.html', {
                    'cart': checkout_cart_rows,
                    'saved_addresses': saved_addresses,
                    'default_address': default_address,
                    'subtotal': subtotal,
                    'subtotal_after_product_offers': subtotal_after_product_offers,
                    'subtotal_after_all_discounts': subtotal_after_all_discounts,
                    'delivery_fee': delivery_fee_amount,
                    'total_with_delivery': total_with_delivery,
                    'product_discount_total': product_discount_total,
                    'coupon_discount_total': coupon_discount_total,
                    'applied_coupon_code': applied_coupon_code,
                    'coupon_code_input': coupon_code_input,
                })

        if not address:
            messages.error(request, 'الرجاء ملء العنوان')
            return render(request, 'store/checkout.html', {
                'cart': checkout_cart_rows,
                'saved_addresses': saved_addresses,
                'default_address': default_address,
                'subtotal': subtotal,
                'subtotal_after_product_offers': subtotal_after_product_offers,
                'subtotal_after_all_discounts': subtotal_after_all_discounts,
                'delivery_fee': delivery_fee_amount,
                'total_with_delivery': total_with_delivery,
                'product_discount_total': product_discount_total,
                'coupon_discount_total': coupon_discount_total,
                'applied_coupon_code': applied_coupon_code,
                'coupon_code_input': coupon_code_input,
            })

        # تطبيق كوبون الطلب (للمسجلين فقط) + تحديث تسعير الصفحة
        pricing_for_order = pricing_offers
        coupon_code_input = (request.POST.get('coupon_code') or '').strip()
        if coupon_code_input:
            if not request.user.is_authenticated:
                messages.error(request, STOREFRONT_COUPON_DENIED_GUEST_MSG)
            else:
                from .discount_engine import price_cart
                pricing_candidate = price_cart(
                    cart_items,
                    user=request.user,
                    guest_phone=None,
                    coupon_code=coupon_code_input,
                )
                if pricing_candidate.get('applied_coupon_code'):
                    pricing_for_order = pricing_candidate
                    applied_coupon_code = pricing_candidate.get('applied_coupon_code')
                    coupon_discount_total = pricing_candidate['coupon_discount_total']
                    product_discount_total = pricing_candidate['product_discount_total']
                    subtotal_after_product_offers = pricing_candidate['subtotal_after_product_offers']
                    discounted_subtotal = pricing_candidate['final_subtotal']
                    subtotal_after_all_discounts = discounted_subtotal
                    total_with_delivery = discounted_subtotal + delivery_fee_amount
                    checkout_cart_rows = _build_checkout_cart_rows(pricing_candidate)
                else:
                    messages.error(request, STOREFRONT_COUPON_INVALID_LOGGED_MSG)

        # فحص توفر المنتجات قبل إنشاء الطلب
        unavailable_products = []
        for item in cart_items:
            product_id = item['product'].id
            variant = item.get('variant')
            quantity = item['quantity']
            current_product = Product.objects.get(id=product_id)
            current_variant = None
            if variant:
                current_variant = ProductVariant.objects.filter(pk=variant.id, product=current_product, is_active=True).first()
            available_qty = int(current_variant.stock_quantity) if current_variant else int(current_product.stock)
            if available_qty < quantity:
                unavailable_products.append({
                    'name': f"{current_product.name_ar} - {current_variant.color_name}" if current_variant and current_variant.color_name else current_product.name_ar,
                    'requested': quantity,
                    'available': available_qty
                })

        if unavailable_products:
            error_msg = 'بعض المنتجات غير متوفرة بالكمية المطلوبة:\n'
            for item in unavailable_products:
                error_msg += f"{item['name']}: طلبت {item['requested']}، متوفر {item['available']}\n"
            messages.error(request, error_msg)
            return render(request, 'store/checkout.html', {
                'cart': checkout_cart_rows,
                'saved_addresses': saved_addresses,
                'default_address': default_address,
                'subtotal': subtotal,
                'subtotal_after_product_offers': subtotal_after_product_offers,
                'subtotal_after_all_discounts': subtotal_after_all_discounts,
                'delivery_fee': delivery_fee_amount,
                'total_with_delivery': total_with_delivery,
                'product_discount_total': product_discount_total,
                'coupon_discount_total': coupon_discount_total,
                'applied_coupon_code': applied_coupon_code,
                'coupon_code_input': coupon_code_input,
            })

        # إنشاء الطلب
        from decimal import Decimal

        from .order_engine import create_initial_history, validate_order_creation

        customer_type = Order.CUSTOMER_REGISTERED if request.user.is_authenticated else Order.CUSTOMER_GUEST

        try:
            validate_order_creation(customer_type, payment_method)
        except ValueError as e:
            messages.error(request, str(e))
            payment_method = Order.PAYMENT_CASH

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    customer_type=customer_type,
                    customer_name=name,
                    customer_phone=phone,
                    customer_email=email,
                    address=address,
                    notes=notes,
                    status=Order.STATUS_PENDING,
                    payment_method=payment_method,
                    payment_status=Order.PAY_STATUS_PENDING,
                    delivery_fee=Decimal(str(delivery_fee_amount)),
                )

                # سجّل نقطة البداية في التاريخ
                create_initial_history(order, actor=request.user if request.user.is_authenticated else None)

                # إضافة عناصر الطلب وخصم المخزون بشكل ذرّي لتفادي البيع الزائد
                # ملاحظة: التسعير النهائي (عروض + كوبون) يأتي من pricing_for_order/checkout_cart_rows
                for idx, item in enumerate(cart_items):
                    product = item['product']
                    variant = item.get('variant')
                    selected_gallery_image = item.get('selected_gallery_image')
                    quantity = int(item['quantity'])
                    final_unit_price = checkout_cart_rows[idx]['unit_price_final']
                    locked_product = Product.objects.select_for_update().get(pk=product.pk)
                    locked_variant = None
                    locked_gallery_image = None
                    if variant:
                        locked_variant = ProductVariant.objects.select_for_update().filter(
                            pk=variant.pk,
                            product_id=locked_product.pk,
                            is_active=True,
                        ).first()
                        if not locked_variant or int(locked_variant.stock_quantity or 0) < quantity:
                            raise ValueError('المخزون تغيّر أثناء تنفيذ الطلب. أعد المحاولة.')
                    elif selected_gallery_image:
                        locked_gallery_image = ProductGalleryImage.objects.select_for_update().filter(
                            pk=selected_gallery_image.pk,
                            product_id=locked_product.pk,
                        ).first()
                        if not locked_gallery_image or int(locked_gallery_image.effective_stock) < quantity:
                            raise ValueError('المخزون تغيّر أثناء تنفيذ الطلب. أعد المحاولة.')
                    elif int(locked_product.stock or 0) < quantity:
                        raise ValueError('المخزون تغيّر أثناء تنفيذ الطلب. أعد المحاولة.')

                    snap = OrderItem.build_snapshots(
                        locked_product,
                        locked_variant,
                        locked_gallery_image if (not locked_variant and locked_gallery_image) else None,
                        image_url=item.get('display_image_url') or '',
                    )
                    OrderItem.objects.create(
                        order=order,
                        product=locked_product,
                        variant=locked_variant,
                        selected_gallery_image=locked_gallery_image if (not locked_variant and locked_gallery_image) else None,
                        quantity=quantity,
                        price=final_unit_price,
                        applied_promotion_id=checkout_cart_rows[idx].get('best_promo_id'),
                        **snap,
                    )
                    if locked_variant:
                        locked_variant.stock_quantity = max(0, int(locked_variant.stock_quantity) - quantity)
                        locked_variant.save(update_fields=['stock_quantity', 'updated_at'])
                    elif locked_gallery_image:
                        locked_gallery_image.stock_quantity = max(0, int(locked_gallery_image.effective_stock) - quantity)
                        locked_gallery_image.save(update_fields=['stock_quantity'])
                    locked_product.stock = max(0, int(locked_product.stock) - quantity)
                    locked_product.save(update_fields=['stock', 'updated_at'])

                # تسجيل استخدام الكوبون بعد نجاح إنشاء OrderItems وخصم المخزون
                if pricing_for_order.get('coupon_obj') and pricing_for_order.get('applied_coupon_code'):
                    from .models import CouponRedemption
                    coupon_obj = pricing_for_order['coupon_obj']
                    if request.user.is_authenticated:
                        CouponRedemption.objects.create(coupon=coupon_obj, user=request.user, guest_phone=None)
                    else:
                        CouponRedemption.objects.create(
                            coupon=coupon_obj,
                            user=None,
                            guest_phone=pricing_for_order.get('guest_phone_norm') or '',
                        )
        except ValueError as e:
            messages.error(request, str(e))
            return render(request, 'store/checkout.html', {
                'cart': checkout_cart_rows,
                'saved_addresses': saved_addresses,
                'default_address': default_address,
                'subtotal': subtotal,
                'subtotal_after_product_offers': subtotal_after_product_offers,
                'subtotal_after_all_discounts': subtotal_after_all_discounts,
                'delivery_fee': delivery_fee_amount,
                'total_with_delivery': total_with_delivery,
                'product_discount_total': product_discount_total,
                'coupon_discount_total': coupon_discount_total,
                'applied_coupon_code': applied_coupon_code,
                'coupon_code_input': coupon_code_input,
            })

        # تفريغ السلة
        cart.clear()

        if payment_method == Order.PAYMENT_GATEWAY:
            from .models import PaymentAttempt
            attempt = PaymentAttempt.objects.create(
                order=order,
                status=PaymentAttempt.STATUS_PENDING,
                amount=order.total,
            )
            # تخزين محاولة الدفع في الجلسة لضمان السماح للضيوف (بدون تسجيل دخول)
            # بوابة الدفع الوهمية ستفحص هذا الـ session بدل الاعتماد على request.user
            try:
                request.session['fake_gateway_attempt_id'] = attempt.id
            except Exception:
                pass
            messages.success(request, f'تم إنشاء طلبك! رقم الطلب: #{order.id}. انتقل لإكمال الدفع (محاكاة).')
            return redirect('fake_gateway_pay', attempt_id=attempt.id)

        messages.success(request, f'تم إنشاء طلبك بنجاح! رقم الطلب: #{order.id}')
        return redirect('order_success', order_id=order.id)

    return render(request, 'store/checkout.html', {
        'cart': checkout_cart_rows,
        'saved_addresses': saved_addresses,
        'default_address': default_address,
        'subtotal': subtotal,
            'subtotal_after_product_offers': subtotal_after_product_offers,
            'subtotal_after_all_discounts': subtotal_after_all_discounts,
        'delivery_fee': delivery_fee_amount,
        'total_with_delivery': total_with_delivery,
        'product_discount_total': product_discount_total,
        'coupon_discount_total': coupon_discount_total,
        'applied_coupon_code': applied_coupon_code,
        'coupon_code_input': coupon_code_input,
    })


def order_success(request, order_id):
    """صفحة نجاح الطلب."""
    order = get_object_or_404(Order, pk=order_id)
    is_guest = not order.user
    return render(request, 'store/order_success.html', {
        'order': order,
        'is_guest': is_guest,
    })


def _authorize_fake_gateway(request, *, attempt):
    """
    السماح للمسجلين بعرض/تنفيذ الدفع فقط لطلبهم.
    السماح للضيوف بالوصول عبر session بعد إنشاء attempt في صفحة checkout.

    يُخزَّن fake_gateway_attempt_id في الجلسة عند إنشاء المحاولة (للمسجلين والضيوف).
    الاعتماد على الجلسة فقط للمسجلين يسبب فشلاً إذا انتهت جلسة تسجيل الدخول لكن
    بقي مفتاح المحاولة، أو إذا فُتح رابط الدفع في متصفح/جهاز بلا نفس حساب المستخدم.
    """
    order = attempt.order
    session_ok = request.session.get('fake_gateway_attempt_id') == attempt.id

    if order.user:
        if request.user.is_authenticated and request.user == order.user:
            return True
        return session_ok

    # طلب ضيف: التحقق من الجلسة التي أنشأت الطلب (حتى لو سجّل المستخدم دخولاً لاحقاً)
    return session_ok


def fake_gateway_pay(request, attempt_id):
    """صفحة بوابة الدفع الوهمية (محاكاة) — تدعم الضيوف أيضاً"""
    from .models import PaymentAttempt

    attempt = get_object_or_404(
        PaymentAttempt.objects.select_related('order', 'order__user'),
        pk=attempt_id,
    )
    order = attempt.order

    if not _authorize_fake_gateway(request, attempt=attempt):
        messages.error(request, 'غير مصرح لك بعرض صفحة الدفع لهذا الطلب.')
        return redirect('wardrobe')

    return render(request, 'store/fake_gateway_pay.html', {
        'attempt': attempt,
        'order': order,
    })


def fake_gateway_callback(request, attempt_id):
    """محاكاة نتيجة الدفع: success / fail (يدعم الضيوف أيضاً)"""
    from .models import Order, PaymentAttempt
    from .order_engine import OrderTransitionError, advance_order, cancel_order, mark_payment

    if request.method != 'POST':
        return redirect('fake_gateway_pay', attempt_id=attempt_id)

    attempt = get_object_or_404(
        PaymentAttempt.objects.select_related('order', 'order__user'),
        pk=attempt_id,
    )
    order = attempt.order

    if not _authorize_fake_gateway(request, attempt=attempt):
        messages.error(request, 'غير مصرح لك بتنفيذ الدفع لهذا الطلب.')
        return redirect('wardrobe')

    result = request.POST.get('result', '').strip().lower()
    reference = request.POST.get('reference', '').strip() or f"FAKEPAY-{attempt.id:06d}"

    card_number = (request.POST.get('card_number') or '').strip()
    card_holder = (request.POST.get('card_holder_name') or '').strip()
    card_expiry = (request.POST.get('card_expiry') or '').strip()

    card_last4 = ''
    digits = ''.join(ch for ch in card_number if ch.isdigit())
    if len(digits) >= 4:
        card_last4 = digits[-4:]

    attempt.reference = reference
    attempt.raw_payload = {
        'result': result,
        'reference': reference,
        'simulated': True,
        'card_last4': card_last4,
        'card_holder_name': card_holder,
        'card_expiry': card_expiry,
    }

    actor = request.user if request.user.is_authenticated else None

    if result == 'success':
        attempt.status = PaymentAttempt.STATUS_SUCCESS
        attempt.save(update_fields=['status', 'reference', 'raw_payload', 'updated_at'])

        mark_payment(order, Order.PAY_STATUS_PAID, actor=actor, note='نجاح الدفع (محاكاة)', is_auto=True)
        # تقدّم تلقائي: pending → confirmed
        try:
            if order.status == Order.STATUS_PENDING:
                advance_order(order, Order.STATUS_CONFIRMED, actor=actor, note='تأكيد تلقائي بعد الدفع', is_auto=True)
        except OrderTransitionError:
            pass

        messages.success(request, '✅ تم الدفع بنجاح (محاكاة).')
        if request.session.get('fake_gateway_attempt_id') == attempt.id:
            try:
                del request.session['fake_gateway_attempt_id']
            except KeyError:
                pass
        if order.user:
            return redirect('order_detail', order_id=order.id)
        return redirect('order_success', order_id=order.id)

    # fail
    attempt.status = PaymentAttempt.STATUS_FAILED
    attempt.save(update_fields=['status', 'reference', 'raw_payload', 'updated_at'])

    mark_payment(order, Order.PAY_STATUS_FAILED, actor=actor, note='فشل الدفع (محاكاة)', is_auto=True)
    try:
        cancel_order(order, reason=Order.CANCEL_PAYMENT_FAIL, note='إلغاء تلقائي بسبب فشل الدفع (محاكاة)', is_auto=True)
    except OrderTransitionError:
        pass

    messages.error(request, '❌ فشل الدفع (محاكاة). تم إلغاء الطلب وإعادة المخزون.')
    if request.session.get('fake_gateway_attempt_id') == attempt.id:
        try:
            del request.session['fake_gateway_attempt_id']
        except KeyError:
            pass
    if order.user:
        return redirect('my_orders')
    return redirect('wardrobe')


def order_track(request):
    """تتبع الطلب — يدعم المستخدمين المسجلين والضيوف معاً."""
    from .models import OrderStatusHistory
    order = None
    history = []

    # تتبع عبر رمز التتبع الفريد (رابط مباشر)
    token = request.GET.get('token', '').strip()
    if token:
        try:
            order = Order.objects.prefetch_related('items__product').get(tracking_token=token)
            history = OrderStatusHistory.objects.filter(order=order)
        except Order.DoesNotExist:
            messages.error(request, 'رابط التتبع غير صالح أو منتهي.')

    elif request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        order_id = request.POST.get('order_id', '').strip()
        phone    = request.POST.get('phone', '').strip()
        if order_id and phone:
            try:
                order = Order.objects.prefetch_related('items__product').get(
                    id=order_id, customer_phone=phone
                )
                history = OrderStatusHistory.objects.filter(order=order)
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'order_id': order.id,
                        'redirect_url': f"{reverse('order_track')}?token={order.tracking_token}",
                    })
            except Order.DoesNotExist:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'لم يتم العثور على الطلب. تأكد من رقم الطلب ورقم الجوال.'}, status=404)
                messages.error(request, 'لم يتم العثور على الطلب. تأكد من رقم الطلب ورقم الجوال.')
        elif is_ajax:
            return JsonResponse({'success': False, 'error': 'أدخل رقم الطلب ورقم الجوال.'}, status=400)

    shipment = None
    if order:
        try:
            shipment = order.shipment
        except Exception:
            shipment = None

    return render(request, 'store/order_track.html', {'order': order, 'history': history, 'shipment': shipment})


# ========== المستخدمين والتسجيل ==========

def user_register(request):
    """إنشاء حساب جديد - مع إرسال OTP للتحقق"""
    import hashlib
    import logging
    import random

    log = logging.getLogger(__name__)

    if request.user.is_authenticated:
        return redirect('wardrobe')

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        from .security_services import register_otp_rate_allow, turnstile_configured, verify_turnstile
        if turnstile_configured():
            ok, err = verify_turnstile(request)
            if not ok:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': err}, status=400)
                messages.error(request, err)
                return render(request, 'store/register.html', {'form': UserRegisterForm(request.POST)})

        form = UserRegisterForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            username = form.cleaned_data['username']
            phone = form.cleaned_data.get('phone', '')
            raw_password = form.cleaned_data['password1']

            if User.objects.filter(email=email).exists():
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'هذا البريد الإلكتروني مسجل مسبقاً.'}, status=400)
                messages.error(request, 'هذا البريد الإلكتروني مسجل مسبقاً.')
                return render(request, 'store/register.html', {'form': form})

            if not register_otp_rate_allow(request, email):
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'تم تجاوز عدد طلبات التحقق المسموح. حاول لاحقاً بعد ساعة.'}, status=429)
                messages.error(request, 'تم تجاوز عدد طلبات التحقق المسموح. حاول لاحقاً بعد ساعة.')
                return render(request, 'store/register.html', {'form': form})

            otp_code = str(random.randint(100000, 999999))
            password_hash = hashlib.sha256(raw_password.encode()).hexdigest()

            EmailOTP.objects.filter(email=email, is_verified=False).delete()
            EmailOTP.objects.create(
                email=email,
                code=otp_code,
                username=username,
                phone=phone,
                password_hash=password_hash,
            )

            from .notifications import send_registration_otp_email
            send_registration_otp_email(email, otp_code)
            log.info('Registration OTP queued for %s (see EMAIL_BACKEND)', email)
            if settings.DEBUG:
                log.debug('Registration OTP code for %s: %s', email, otp_code)

            request.session['otp_email'] = email
            request.session['otp_temp_pass'] = raw_password
            from .security_services import (
                otp_record_successful_send,
                otp_reset_send_count,
                otp_send_session_key_reg,
            )

            k_reg = otp_send_session_key_reg()
            otp_reset_send_count(request, k_reg)
            otp_record_successful_send(request, k_reg)
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'تم إرسال رمز التحقق إلى {email}.', 'redirect_url': reverse('verify_otp')})
            messages.success(request, f'تم إرسال رمز التحقق إلى {email}.')
            return redirect('verify_otp')
        if is_ajax:
            errors = {}
            for field_name, field_errors in form.errors.items():
                errors[field_name] = [str(e) for e in field_errors]
            return JsonResponse({'success': False, 'error': 'يرجى تصحيح بيانات التسجيل.', 'errors': errors}, status=400)
    else:
        form = UserRegisterForm()

    return render(request, 'store/register.html', {'form': form})


def verify_otp(request):
    """صفحة التحقق من رمز OTP"""
    import logging
    import random

    from django.utils import timezone

    from .security_services import (
        otp_can_send_in_challenge,
        otp_record_successful_send,
        otp_send_session_key_reg,
        otp_sends_remaining,
        turnstile_configured,
        verify_turnstile,
    )

    log = logging.getLogger(__name__)

    if request.user.is_authenticated:
        return redirect('wardrobe')

    email = request.session.get('otp_email')
    if not email:
        messages.error(request, 'انتهت الجلسة. يرجى التسجيل مرة أخرى.')
        return redirect('user_register')

    reg_send_key = otp_send_session_key_reg()

    def _verify_otp_render(extra=None):
        ctx = {'email': email, 'otp_sends_remaining': otp_sends_remaining(request, reg_send_key)}
        if extra:
            ctx.update(extra)
        return render(request, 'store/verify_otp.html', ctx)

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if turnstile_configured():
            ok, err = verify_turnstile(request)
            if not ok:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': err}, status=400)
                messages.error(request, err)
                return _verify_otp_render()

        entered_code = request.POST.get('otp_code', '').strip()
        action = request.POST.get('otp_action', request.POST.get('action', 'verify'))

        if action == 'resend':
            if not otp_can_send_in_challenge(request, reg_send_key):
                msg = 'تم تجاوز عدد إعادة الإرسال لهذه الجلسة (3 إعادات بعد الرمز الأول).'
                if is_ajax:
                    return JsonResponse(
                        {
                            'success': False,
                            'error': msg,
                            'otp_sends_remaining': otp_sends_remaining(request, reg_send_key),
                        },
                        status=429,
                    )
                messages.error(request, msg)
                return redirect('verify_otp')
            otp_record = EmailOTP.objects.filter(email=email, is_verified=False).last()
            if otp_record:
                new_code = str(random.randint(100000, 999999))
                otp_record.code = new_code
                otp_record.created_at = timezone.now()
                otp_record.save()
                from .notifications import send_registration_otp_email
                send_registration_otp_email(email, new_code)
                otp_record_successful_send(request, reg_send_key)
                log.info('Registration OTP resent to %s (see EMAIL_BACKEND)', email)
                if settings.DEBUG:
                    log.debug('New registration OTP for %s: %s', email, new_code)
                rem = otp_sends_remaining(request, reg_send_key)
                if is_ajax:
                    return JsonResponse({'success': True, 'message': 'تم إرسال رمز جديد.', 'otp_sends_remaining': rem})
                messages.success(request, 'تم إرسال رمز جديد.')
            elif is_ajax:
                return JsonResponse({'success': False, 'error': 'تعذر العثور على رمز لإعادة الإرسال.'}, status=404)
            return redirect('verify_otp')

        otp_record = EmailOTP.objects.filter(email=email, is_verified=False).last()

        if not otp_record:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'لم يتم العثور على رمز تحقق. يرجى التسجيل مرة أخرى.', 'redirect_url': reverse('user_register')}, status=404)
            messages.error(request, 'لم يتم العثور على رمز تحقق. يرجى التسجيل مرة أخرى.')
            return redirect('user_register')

        if otp_record.is_expired():
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'انتهت صلاحية الرمز. اضغط "إعادة الإرسال" للحصول على رمز جديد.'}, status=400)
            messages.error(request, 'انتهت صلاحية الرمز. اضغط "إعادة الإرسال" للحصول على رمز جديد.')
            return _verify_otp_render()

        if entered_code == otp_record.code:
            username = otp_record.username
            phone = otp_record.phone

            if User.objects.filter(username=username).exists():
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'اسم المستخدم محجوز مسبقاً.', 'redirect_url': reverse('user_register')}, status=400)
                messages.error(request, 'اسم المستخدم محجوز مسبقاً.')
                return redirect('user_register')

            temp_pass = request.session.get('otp_temp_pass')
            if not temp_pass:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'انتهت الجلسة. يرجى التسجيل مرة أخرى.', 'redirect_url': reverse('user_register')}, status=400)
                messages.error(request, 'انتهت الجلسة. يرجى التسجيل مرة أخرى.')
                return redirect('user_register')

            user = User.objects.create_user(
                username=username,
                email=email,
                password=temp_pass,
                is_active=True,
            )
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if phone:
                profile.phone = phone
            profile.email_verified_at = timezone.now()
            profile.save()

            otp_record.is_verified = True
            otp_record.save()
            request.session.pop('otp_email', None)
            request.session.pop('otp_temp_pass', None)

            login(request, user)
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'تم التحقق من بريدك وإنشاء حسابك بنجاح! مرحباً {user.username}', 'redirect_url': reverse('wardrobe')})
            messages.success(request, f'تم التحقق من بريدك وإنشاء حسابك بنجاح! مرحباً {user.username}')
            return redirect('wardrobe')
        if is_ajax:
            return JsonResponse({'success': False, 'error': 'رمز التحقق غير صحيح. حاول مرة أخرى.'}, status=400)
        messages.error(request, 'رمز التحقق غير صحيح. حاول مرة أخرى.')

    return _verify_otp_render()


def user_login(request):
    """تسجيل الدخول"""
    from .security_services import (
        clear_login_failure,
        is_login_locked,
        locked_message,
        login_needs_turnstile,
        record_login_failure,
        send_login_alert_if_enabled,
        verify_turnstile,
    )

    request._security_portal = 'store'

    if request.user.is_authenticated:
        return redirect('wardrobe')

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        username = (request.POST.get('username') or '').strip()
        if username and is_login_locked('store', request, username):
            if is_ajax:
                return JsonResponse({'success': False, 'error': locked_message()}, status=429)
            messages.error(request, locked_message())
            return render(request, 'store/login.html', {'form': UserLoginForm()})

        if login_needs_turnstile('store', request):
            ok, err = verify_turnstile(request)
            if not ok:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': err}, status=400)
                messages.error(request, err)
                return render(request, 'store/login.html', {'form': UserLoginForm(request, data=request.POST)})

        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            clear_login_failure('store', request, username)
            remember = form.cleaned_data.get('remember_me')
            if remember:
                request.session.set_expiry(getattr(settings, 'SESSION_COOKIE_AGE', 1209600))
            else:
                request.session.set_expiry(0)
            login(request, user)
            send_login_alert_if_enabled(user, request)
            raw_next = (request.GET.get('next') or request.POST.get('next') or '').strip()
            if (
                raw_next
                and raw_next.startswith('/')
                and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()})
            ):
                next_url = raw_next
            else:
                profile = getattr(user, 'profile', None)
                at = getattr(profile, 'account_type', None) if profile else None
                if at == UserProfile.ACCOUNT_WAREHOUSE_MANAGER:
                    next_url = reverse('warehouse:manager_dashboard')
                elif at == UserProfile.ACCOUNT_SHIPPING_MANAGER:
                    next_url = reverse('shipping:manager_dashboard')
                elif at == UserProfile.ACCOUNT_PACKER:
                    next_url = reverse('warehouse:dashboard')
                elif at == UserProfile.ACCOUNT_COURIER:
                    next_url = reverse('shipping:dashboard')
                else:
                    next_url = reverse('wardrobe')
            if is_ajax:
                return JsonResponse({'success': True, 'message': f'مرحباً بك {user.username}!', 'redirect_url': next_url})
            messages.success(request, f'مرحباً بك {user.username}!')
            return redirect(next_url)
        if username:
            record_login_failure('store', request, username)
        if is_ajax:
            errors = {}
            for field_name, field_errors in form.errors.items():
                errors[field_name] = [str(e) for e in field_errors]
            return JsonResponse({'success': False, 'error': 'بيانات الدخول غير صحيحة.', 'errors': errors}, status=400)
    else:
        form = UserLoginForm()

    return render(request, 'store/login.html', {'form': form})


def forgot_password(request):
    """بدء عملية نسيت كلمة المرور (إرسال OTP للبريد)."""
    from django.contrib.auth.models import User

    from .password_reset_flow import (
        MSG_EMAIL_REQUIRED,
        MSG_NO_ACCOUNT,
        MSG_OTP_SENT,
        MSG_RATE_LIMITED,
        process_forgot_password_step1,
    )
    if request.user.is_authenticated:
        return redirect('wardrobe')

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        from .security_services import turnstile_configured, verify_turnstile
        if turnstile_configured():
            ok, err = verify_turnstile(request)
            if not ok:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(err)}, status=400)
                messages.error(request, err)
                return redirect('forgot_password')

        email = request.POST.get('email') or ''
        outcome, _ = process_forgot_password_step1(
            request,
            email_raw=email,
            session_otp_key='pw_reset_otp_id',
            session_verified_key='pw_reset_otp_verified',
            resolve_user=lambda e: User.objects.filter(email__iexact=e).first(),
            mail_context='المتجر — إعادة تعيين كلمة المرور',
        )
        if outcome == 'empty':
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(MSG_EMAIL_REQUIRED)}, status=400)
            messages.error(request, MSG_EMAIL_REQUIRED)
        elif outcome == 'rate':
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(MSG_RATE_LIMITED)}, status=429)
            messages.error(request, MSG_RATE_LIMITED)
        elif outcome == 'otp':
            from .security_services import (
                otp_record_successful_send,
                otp_reset_send_count,
                otp_send_session_key_pw_portal,
            )

            k_pw = otp_send_session_key_pw_portal('store')
            otp_reset_send_count(request, k_pw)
            otp_record_successful_send(request, k_pw)
            if is_ajax:
                return JsonResponse({'success': True, 'message': str(MSG_OTP_SENT), 'redirect_url': reverse('forgot_password_otp')})
            messages.success(request, MSG_OTP_SENT)
            return redirect('forgot_password_otp')
        elif outcome == 'no_user':
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(MSG_NO_ACCOUNT)}, status=404)
            messages.error(request, MSG_NO_ACCOUNT)
        return redirect('forgot_password')

    return render(request, 'store/forgot_password.html')


def forgot_password_otp(request):
    """إدخال رمز OTP فقط."""
    from .password_reset_flow import (
        MSG_OTP_EXPIRED,
        MSG_OTP_RESTART,
        MSG_OTP_VERIFIED,
        MSG_OTP_WRONG,
        get_active_password_reset_otp,
        password_reset_otp_resend_response,
        try_verify_password_reset_otp_step,
    )
    from .security_services import otp_send_session_key_pw_portal, otp_sends_remaining

    if request.user.is_authenticated:
        return redirect('wardrobe')

    otp_obj = get_active_password_reset_otp(request, 'pw_reset_otp_id')
    if not otp_obj:
        messages.error(request, MSG_OTP_RESTART)
        return redirect('forgot_password')

    if request.session.get('pw_reset_otp_verified'):
        return redirect('forgot_password_new_password')

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if (request.POST.get('otp_action') or '').strip() == 'resend':
            return password_reset_otp_resend_response(
                request,
                otp_obj,
                portal='store',
                mail_context='المتجر — إعادة تعيين كلمة المرور',
                url_otp='forgot_password_otp',
            )
        if is_ajax:
            code = (request.POST.get('code') or '').strip()
            if otp_obj.is_expired():
                request.session.pop('pw_reset_otp_id', None)
                request.session.pop('pw_reset_otp_verified', None)
                return JsonResponse({'success': False, 'error': str(MSG_OTP_EXPIRED), 'redirect_url': reverse('forgot_password')}, status=400)
            if code != otp_obj.code:
                return JsonResponse({'success': False, 'error': str(MSG_OTP_WRONG)}, status=400)
            request.session['pw_reset_otp_verified'] = True
            return JsonResponse({'success': True, 'message': str(MSG_OTP_VERIFIED), 'redirect_url': reverse('forgot_password_new_password')})

        resp = try_verify_password_reset_otp_step(
            request,
            otp_obj,
            session_otp_key='pw_reset_otp_id',
            session_verified_key='pw_reset_otp_verified',
            url_forgot='forgot_password',
            url_otp='forgot_password_otp',
            url_new_password='forgot_password_new_password',
        )
        if resp:
            return resp

    return render(
        request,
        'store/forgot_password_otp.html',
        {
            'email': otp_obj.email,
            'otp_sends_remaining': otp_sends_remaining(request, otp_send_session_key_pw_portal('store')),
        },
    )


def forgot_password_new_password(request):
    """كلمة المرور الجديدة — تظهر فقط بعد التحقق من الرمز."""
    from .password_reset_flow import (
        MSG_COMPLETE_OTP_FIRST,
        MSG_OTP_EXPIRED,
        MSG_PASSWORD_CHANGED,
        MSG_PASSWORD_MISMATCH,
        MSG_PASSWORD_SHORT,
        get_context_for_new_password_page,
        try_set_new_password_after_verified_otp,
    )
    if request.user.is_authenticated:
        return redirect('wardrobe')

    redir, otp_obj = get_context_for_new_password_page(
        request,
        session_otp_key='pw_reset_otp_id',
        session_verified_key='pw_reset_otp_verified',
        url_forgot='forgot_password',
        url_otp='forgot_password_otp',
    )
    if redir:
        return redir

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if is_ajax:
            if not request.session.get('pw_reset_otp_verified'):
                return JsonResponse({'success': False, 'error': str(MSG_COMPLETE_OTP_FIRST), 'redirect_url': reverse('forgot_password_otp')}, status=400)
            if otp_obj.is_expired():
                request.session.pop('pw_reset_otp_id', None)
                request.session.pop('pw_reset_otp_verified', None)
                return JsonResponse({'success': False, 'error': str(MSG_OTP_EXPIRED), 'redirect_url': reverse('forgot_password')}, status=400)
            pw1 = request.POST.get('password1') or ''
            pw2 = request.POST.get('password2') or ''
            if not pw1 or len(pw1) < 6:
                return JsonResponse({'success': False, 'error': str(MSG_PASSWORD_SHORT)}, status=400)
            if pw1 != pw2:
                return JsonResponse({'success': False, 'error': str(MSG_PASSWORD_MISMATCH)}, status=400)
            user = otp_obj.user
            user.set_password(pw1)
            user.save(update_fields=['password'])
            otp_obj.is_used = True
            otp_obj.save(update_fields=['is_used'])
            request.session.pop('pw_reset_otp_id', None)
            request.session.pop('pw_reset_otp_verified', None)
            return JsonResponse({'success': True, 'message': str(MSG_PASSWORD_CHANGED), 'redirect_url': reverse('user_login')})

        resp = try_set_new_password_after_verified_otp(
            request,
            otp_obj,
            session_otp_key='pw_reset_otp_id',
            session_verified_key='pw_reset_otp_verified',
            url_forgot='forgot_password',
            url_otp='forgot_password_otp',
            url_new_password='forgot_password_new_password',
            url_login='user_login',
            success_message=MSG_PASSWORD_CHANGED,
        )
        if resp:
            return resp

    return render(request, 'store/forgot_password_new.html', {'email': otp_obj.email})


def user_logout(request):
    """تسجيل الخروج"""
    logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح')
    return redirect('wardrobe')


# ========== المفضلات ==========

@login_required(login_url='user_login')
def wishlist_view(request):
    """عرض المفضلات"""
    wishlist_items = (
        Wishlist.objects.filter(user=request.user)
        .select_related('product__category__shelf__compartment')
        .prefetch_related(
            Prefetch(
                'product__variants',
                queryset=ProductVariant.objects.filter(is_active=True).only(
                    'id', 'product_id', 'title', 'color_name', 'color_hex', 'price', 'stock_quantity', 'is_active',
                ).order_by('sort_order', 'id'),
            ),
            'product__gallery_images',
        )
    )
    _attach_storefront_listing_state([w.product for w in wishlist_items])

    # قائمة المنتجات في السلة
    cart = Cart(request)
    cart_product_ids = [int(item['product'].id) for item in cart]

    return render(request, 'store/wishlist.html', {
        'wishlist_items': wishlist_items,
        'cart_product_ids': cart_product_ids,
    })


@login_required(login_url='user_login')
def wishlist_add(request, product_id):
    """إضافة منتج للمفضلات"""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    wishlist_item, created = Wishlist.objects.get_or_create(user=request.user, product=product)

    # للطلبات AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        wishlist_count = Wishlist.objects.filter(user=request.user).count()
        if created:
            return JsonResponse({
                'success': True,
                'created': True,
                'message': f'تمت إضافة {product.name_ar} للمفضلات',
                'wishlist_count': wishlist_count
            })
        else:
            return JsonResponse({
                'success': True,
                'created': False,
                'message': f'{product.name_ar} موجود بالفعل في المفضلات',
                'wishlist_count': wishlist_count
            })

    # للطلبات العادية
    if created:
        messages.success(request, f'تمت إضافة {product.name_ar} للمفضلات')
    else:
        messages.info(request, f'{product.name_ar} موجود بالفعل في المفضلات')

    return redirect(request.META.get('HTTP_REFERER', 'wardrobe'))


@login_required(login_url='user_login')
def wishlist_remove(request, product_id):
    """حذف منتج من المفضلات"""
    Wishlist.objects.filter(user=request.user, product_id=product_id).delete()

    # للطلبات AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        wishlist_count = Wishlist.objects.filter(user=request.user).count()
        return JsonResponse({
            'success': True,
            'message': 'تم حذف المنتج من المفضلات',
            'wishlist_count': wishlist_count
        })

    # للطلبات العادية
    messages.success(request, 'تم حذف المنتج من المفضلات')
    return redirect('wishlist_view')


# ========== طلباتي ==========

def _order_live_sync_signature(order):
    """توقيع ثابت لمقارنة تغيّر حالة الطلب/الشحنة بين الطلبات المتتالية."""
    shipment_status = ''
    shipment_updated = ''
    try:
        shipment = order.shipment
        shipment_status = shipment.status or ''
        shipment_updated = shipment.updated_at.isoformat() if shipment.updated_at else ''
    except Exception:
        pass
    return '|'.join([
        str(order.status or ''),
        str(order.payment_status or ''),
        shipment_status,
        order.updated_at.isoformat() if order.updated_at else '',
        shipment_updated,
    ])


def _order_live_sync_payload(request, order):
    """JSON + HTML جزئي لتحديث واجهة تفاصيل الطلب دون إعادة تحميل الصفحة."""
    try:
        shipment = order.shipment
    except Exception:
        shipment = None
    progress_html = render_to_string(
        'store/partials/order_detail_progress.html',
        {'order': order},
        request=request,
    )
    shipment_slot_html = ''
    if shipment:
        shipment_slot_html = render_to_string(
            'store/partials/order_detail_shipment_row.html',
            {'shipment': shipment},
            request=request,
        )
    return {
        'success': True,
        'signature': _order_live_sync_signature(order),
        'status': order.status,
        'status_display': order.get_status_display(),
        'payment_status': order.payment_status,
        'payment_status_display': order.get_payment_status_display(),
        'progress_html': progress_html,
        'shipment_slot_html': shipment_slot_html,
    }


@login_required(login_url='user_login')
def my_orders(request):
    """عرض طلبات المستخدم"""
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product').order_by('-created_at')
    return render(request, 'store/my_orders.html', {'orders': orders})


@login_required(login_url='user_login')
def order_detail(request, order_id):
    """عرض تفاصيل طلب محدد للمستخدم (بدون سجل حالات داخلي — يظهر في لوحة الإدارة فقط)."""
    from .order_engine import OrderTransitionError, cancel_order
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product__category'),
        pk=order_id,
        user=request.user,
    )

    if request.method == 'POST' and request.POST.get('action') == 'cancel':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        try:
            cancel_order(
                order,
                reason='customer_request',
                note='إلغاء بطلب العميل',
                actor=request.user
            )
            if is_ajax:
                order.refresh_from_db()
                return JsonResponse({
                    'success': True,
                    'order_id': order.id,
                    'status': order.status,
                    'status_display': order.get_status_display(),
                    'cancel_reason_display': order.get_cancel_reason_display() if order.cancel_reason else '',
                    'cancel_note': order.cancel_note or '',
                    'message': 'تم إلغاء طلبك بنجاح.',
                })
            messages.success(request, 'تم إلغاء طلبك بنجاح.')
        except OrderTransitionError as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(request, str(e))
        return redirect('order_detail', order_id=order_id)

    shipment = None
    try:
        shipment = order.shipment
    except Exception:
        shipment = None

    return render(request, 'store/order_detail.html', {
        'order': order,
        'shipment': shipment,
        'sync_signature': _order_live_sync_signature(order),
    })


@login_required(login_url='user_login')
def order_detail_poll(request, order_id):
    """مزامنة خفيفة: نفس توقيع الصفحة + HTML مسار الطلب وشارة الحالات (بدون reload)."""
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    return JsonResponse(_order_live_sync_payload(request, order))


def order_track_poll(request):
    """Polling لتتبع الطلب — يرجع بيانات كاملة لتحديث DOM بدون reload."""
    token = (request.GET.get('token') or '').strip()
    if not token:
        return JsonResponse({'success': False, 'error': 'token_required'}, status=400)
    order = Order.objects.filter(tracking_token=token).first()
    if not order:
        return JsonResponse({'success': False, 'error': 'order_not_found'}, status=404)

    shipment = None
    shipment_status = ''
    shipment_status_display = ''
    shipment_updated = ''
    try:
        shipment = order.shipment
        shipment_status = shipment.status or ''
        shipment_status_display = shipment.get_status_display() if shipment else ''
        shipment_updated = shipment.updated_at.isoformat() if shipment.updated_at else ''
    except Exception:
        pass

    signature = '|'.join([
        str(order.status or ''),
        str(order.payment_status or ''),
        shipment_status,
        order.updated_at.isoformat() if order.updated_at else '',
        shipment_updated,
    ])

    # قائمة الخطوات المرتبة مع أيقوناتها وعناوينها
    steps_meta = [
        {'code': 'pending',       'icon': '⏳', 'label': 'قيد الانتظار'},
        {'code': 'confirmed',     'icon': '✅', 'label': 'تم التأكيد'},
        {'code': 'processing',    'icon': '⚙️', 'label': 'قيد التجهيز'},
        {'code': 'ready_to_ship', 'icon': '📦', 'label': 'جاهز للشحن'},
        {'code': 'shipped',       'icon': '🚚', 'label': 'تم الشحن'},
        {'code': 'delivered',     'icon': '🎉', 'label': 'تم التوصيل'},
    ]
    status_icons = {s['code']: s['icon'] for s in steps_meta}
    status_icons['cancelled'] = '❌'

    cancel_reason_display = ''
    if order.status == 'cancelled' and order.cancel_reason:
        cancel_reason_display = order.get_cancel_reason_display()

    return JsonResponse({
        'success': True,
        'signature': signature,
        'status': order.status or '',
        'status_display': order.get_status_display(),
        'status_icon': status_icons.get(order.status or '', ''),
        'payment_status': order.payment_status or '',
        'payment_status_display': order.get_payment_status_display(),
        'has_shipment': bool(shipment),
        'shipment_status': shipment_status,
        'shipment_status_display': shipment_status_display,
        'is_cancelled': order.status == 'cancelled',
        'cancel_reason_display': cancel_reason_display,
        'steps_meta': steps_meta,
    })


@login_required(login_url='user_login')
def reorder(request, order_id):
    """إعادة طلب سابق - إضافة جميع منتجات الطلب للسلة"""
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    cart = Cart(request)

    added_count = 0
    unavailable = []

    for item in order.items.all():
        if not item.product_id:
            unavailable.append({
                'name': item.display_product_name or 'منتج غير متوفر',
                'requested': item.quantity,
                'available': 0,
            })
            continue
        product = item.product
        variant = item.variant if item.variant_id else None
        quantity = item.quantity

        available_qty = int(variant.stock_quantity) if variant else int(product.stock)
        if product.is_active and available_qty >= quantity:
            cart.add(product, quantity, variant=variant)
            added_count += 1
        else:
            vname = ''
            if variant and variant.color_name:
                vname = variant.color_name
            elif item.display_variant_label:
                vname = item.display_variant_label
            label = f"{product.name_ar} - {vname}" if vname else product.name_ar
            unavailable.append({
                'name': label,
                'requested': quantity,
                'available': available_qty if product.is_active else 0,
            })

    if added_count > 0:
        messages.success(request, f'تمت إضافة {added_count} منتج للسلة')

    if unavailable:
        warning_msg = 'بعض المنتجات غير متوفرة:\n'
        for item in unavailable:
            warning_msg += f"• {item['name']}: طلبت {item['requested']}، متوفر {item['available']}\n"
        messages.warning(request, warning_msg)

    return redirect('cart_view')


# ========== الملف الشخصي ==========

@login_required(login_url='user_login')
def profile_view(request):
    """عرض الملف الشخصي"""
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    addresses = Address.objects.filter(user=request.user)
    recent_orders = Order.objects.filter(user=request.user)[:5]

    stats = {
        'total_orders': Order.objects.filter(user=request.user).count(),
        'wishlist_count': Wishlist.objects.filter(user=request.user).count(),
        'addresses_count': addresses.count(),
    }

    return render(request, 'store/profile.html', {
        'profile': profile,
        'addresses': addresses,
        'recent_orders': recent_orders,
        'stats': stats,
    })


@login_required(login_url='user_login')
def profile_edit(request):
    """تعديل الملف الشخصي"""
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        form = UserProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            # حفظ بيانات الـ User
            user = request.user
            user.first_name = form.cleaned_data.get('first_name', '')
            user.last_name = form.cleaned_data.get('last_name', '')
            user.email = form.cleaned_data.get('email', '')
            user.save()

            # حفظ الملف الشخصي
            form.save()
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'تم تحديث ملفك الشخصي بنجاح', 'redirect_url': reverse('profile_view')})
            messages.success(request, 'تم تحديث ملفك الشخصي بنجاح')
            return redirect('profile_view')
        if is_ajax:
            errors = {}
            for field_name, field_errors in form.errors.items():
                errors[field_name] = [str(e) for e in field_errors]
            return JsonResponse({'success': False, 'error': 'يرجى تصحيح الأخطاء في النموذج.', 'errors': errors}, status=400)
    else:
        form = UserProfileForm(instance=profile, user=request.user)

    return render(request, 'store/profile_edit.html', {'form': form, 'profile': profile})


# ========== العناوين ==========

@login_required(login_url='user_login')
def addresses_list(request):
    """قائمة العناوين"""
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'store/addresses_list.html', {'addresses': addresses})


@login_required(login_url='user_login')
def address_add(request):
    """إضافة عنوان جديد"""
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        form = AddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'تم إضافة العنوان بنجاح', 'redirect_url': reverse('addresses_list')})
            messages.success(request, 'تم إضافة العنوان بنجاح')
            return redirect('addresses_list')
        if is_ajax:
            errors = {}
            for field_name, field_errors in form.errors.items():
                errors[field_name] = [str(e) for e in field_errors]
            return JsonResponse({'success': False, 'error': 'يرجى تصحيح الأخطاء في العنوان.', 'errors': errors}, status=400)
    else:
        form = AddressForm()

    return render(request, 'store/address_form.html', {'form': form, 'title': 'إضافة عنوان جديد'})


@login_required(login_url='user_login')
def address_edit(request, address_id):
    """تعديل عنوان"""
    address = get_object_or_404(Address, pk=address_id, user=request.user)

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        form = AddressForm(request.POST, instance=address)
        if form.is_valid():
            form.save()
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'تم تحديث العنوان بنجاح', 'redirect_url': reverse('addresses_list')})
            messages.success(request, 'تم تحديث العنوان بنجاح')
            return redirect('addresses_list')
        if is_ajax:
            errors = {}
            for field_name, field_errors in form.errors.items():
                errors[field_name] = [str(e) for e in field_errors]
            return JsonResponse({'success': False, 'error': 'يرجى تصحيح أخطاء العنوان.', 'errors': errors}, status=400)
    else:
        form = AddressForm(instance=address)

    return render(request, 'store/address_form.html', {'form': form, 'title': 'تعديل العنوان', 'address': address})


@login_required(login_url='user_login')
def address_delete(request, address_id):
    """حذف عنوان"""
    if request.method != 'POST':
        return redirect('addresses_list')
    address = get_object_or_404(Address, pk=address_id, user=request.user)
    address.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'تم حذف العنوان بنجاح', 'address_id': int(address_id)})
    messages.success(request, 'تم حذف العنوان بنجاح')
    return redirect('addresses_list')


@login_required(login_url='user_login')
def address_set_default(request, address_id):
    """جعل العنوان افتراضي"""
    if request.method != 'POST':
        return redirect('addresses_list')
    address = get_object_or_404(Address, pk=address_id, user=request.user)
    # إلغاء الافتراضي من جميع العناوين
    Address.objects.filter(user=request.user).update(is_default=False)
    # جعل هذا العنوان افتراضي
    address.is_default = True
    address.save()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': 'تم تعيين العنوان الافتراضي',
            'address_id': address.id,
        })
    messages.success(request, 'تم تعيين العنوان الافتراضي')
    return redirect('addresses_list')


# ========== التقييمات ==========

@login_required(login_url='user_login')
def review_add(request, product_id):
    """إضافة تقييم"""
    product = get_object_or_404(Product, pk=product_id, is_active=True)

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        rating = request.POST.get('rating')
        comment = request.POST.get('comment', '').strip()

        if not rating:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'الرجاء اختيار تقييم'}, status=400)
            messages.error(request, 'الرجاء اختيار تقييم')
            return redirect('product', product_id=product_id)

        review, created = Review.objects.update_or_create(
            product=product,
            user=request.user,
            defaults={
                'rating': int(rating),
                'comment': comment
            }
        )
        if is_ajax:
            return JsonResponse({
                'success': True,
                'created': bool(created),
                'message': 'تم إضافة تقييمك بنجاح' if created else 'تم تحديث تقييمك بنجاح',
                'rating': int(review.rating or 0),
                'comment': review.comment or '',
            })

        if created:
            messages.success(request, 'تم إضافة تقييمك بنجاح')
        else:
            messages.success(request, 'تم تحديث تقييمك بنجاح')

        return redirect('product', product_id=product_id)

    return redirect('product', product_id=product_id)


@login_required(login_url='user_login')
def review_delete(request, review_id):
    """حذف تقييم"""
    if request.method != 'POST':
        return redirect('my_reviews')
    review = get_object_or_404(Review, pk=review_id, user=request.user)
    product_id = review.product.id
    review.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': 'تم حذف تقييمك',
            'review_id': int(review_id),
            'product_id': product_id,
        })
    messages.success(request, 'تم حذف تقييمك')
    return redirect('product', product_id=product_id)


@login_required(login_url='user_login')
def my_reviews(request):
    """عرض تقييماتي"""
    reviews = Review.objects.filter(user=request.user).select_related('product__category__shelf__compartment')
    return render(request, 'store/my_reviews.html', {'reviews': reviews})


def search(request):
    """البحث عن منتجات مع فلاتر و pagination."""
    query = request.GET.get('q', '').strip()
    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()

    products = []
    products_page = None
    count = 0

    if query:
        query_no_hash = query[1:].strip() if query.startswith('#') else query
        linked_product = _resolve_product_from_query(query) or _resolve_product_from_query(query_no_hash)
        if linked_product:
            return redirect('product', product_id=linked_product.id)

        terms = [query]
        if query_no_hash and query_no_hash != query:
            terms.append(query_no_hash)

        products = Product.objects.filter(is_active=True).none()
        for term in terms:
            products = products | Product.objects.filter(is_active=True).filter(
                Q(name_ar__icontains=term) |
                Q(name_en__icontains=term) |
                Q(sku__icontains=term)
            )
            if term.isdigit():
                products = products | Product.objects.filter(is_active=True, id=int(term))
        products = products.distinct()

        # فلتر السعر
        if min_price:
            try:
                products = products.filter(price__gte=float(min_price))
            except ValueError:
                pass

        if max_price:
            try:
                products = products.filter(price__lte=float(max_price))
            except ValueError:
                pass

        products = (
            products.select_related('category__shelf__compartment')
            .annotate(gallery_count=Count('gallery_images', distinct=True))
            .prefetch_related(_variants_for_teaser_prefetch())
        )
        count = products.count()

        # Pagination
        paginator = Paginator(products, 20)  # 20 منتج في الصفحة
        page = request.GET.get('page')

        try:
            products_page = paginator.page(page)
        except PageNotAnInteger:
            products_page = paginator.page(1)
        except EmptyPage:
            products_page = paginator.page(paginator.num_pages)

        _attach_storefront_listing_state(products_page)

    return render(request, 'store/search.html', {
        'query': query,
        'products': products_page,
        'count': count,
        'min_price': min_price,
        'max_price': max_price,
    })


def about_view(request):
    """صفحة عن المتجر."""
    return render(request, 'store/about.html')


def contact_view(request):
    """صفحة اتصل بنا مع نموذج إرسال رسالة."""
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            if is_ajax:
                return JsonResponse({'success': True, 'message': 'تم إرسال رسالتك بنجاح. سنتواصل معك قريباً.'})
            messages.success(request, 'تم إرسال رسالتك بنجاح. سنتواصل معك قريباً.')
            return redirect('contact')
        if is_ajax:
            errors = {}
            for field_name, field_errors in form.errors.items():
                errors[field_name] = [str(e) for e in field_errors]
            return JsonResponse({'success': False, 'error': 'يرجى تصحيح الأخطاء أدناه.', 'errors': errors}, status=400)
        messages.error(request, 'يرجى تصحيح الأخطاء أدناه.')
    else:
        form = ContactForm()
    return render(request, 'store/contact.html', {'form': form})


# ===== المرتجعات =====

@login_required
def my_returns_view(request):
    """عرض جميع مرتجعات المستخدم"""
    returns = Return.objects.filter(user=request.user).prefetch_related('items__product', 'order')
    return render(request, 'store/my_returns.html', {'returns': returns})


@login_required
def return_detail_view(request, return_id):
    """عرض تفاصيل مرتجع محدد"""
    from .return_engine import build_return_timeline

    return_obj = get_object_or_404(
        Return.objects.select_related('order').prefetch_related(
            Prefetch(
                'status_history',
                queryset=ReturnStatusHistory.objects.select_related('changed_by').order_by('created_at'),
            ),
            'items__product',
        ),
        id=return_id,
        user=request.user,
    )
    return render(request, 'store/return_detail.html', {
        'return_obj': return_obj,
        'return_timeline': build_return_timeline(return_obj),
    })


@login_required
def return_detail_poll(request, return_id):
    """GET — تحديث حالة طلب الإرجاع وجدول زمنه بدون reload."""
    from .return_engine import build_return_timeline

    return_obj = get_object_or_404(
        Return.objects.select_related('order').prefetch_related(
            Prefetch(
                'status_history',
                queryset=ReturnStatusHistory.objects.select_related('changed_by').order_by('created_at'),
            ),
        ),
        id=return_id,
        user=request.user,
    )
    timeline_html = render_to_string(
        'store/partials/return_timeline.html',
        {
            'return_obj': return_obj,
            'return_timeline': build_return_timeline(return_obj),
        },
        request=request,
    )
    signature = '|'.join([
        str(return_obj.status or ''),
        str(return_obj.refund_status or ''),
        str(return_obj.stock_status or ''),
        return_obj.updated_at.isoformat() if return_obj.updated_at else '',
    ])
    return JsonResponse({
        'success': True,
        'signature': signature,
        'status': return_obj.status,
        'status_display': return_obj.get_status_display(),
        'refund_status': return_obj.refund_status or '',
        'stock_status': return_obj.stock_status or '',
        'timeline_html': timeline_html,
    })


@login_required
def create_return_view(request, order_id):
    """إنشاء طلب إرجاع لطلب معين"""
    order = get_object_or_404(Order, id=order_id, user=request.user)

    if order.status not in [Order.STATUS_DELIVERED, Order.STATUS_CONFIRMED]:
        messages.error(request, 'لا يمكن إرجاع هذا الطلب. يجب أن يكون الطلب مؤكداً أو تم توصيله.')
        return redirect('order_detail', order_id=order_id)

    if Return.objects.filter(order=order).exists():
        messages.warning(request, 'تم إنشاء طلب إرجاع لهذا الطلب مسبقاً.')
        return redirect('my_returns')

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        reason = request.POST.get('reason')
        reason_details = request.POST.get('reason_details', '')
        selected_items = request.POST.getlist('item_ids')

        if not reason:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'يرجى تحديد سبب الإرجاع'}, status=400)
            messages.error(request, 'يرجى تحديد سبب الإرجاع')
            return redirect('create_return', order_id=order_id)

        if not selected_items:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'يرجى اختيار المنتجات التي تريد إرجاعها'}, status=400)
            messages.error(request, 'يرجى اختيار المنتجات التي تريد إرجاعها')
            return redirect('create_return', order_id=order_id)

        return_obj = Return.objects.create(
            order=order,
            user=request.user,
            reason=reason,
            reason_details=reason_details,
            status=Return.STATUS_REQUESTED
        )
        from .return_engine import create_initial_return_history
        create_initial_return_history(return_obj, actor=request.user)

        total_refund = 0
        for item_id in selected_items:
            order_item = OrderItem.objects.filter(id=item_id, order=order).first()
            if order_item:
                quantity_str = request.POST.get(f'quantity_{item_id}', '0')
                try:
                    quantity = int(quantity_str)
                    if quantity > 0 and quantity <= order_item.quantity:
                        ReturnItem.objects.create(
                            return_request=return_obj,
                            product=order_item.product,
                            variant=order_item.variant,
                            quantity=quantity,
                            price_at_purchase=order_item.price,
                            product_name_snapshot=order_item.display_product_name,
                            product_sku_snapshot=order_item.display_sku or '',
                            variant_label_snapshot=order_item.display_variant_label or '',
                        )
                        total_refund += quantity * order_item.price
                except ValueError:
                    pass

        return_obj.refund_amount = total_refund
        return_obj.save()
        if is_ajax:
            return JsonResponse({
                'success': True,
                'return_id': return_obj.id,
                'redirect_url': reverse('return_detail', args=[return_obj.id]),
                'message': f'تم إنشاء طلب الإرجاع #{return_obj.id} بنجاح',
            })

        messages.success(request, f'تم إنشاء طلب الإرجاع #{return_obj.id} بنجاح')
        return redirect('return_detail', return_id=return_obj.id)

    order_items = order.items.prefetch_related(
        'product__gallery_images',
        'variant__images',
        'selected_gallery_image',
        'applied_promotion',
    )
    return render(request, 'store/create_return.html', {
        'order': order,
        'order_items': order_items,
        'reason_choices': Return.REASON_CHOICES
    })
