"""
مسارات بوابة المستودع (تجهيز الطلبات).
"""
from django.urls import path

from . import views_warehouse

app_name = 'warehouse'

urlpatterns = [
    path('', views_warehouse.dashboard, name='dashboard'),
    path('login/', views_warehouse.warehouse_login, name='login'),
    path('forgot-password/', views_warehouse.forgot_password, name='forgot_password'),
    path('forgot-password/otp/', views_warehouse.forgot_password_otp, name='forgot_password_otp'),
    path('forgot-password/new-password/', views_warehouse.forgot_password_new_password, name='forgot_password_new_password'),
    path('logout/', views_warehouse.warehouse_logout, name='logout'),
    path('profile/', views_warehouse.profile, name='profile'),
    path('availability/', views_warehouse.set_availability, name='set_availability'),
    path('api/my-availability/', views_warehouse.my_availability_live, name='my_availability_live'),
    path('jobs/', views_warehouse.available_orders, name='available_orders'),
    path('jobs/live/', views_warehouse.available_orders_live, name='available_orders_live'),
    path('jobs/<int:pk>/accept/', views_warehouse.accept_order, name='accept_order'),
    path('orders/<int:pk>/', views_warehouse.order_detail, name='order_detail'),
    path('orders/<int:pk>/poll/', views_warehouse.order_detail_poll, name='order_detail_poll'),
    path('internal-chat/', views_warehouse.internal_chat, name='internal_chat'),
    path('orders/<int:pk>/waybill/create/', views_warehouse.create_shipping_waybill, name='create_shipping_waybill'),
    path('orders/<int:pk>/label/', views_warehouse.shipping_label, name='shipping_label'),
    path('orders/<int:pk>/label/qr.png', views_warehouse.order_label_qr, name='order_label_qr'),
    path('scan/', views_warehouse.scan, name='scan'),
    path('scan/consume/', views_warehouse.scan_consume, name='scan_consume'),
    # ── لوحة مسؤول المستودع ──────────────────────────────────
    path('manager/', views_warehouse.warehouse_manager_dashboard, name='manager_dashboard'),
    path('manager/team/', views_warehouse.warehouse_manager_team, name='manager_team'),
    path('manager/orders/', views_warehouse.warehouse_manager_orders, name='manager_orders'),
    path('manager/orders/<int:pk>/assign/', views_warehouse.warehouse_assign_order, name='assign_order'),
]

