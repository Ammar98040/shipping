from django.conf import settings
from django.core.mail import send_mail


def send_registration_otp_email(to_email: str, code: str) -> None:
    """
    رمز التحقق عند إنشاء حساب جديد.
    نفس مسار البريد العام: مع console يظهر في التيرمنال، مع SMTP يصل للبريد الحقيقي.
    """
    if not to_email:
        return
    send_mail(
        subject='رمز التحقق — إنشاء حساب',
        message=f'رمز التحقق لإتمام التسجيل: {code}\nصالح لمدة 15 دقيقة.',
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[to_email],
        fail_silently=True,
    )
    print(f"[REGISTRATION_OTP] email={to_email} otp={code}")


def send_order_email(to_email: str, subject: str, message: str) -> None:
    """
    إرسال إشعار للعميل.
    في وضع التطوير يستخدم EMAIL_BACKEND=console لذلك ستظهر الرسالة في الـ Terminal.
    """
    if not to_email:
        return
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[to_email],
        fail_silently=True,
    )


def notify_order_status(order, title: str, extra: str = '') -> None:
    subject = f"{title} | طلب #{order.id}"
    msg = (
        f"طلب رقم: #{order.id}\n"
        f"الاسم: {order.customer_name}\n"
        f"الحالة: {order.get_status_display()}\n"
        f"حالة الدفع: {order.get_payment_status_display()}\n"
        f"المجموع: {order.total} ر.س\n"
    )
    if extra:
        msg += f"\n{extra}\n"
    send_order_email(order.customer_email, subject, msg)

