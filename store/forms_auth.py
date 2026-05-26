"""
Forms for user authentication and registration
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class UserRegisterForm(UserCreationForm):
    """نموذج إنشاء حساب جديد"""
    username = forms.CharField(
        label='اسم المستخدم',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم المستخدم'})
    )
    email = forms.EmailField(
        required=True,
        label='البريد الإلكتروني',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@email.com'})
    )
    phone = forms.CharField(
        required=True,
        label='رقم الجوال',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '05xxxxxxxx', 'maxlength': '20'})
    )
    password1 = forms.CharField(
        label='كلمة المرور',
        help_text=_('10 أحرف على الأقل؛ تجنب كلمات شائعة.'),
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'كلمة المرور', 'minlength': '10', 'autocomplete': 'new-password'})
    )
    password2 = forms.CharField(
        label='تأكيد كلمة المرور',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'أعد كتابة كلمة المرور', 'minlength': '10', 'autocomplete': 'new-password'})
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'phone', 'password1', 'password2']

    def clean_password1(self):
        pw = self.cleaned_data.get('password1') or ''
        if len(pw) < 10:
            raise ValidationError(_('كلمة المرور يجب أن تكون 10 أحرف على الأقل.'))
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            from .models import UserProfile
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone = self.cleaned_data.get('phone', '')
            profile.save()
        return user


class UserLoginForm(AuthenticationForm):
    """نموذج تسجيل الدخول"""
    username = forms.CharField(
        label='اسم المستخدم',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم المستخدم', 'autocomplete': 'username'})
    )
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'كلمة المرور', 'autocomplete': 'current-password'})
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        label='تذكرني على هذا الجهاز (جلسة أطول)',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
