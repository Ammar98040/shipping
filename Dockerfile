# استخدم نسخة بايثون مستقرة
FROM python:3.11-slim

# منع بايثون من كتابة ملفات pyc ومن تخزين المخرجات في الذاكرة المؤقتة
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# تثبيت مكتبات النظام اللازمة (لـ MySQL و PostgreSQL إذا احتجنا لاحقاً)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملف المتطلبات وتثبيت المكتبات
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كامل كود المشروع
COPY . /app/

# Hugging Face يتطلب العمل على المنفذ 7860
EXPOSE 7860

# تشغيل عمليات Django وتجهيز الملفات الثابتة ثم تشغيل السيرفر
CMD ["sh", "-c", "python manage.py collectstatic --no-input && python manage.py migrate && python create_admin.py && gunicorn config.wsgi:application --bind 0.0.0.0:7860"]
