"""
نظام السلة — session-based (لا يحتاج تسجيل دخول).
"""

class Cart:
    """إدارة سلة التسوق في Session."""

    def __init__(self, request):
        self.session = request.session
        cart = self.session.get('cart')
        if not cart:
            cart = self.session['cart'] = {}
        # توحيد المفاتيح كنص لتجنب تكرار نفس المنتج (مثلاً 5 و "5")
        self.cart = {str(k): v for k, v in cart.items()}
        self.session['cart'] = self.cart

        # كوبون السلة (تجريبي): نخزنه في الـ session حتى يظهر في السلة/الدفع
        self._coupon_code = (self.session.get('cart_coupon_code') or '').strip()
        self._coupon_guest_phone = (self.session.get('cart_coupon_guest_phone') or '').strip()

    def get_coupon_code(self) -> str:
        return (self._coupon_code or '').strip()

    def get_coupon_guest_phone(self) -> str:
        return (self._coupon_guest_phone or '').strip()

    def set_coupon(self, *, code: str = '', guest_phone: str = ''):
        self._coupon_code = (code or '').strip()
        self._coupon_guest_phone = (guest_phone or '').strip()
        if self._coupon_code:
            self.session['cart_coupon_code'] = self._coupon_code
        else:
            self.session.pop('cart_coupon_code', None)
        if self._coupon_guest_phone:
            self.session['cart_coupon_guest_phone'] = self._coupon_guest_phone
        else:
            self.session.pop('cart_coupon_guest_phone', None)
        self.save()

    def clear_coupon(self):
        self._coupon_code = ''
        self._coupon_guest_phone = ''
        self.session.pop('cart_coupon_code', None)
        self.session.pop('cart_coupon_guest_phone', None)
        self.save()

    @staticmethod
    def make_key(product_id, variant_id=None, gallery_image_id=None):
        if variant_id:
            return f"v:{int(variant_id)}"
        if gallery_image_id:
            return f"g:{int(product_id)}:{int(gallery_image_id)}"
        return str(int(product_id))

    def add(self, product, quantity=1, variant=None, selected_gallery_image=None):
        """إضافة منتج للسلة."""
        cart_key = self.make_key(product.id, getattr(variant, 'id', None), getattr(selected_gallery_image, 'id', None))
        if variant is not None:
            unit_price = variant.effective_price
            item_name = f"{product.name_ar} - {variant.color_name}" if variant.color_name else product.name_ar
        elif selected_gallery_image is not None:
            unit_price = selected_gallery_image.effective_price
            item_name = selected_gallery_image.title or product.name_ar
        else:
            unit_price = product.price
            item_name = product.name_ar
        if cart_key not in self.cart:
            self.cart[cart_key] = {
                'product_id': int(product.id),
                'variant_id': int(variant.id) if variant is not None else None,
                'selected_gallery_image_id': int(selected_gallery_image.id) if selected_gallery_image is not None else None,
                'quantity': 0,
                'price': str(unit_price),
                'name': item_name,
            }
        self.cart[cart_key]['quantity'] += quantity
        self.save()

    def update(self, key_or_product_id, quantity, variant_id=None):
        """تحديث كمية منتج في السلة."""
        cart_key = str(key_or_product_id)
        if variant_id is not None:
            cart_key = self.make_key(key_or_product_id, variant_id)
        if cart_key in self.cart:
            if quantity > 0:
                self.cart[cart_key]['quantity'] = quantity
            else:
                del self.cart[cart_key]
            self.save()

    def remove(self, key_or_product_id, variant_id=None):
        """حذف منتج من السلة."""
        cart_key = str(key_or_product_id)
        if variant_id is not None:
            cart_key = self.make_key(key_or_product_id, variant_id)
        if cart_key in self.cart:
            del self.cart[cart_key]
            self.save()

    def clear(self):
        """تفريغ السلة."""
        del self.session['cart']
        self.save()

    def save(self):
        self.session.modified = True

    def __iter__(self):
        """استرجاع المنتجات من قاعدة البيانات."""
        from .models import Product, ProductGalleryImage, ProductVariant
        product_ids = []
        variant_ids = []
        gallery_image_ids = []
        for item in self.cart.values():
            pid = item.get('product_id')
            vid = item.get('variant_id')
            gid = item.get('selected_gallery_image_id')
            if pid:
                product_ids.append(int(pid))
            if vid:
                variant_ids.append(int(vid))
            if gid:
                gallery_image_ids.append(int(gid))

        products = Product.objects.prefetch_related('gallery_images').filter(id__in=product_ids)
        variants = ProductVariant.objects.select_related('product').prefetch_related('images').filter(id__in=variant_ids)
        gallery_images = ProductGalleryImage.objects.select_related('product').filter(id__in=gallery_image_ids)

        products_dict = {str(product.id): product for product in products}
        variants_dict = {str(variant.id): variant for variant in variants}
        gallery_images_dict = {str(img.id): img for img in gallery_images}

        for cart_key, item in self.cart.items():
            product_id = str(item.get('product_id') or '')
            variant_id = item.get('variant_id')
            selected_gallery_image_id = item.get('selected_gallery_image_id')
            variant = variants_dict.get(str(variant_id)) if variant_id is not None else None
            selected_gallery_image = gallery_images_dict.get(str(selected_gallery_image_id)) if selected_gallery_image_id is not None else None
            if product_id in products_dict:
                product = products_dict[product_id]
                active_variant = variant if variant and variant.product_id == product.id else None
                if active_variant:
                    available_stock = int(active_variant.stock_quantity)
                elif selected_gallery_image and selected_gallery_image.product_id == product.id:
                    available_stock = int(selected_gallery_image.effective_stock)
                else:
                    available_stock = int(product.stock)
                display_image_url = product.image.url if product.image else ''
                if active_variant:
                    images = list(active_variant.images.all())
                    primary = next((img for img in images if img.is_primary), None) or (images[0] if images else None)
                    if primary and getattr(primary, 'image', None):
                        display_image_url = primary.image.url
                if not active_variant and selected_gallery_image and selected_gallery_image.product_id == product.id and getattr(selected_gallery_image, 'image', None):
                    display_image_url = selected_gallery_image.image.url
                if not display_image_url:
                    gallery_images = list(product.gallery_images.all())
                    g_primary = next((img for img in gallery_images if img.is_primary), None) or (gallery_images[0] if gallery_images else None)
                    if g_primary and getattr(g_primary, 'image', None):
                        display_image_url = g_primary.image.url
                yield {
                    'cart_key': cart_key,
                    'product': product,
                    'variant': active_variant,
                    'selected_gallery_image': selected_gallery_image if (selected_gallery_image and selected_gallery_image.product_id == product.id) else None,
                    'quantity': item['quantity'],
                    'price': item['price'],
                    'name': item['name'],
                    'display_image_url': display_image_url,
                    'available_stock': available_stock,
                    'total': float(item['price']) * item['quantity']
                }

    def __len__(self):
        """عدد العناصر في السلة."""
        return sum(item['quantity'] for item in self.cart.values())

    def get_total(self):
        """المجموع الكلي للسلة."""
        return sum(float(item['price']) * item['quantity'] for item in self.cart.values())

    def get_items_count(self):
        """عدد الأصناف المختلفة (ليس الكمية الإجمالية)."""
        return len(self.cart)
