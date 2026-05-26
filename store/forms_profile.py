"""
Forms for user profile and addresses
"""
from django import forms

from .models import Address, UserProfile


class UserProfileForm(forms.ModelForm):
    """نموذج تعديل الملف الشخصي"""
    first_name = forms.CharField(
        label='الاسم الأول',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'profile-input',
            'placeholder': 'مثال: محمد',
            'autocomplete': 'given-name',
        })
    )
    last_name = forms.CharField(
        label='اسم العائلة',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'profile-input',
            'placeholder': 'مثال: العتيبي',
            'autocomplete': 'family-name',
        })
    )
    email = forms.EmailField(
        label='البريد الإلكتروني',
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'profile-input',
            'placeholder': 'example@email.com',
            'autocomplete': 'email',
            'dir': 'ltr',
        })
    )

    class Meta:
        model = UserProfile
        fields = ['phone', 'birth_date', 'avatar']
        widgets = {
            'phone': forms.TextInput(attrs={
                'class': 'profile-input',
                'placeholder': '05xxxxxxxx',
                'dir': 'ltr',
                'inputmode': 'tel',
                'autocomplete': 'tel',
            }),
            'birth_date': forms.DateInput(attrs={
                'class': 'profile-input',
                'type': 'date',
            }),
            'avatar': forms.FileInput(attrs={
                'class': 'profile-file-native',
                'accept': 'image/jpeg,image/png,image/webp,image/gif',
            }),
        }
        labels = {
            'phone': 'رقم الجوال',
            'birth_date': 'تاريخ الميلاد',
            'avatar': 'الصورة الشخصية',
        }
        help_texts = {
            'phone': 'يُفضّل رقم سعودي يبدأ بـ 05 مكوّن من 10 أرقام.',
            'birth_date': 'يُستخدم أحياناً لعروض أعياد الميلاد (اختياري).',
            'avatar': 'صورة واضحة للوجه أو رمز تفضّله. الصيغ: JPG أو PNG أو WebP.',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email


class AddressForm(forms.ModelForm):
    """نموذج إضافة/تعديل عنوان"""
    class Meta:
        model = Address
        fields = ['title', 'full_name', 'phone', 'city', 'district', 'street', 'building_number', 'additional_info', 'is_default']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'unified-address-input',
                'placeholder': 'مثال: المنزل، العمل',
                'autocomplete': 'section-address nickname',
            }),
            'full_name': forms.TextInput(attrs={
                'class': 'unified-address-input',
                'autocomplete': 'name',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'unified-address-input',
                'placeholder': '05xxxxxxxx',
                'dir': 'ltr',
                'inputmode': 'tel',
                'autocomplete': 'tel',
            }),
            'city': forms.TextInput(attrs={
                'class': 'unified-address-input',
                'placeholder': 'الرياض، جدة، الدمام...',
                'autocomplete': 'address-level2',
            }),
            'district': forms.TextInput(attrs={
                'class': 'unified-address-input',
                'autocomplete': 'address-level3',
            }),
            'street': forms.TextInput(attrs={
                'class': 'unified-address-input',
                'autocomplete': 'street-address',
            }),
            'building_number': forms.TextInput(attrs={
                'class': 'unified-address-input',
                'autocomplete': 'address-line2',
            }),
            'additional_info': forms.Textarea(attrs={
                'class': 'unified-address-input',
                'rows': 3,
                'placeholder': 'علامات مميزة أو تعليمات للتوصيل',
            }),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'title': 'اسم العنوان',
            'full_name': 'الاسم الكامل',
            'phone': 'رقم الجوال',
            'city': 'المدينة',
            'district': 'الحي',
            'street': 'الشارع',
            'building_number': 'رقم المبنى',
            'additional_info': 'معلومات إضافية',
            'is_default': 'جعله عنوان افتراضي',
        }
