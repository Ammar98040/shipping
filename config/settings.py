"""
Django settings for SHOP (Wardrobe E-commerce).
Database: MySQL (development) → PostgreSQL (production).
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# تحميل متغيرات البيئة من .env إن وُجد
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

_use_sqlite = os.environ.get('USE_SQLITE', '').strip().lower() in ('1', 'true', 'yes')

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'change-me-in-production')

DEBUG = os.environ.get('DEBUG', 'True').strip().lower() in ('1', 'true', 'yes', 'on')

ALLOWED_HOSTS = ['*'] # السماح لـ Hugging Face بالوصول

# إعدادات أمان إضافية لبيئة Hugging Face
CSRF_TRUSTED_ORIGINS = [
    'https://*.hf.space',
    'https://*.huggingface.co'
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'store',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.lang_direction',
                'store.context_processors.cart_context',
                'store.context_processors.security_context',
                'store.context_processors.manage_config',
            ],
        },
    },
]

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600
    )
}
# Backup old logic for reference
# if _use_sqlite else {
#     'default': {
#         'ENGINE': 'django.db.backends.mysql',
#         'NAME': os.environ.get('DB_NAME', 'shop_db'),
#         'USER': os.environ.get('DB_USER', 'root'),
#         'PASSWORD': os.environ.get('DB_PASSWORD', ''),
#         'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
#         'PORT': os.environ.get('DB_PORT', '3306'),
#         'OPTIONS': {
#             'charset': 'utf8mb4',
#         },
#     }
# }

# For production, switch to PostgreSQL (see README):
# 'ENGINE': 'django.db.backends.postgresql',
# 'NAME': os.environ.get('DB_NAME'), ...

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': int(os.environ.get('AUTH_PASSWORD_MIN_LENGTH', '10'))},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ar'
LANGUAGES = [
    ('ar', 'العربية'),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

TIME_ZONE = 'Asia/Riyadh'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# لوحة الإدارة: عدد الأيام التي يُعتبر خلالها السجل «حديثاً» لعلامة الصف الأحمر (قبل أول اطلاع)
MANAGE_NEW_ROW_MAX_AGE_DAYS = int(os.environ.get('MANAGE_NEW_ROW_MAX_AGE_DAYS', '30'))
MANAGE_NOTIFICATIONS_POLL_MS = int(os.environ.get('MANAGE_NOTIFICATIONS_POLL_MS', '8000'))
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')

# رسوم التوصيل الافتراضية (ر.س) — يمكن تغييرها لاحقاً حسب المدينة أو الحد الأدنى للطلب
DELIVERY_FEE = float(os.environ.get('DELIVERY_FEE', '15'))

LOGIN_URL = '/manage/login/'
LOGIN_REDIRECT_URL = '/manage/'

# البريد: افتراضياً console = تظهر الرسائل في تيرمنال runserver (OTP التسجيل + نسيت كلمة المرور + إشعارات).
# للإنتاج: استخدم SMTP عبر متغيرات البيئة (انظر .env.example).
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend',
)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@shop.local')

# Webhooks (fake integrations for testing)
FAKE_GATEWAY_WEBHOOK_SECRET = os.environ.get('FAKE_GATEWAY_WEBHOOK_SECRET', 'dev-secret-gateway')
FAKE_SHIPPING_WEBHOOK_SECRET = os.environ.get('FAKE_SHIPPING_WEBHOOK_SECRET', 'dev-secret-shipping')

_FAKE_SECRET_DEFAULTS = frozenset({'dev-secret-gateway', 'dev-secret-shipping'})
if not DEBUG and (
    FAKE_GATEWAY_WEBHOOK_SECRET in _FAKE_SECRET_DEFAULTS
    or FAKE_SHIPPING_WEBHOOK_SECRET in _FAKE_SECRET_DEFAULTS
):
    raise ImproperlyConfigured(
        'في الإنتاج (DEBUG=False) يجب تعيين FAKE_GATEWAY_WEBHOOK_SECRET و '
        'FAKE_SHIPPING_WEBHOOK_SECRET إلى قيم سرّية عشوائية (وليس القيم الافتراضية للتطوير).'
    )

# صور الدردشة وخدمة العملاء (حجم بالبايت، عدد أقصى للملفات في طلب واحد)
CHAT_IMAGE_MAX_BYTES = int(os.environ.get('CHAT_IMAGE_MAX_BYTES', str(5 * 1024 * 1024)))
CHAT_IMAGE_MAX_COUNT = int(os.environ.get('CHAT_IMAGE_MAX_COUNT', '10'))

# نسخ احتياطي ZIP من لوحة الإدارة (سوبر يوزر فقط). لا تُخزَّن كلمات مرور هنا — استخدم .env فقط.
BACKUP_SCHEMA_VERSION = int(os.environ.get('BACKUP_SCHEMA_VERSION', '1'))
# حسابات النظام المحمية دائماً من التصدير/الاستيراد/الحذف الكامل (لا تُحذف من .env).
SYSTEM_IMMUTABLE_USERNAMES = ('ammar',)
_BACKUP_PROTECTED_RAW = os.environ.get('BACKUP_PROTECTED_USERNAMES', '').strip()
BACKUP_PROTECTED_USERNAMES = [
    x.strip() for x in _BACKUP_PROTECTED_RAW.split(',') if x.strip()
]
BACKUP_PROTECTED_BOOTSTRAP_PASSWORD = os.environ.get('BACKUP_PROTECTED_BOOTSTRAP_PASSWORD', '').strip()
BACKUP_AUTO_SAVE_DIR = os.environ.get('BACKUP_AUTO_SAVE_DIR', '').strip()
BACKUP_IMPORT_MAX_MB = int(os.environ.get('BACKUP_IMPORT_MAX_MB', '2048'))
BACKUP_IMPORT_MAX_BYTES = BACKUP_IMPORT_MAX_MB * 1024 * 1024
# استيراد الويب الكامل خطير على MySQL — افتراضياً غير مسموح إلا SQLite ما لم يُفعَّل صراحةً.
BACKUP_WEB_RESTORE_ALLOW_MYSQL = os.environ.get(
    'BACKUP_WEB_RESTORE_ALLOW_MYSQL', ''
).strip().lower() in ('1', 'true', 'yes', 'on')
# حذف كامل من لوحة النسخ الاحتياطي: يُفعّل زر الخطر فقط إن وُجدت قيمة سرّية في البيئة (لا تُرفع إلى Git).
FULL_SITE_WIPE_SECRET = os.environ.get('FULL_SITE_WIPE_SECRET', '').strip()

# كاش: في الإنتاج مع عدة عمال Gunicorn يُفضّل Redis (REDIS_URL) ليتشارك حد المعدل والجلسات
_redis_url = os.environ.get('REDIS_URL', '').strip()
if _redis_url:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _redis_url,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'shop-default-cache',
        }
    }

# ——— أمان الإنتاج (عند DEBUG=False) ———
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').strip().lower() in ('1', 'true', 'yes', 'on')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    # خلف بروكسي/ـNginx يمرّر X-Forwarded-Proto
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# Cloudflare Turnstile (اتركه فارغاً للتطوير بدون كابتشا)
TURNSTILE_SITE_KEY = os.environ.get('TURNSTILE_SITE_KEY', '').strip()
TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY', '').strip()
TURNSTILE_OPTIONAL_IN_DEBUG = True

# صفحة اعتذار مخصصة عند فشل CSRF
CSRF_FAILURE_VIEW = 'store.views_errors.csrf_failure'

# حد محاولات تسجيل الدخول
LOGIN_FAILURE_MAX = int(os.environ.get('LOGIN_FAILURE_MAX', '5'))
LOGIN_FAILURE_LOCK_SECONDS = int(os.environ.get('LOGIN_FAILURE_LOCK_SECONDS', '900'))
LOGIN_FAILURE_WINDOW_SEC = int(os.environ.get('LOGIN_FAILURE_WINDOW_SEC', '3600'))
LOGIN_CAPTCHA_AFTER_FAILS = int(os.environ.get('LOGIN_CAPTCHA_AFTER_FAILS', '3'))

# بريد تنبيه عند دخول ناجح (متجر العملاء فقط) — اختياري
SEND_LOGIN_ALERT_EMAIL = os.environ.get('SEND_LOGIN_ALERT_EMAIL', '').strip().lower() in ('1', 'true', 'yes', 'on')

# جلسة المتجر الافتراضية (بالثواني؛ 0 = حتى إغلاق المتصفح)
SESSION_COOKIE_AGE = int(os.environ.get('SESSION_COOKIE_AGE', '1209600'))  # 14 يوم كحد أقصى إن مُفعّل «تذكرني»
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
