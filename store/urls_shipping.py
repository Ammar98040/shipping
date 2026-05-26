"""
مسارات بوابة شركة الشحن (شركة السريع للشحن).
"""
from django.urls import path

from . import views_shipping

app_name = 'shipping'

urlpatterns = [
    path('', views_shipping.dashboard, name='dashboard'),
    path('login/', views_shipping.shipping_login, name='login'),
    path('forgot-password/', views_shipping.forgot_password, name='forgot_password'),
    path('forgot-password/otp/', views_shipping.forgot_password_otp, name='forgot_password_otp'),
    path('forgot-password/new-password/', views_shipping.forgot_password_new_password, name='forgot_password_new_password'),
    path('logout/', views_shipping.shipping_logout, name='logout'),
    path('profile/', views_shipping.profile, name='profile'),
    path('scan/', views_shipping.scan_hub, name='scan'),
    path('scan/pickup/', views_shipping.scan_pickup, name='scan_pickup'),
    path('scan/deliver/', views_shipping.scan_deliver, name='scan_deliver'),
    path('scan/consume/', views_shipping.scan_consume, name='scan_consume'),
    path('deliver/otp/', views_shipping.deliver_otp, name='deliver_otp'),
    path('availability/', views_shipping.set_availability, name='set_availability'),
    path('api/my-availability/', views_shipping.my_availability_live, name='my_availability_live'),
    path('jobs/', views_shipping.available_jobs, name='available_jobs'),
    path('jobs/live/', views_shipping.available_jobs_live, name='available_jobs_live'),
    path('jobs/<int:pk>/accept/', views_shipping.accept_job, name='accept_job'),
    path('shipments/', views_shipping.shipments_list, name='shipments_list'),
    path('shipments/<int:pk>/', views_shipping.shipment_detail, name='shipment_detail'),
    path('shipments/<int:pk>/poll/', views_shipping.shipment_detail_poll, name='shipment_detail_poll'),
    path('internal-chat/', views_shipping.internal_chat, name='internal_chat'),
    # ── لوحة مسؤول الشحن ─────────────────────────────────────
    path('manager/', views_shipping.shipping_manager_dashboard, name='manager_dashboard'),
    path('manager/couriers/', views_shipping.shipping_manager_couriers, name='manager_couriers'),
    path('manager/shipments/', views_shipping.shipping_manager_shipments, name='manager_shipments'),
    path('manager/shipments/<int:pk>/assign/', views_shipping.shipping_assign_shipment, name='assign_shipment'),
]

