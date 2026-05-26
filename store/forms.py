"""
نماذج لوحة الإدارة — إضافة/تعديل الخانات، الرفوف، الأصناف، المنتجات.
عربي فقط.
"""
from django import forms

from .models import (
    Category,
    Compartment,
    ContactMessage,
    Coupon,
    Product,
    ProductVariant,
    Promotion,
    Shelf,
)


class CompartmentForm(forms.ModelForm):
    class Meta:
        model = Compartment
        fields = ['name_ar', 'order', 'image', 'is_active']
        widgets = {
            'name_ar': forms.TextInput(attrs={'class': 'input', 'placeholder': 'الاسم'}),
            'order': forms.NumberInput(attrs={'class': 'input', 'min': 0}),
            'is_active': forms.CheckboxInput(attrs={'class': 'checkbox'}),
        }


class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = ['compartment', 'name_ar', 'order', 'image', 'is_active']
        widgets = {
            'compartment': forms.Select(attrs={'class': 'input'}),
            'name_ar': forms.TextInput(attrs={'class': 'input'}),
            'order': forms.NumberInput(attrs={'class': 'input', 'min': 0}),
            'is_active': forms.CheckboxInput(attrs={'class': 'checkbox'}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['shelf', 'name_ar', 'order', 'image', 'is_active']
        widgets = {
            'shelf': forms.Select(attrs={'class': 'input'}),
            'name_ar': forms.TextInput(attrs={'class': 'input'}),
            'order': forms.NumberInput(attrs={'class': 'input', 'min': 0}),
            'is_active': forms.CheckboxInput(attrs={'class': 'checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shelf'].queryset = Shelf.objects.select_related('compartment').order_by(
            'compartment__order', 'compartment__id', 'order', 'id'
        )
        self.fields['shelf'].label_from_instance = lambda sh: f"{sh.compartment.name_ar} - {sh.name_ar}"


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'category', 'name_ar',
            'description_ar',
            'price', 'image', 'stock', 'order', 'is_active'
        ]
        widgets = {
            'category': forms.Select(attrs={'class': 'input'}),
            'name_ar': forms.TextInput(attrs={'class': 'input'}),
            'description_ar': forms.Textarea(attrs={'class': 'input', 'rows': 3}),
            'price': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': 0}),
            'stock': forms.NumberInput(attrs={'class': 'input', 'min': 0}),
            'order': forms.NumberInput(attrs={'class': 'input', 'min': 0}),
            'is_active': forms.CheckboxInput(attrs={'class': 'checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.select_related('shelf', 'shelf__compartment').order_by(
            'shelf__compartment__order',
            'shelf__compartment__id',
            'shelf__order',
            'shelf__id',
            'order',
            'id',
        )
        self.fields['category'].label_from_instance = lambda cat: f"{cat.shelf.compartment.name_ar} - {cat.shelf.name_ar} - {cat.name_ar}"


class ContactForm(forms.ModelForm):
    """نموذج اتصل بنا"""
    class Meta:
        model = ContactMessage
        fields = ['name', 'phone', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'الاسم الكامل'}),
            'phone': forms.TextInput(attrs={'class': 'input', 'placeholder': '05xxxxxxxx', 'required': 'required'}),
            'email': forms.EmailInput(attrs={'class': 'input', 'placeholder': 'example@email.com'}),
            'subject': forms.TextInput(attrs={'class': 'input', 'placeholder': 'موضوع الرسالة'}),
            'message': forms.Textarea(attrs={'class': 'input', 'rows': 5, 'placeholder': 'اكتب رسالتك هنا...'}),
        }
        labels = {
            'name': 'الاسم *',
            'phone': 'رقم الجوال *',
            'email': 'البريد الإلكتروني *',
            'subject': 'الموضوع *',
            'message': 'الرسالة *',
        }


class PromotionForm(forms.ModelForm):
    class Meta:
        model = Promotion
        fields = [
            'name',
            'description',
            'is_active',
            'start_at',
            'end_at',
            'scope',
            'discount_type',
            'discount_value',
            'min_quantity',
            'compartments',
            'shelves',
            'categories',
            'products',
            'variants',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'مثال: خصم 20% تيشيرت'}),
            'description': forms.Textarea(attrs={'class': 'input', 'rows': 3, 'placeholder': 'وصف اختياري'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'checkbox'}),
            'start_at': forms.DateTimeInput(attrs={'class': 'input', 'type': 'datetime-local'}),
            'end_at': forms.DateTimeInput(attrs={'class': 'input', 'type': 'datetime-local'}),
            'scope': forms.Select(attrs={'class': 'input'}),
            'discount_type': forms.Select(attrs={'class': 'input'}),
            'discount_value': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': 0}),
            'min_quantity': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
            'compartments': forms.SelectMultiple(attrs={'class': 'input', 'size': 8}),
            'shelves': forms.SelectMultiple(attrs={'class': 'input', 'size': 8}),
            'categories': forms.SelectMultiple(attrs={'class': 'input', 'size': 8}),
            'products': forms.SelectMultiple(attrs={'class': 'input', 'size': 8}),
            'variants': forms.SelectMultiple(attrs={'class': 'input', 'size': 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['scope'].help_text = 'اختر نطاق تطبيق العرض ثم اختر العناصر التابعة له (إن لزم).'
        self.fields['compartments'].help_text = 'يظهر فقط عند اختيار نطاق: الخانات.'
        self.fields['shelves'].help_text = 'يظهر فقط عند اختيار نطاق: الرفوف.'
        self.fields['categories'].help_text = 'يظهر فقط عند اختيار نطاق: الأصناف.'
        self.fields['products'].help_text = 'يظهر فقط عند اختيار نطاق: المنتجات.'
        self.fields['variants'].help_text = 'يظهر فقط عند اختيار نطاق: النسخ.'

        self.fields['compartments'].queryset = Compartment.objects.order_by('order', 'id')
        self.fields['shelves'].queryset = Shelf.objects.select_related('compartment').order_by(
            'compartment__order', 'compartment__id', 'order', 'id'
        )
        self.fields['categories'].queryset = Category.objects.select_related('shelf', 'shelf__compartment').order_by(
            'shelf__compartment__order',
            'shelf__compartment__id',
            'shelf__order',
            'shelf__id',
            'order',
            'id',
        )
        self.fields['products'].queryset = Product.objects.select_related('category', 'category__shelf', 'category__shelf__compartment').order_by(
            'category__shelf__compartment__order',
            'category__shelf__compartment__id',
            'category__shelf__order',
            'category__shelf__id',
            'category__order',
            'category__id',
            'order',
            'id',
        )
        self.fields['variants'].queryset = ProductVariant.objects.select_related('product', 'product__category', 'product__category__shelf', 'product__category__shelf__compartment').order_by(
            'product__category__shelf__compartment__order',
            'product__category__shelf__compartment__id',
            'product__category__shelf__order',
            'product__category__shelf__id',
            'product__category__order',
            'product__category__id',
            'product__order',
            'product__id',
            'sort_order',
            'id',
        )

        self.fields['shelves'].label_from_instance = lambda sh: f"{sh.compartment.name_ar} - {sh.name_ar}"
        self.fields['categories'].label_from_instance = lambda cat: f"{cat.shelf.compartment.name_ar} - {cat.shelf.name_ar} - {cat.name_ar}"
        self.fields['products'].label_from_instance = lambda p: f"{p.category.shelf.compartment.name_ar} - {p.category.shelf.name_ar} - {p.category.name_ar} - {p.name_ar}"
        self.fields['variants'].label_from_instance = lambda v: f"{v.product.category.shelf.compartment.name_ar} - {v.product.category.shelf.name_ar} - {v.product.category.name_ar} - {v.product.name_ar} - {v.customer_variant_button_label}"


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            'code',
            'is_active',
            'start_at',
            'end_at',
            'discount_type',
            'discount_value',
            'max_uses_total',
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'input', 'placeholder': 'مثال: SALE10'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'checkbox'}),
            'start_at': forms.DateTimeInput(attrs={'class': 'input', 'type': 'datetime-local'}),
            'end_at': forms.DateTimeInput(attrs={'class': 'input', 'type': 'datetime-local'}),
            'discount_type': forms.Select(attrs={'class': 'input'}),
            'discount_value': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': 0}),
            'max_uses_total': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
        }
