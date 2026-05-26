"""
مسارات لوحة الإدارة — نظامك فقط (لا تعتمد على /admin/).
"""
from django.urls import path

from . import views_manage

app_name = 'manage'

urlpatterns = [
    path('system/backup/', views_manage.site_backup, name='site_backup'),
    path('system/wipe/', views_manage.site_full_wipe, name='site_full_wipe'),
    path('', views_manage.dashboard, name='dashboard'),
    path('login/', views_manage.manage_login, name='login'),
    path('forgot-password/', views_manage.forgot_password, name='forgot_password'),
    path('forgot-password/otp/', views_manage.forgot_password_otp, name='forgot_password_otp'),
    path('forgot-password/new-password/', views_manage.forgot_password_new_password, name='forgot_password_new_password'),
    path('logout/', views_manage.manage_logout, name='logout'),
    path('api/notifications/', views_manage.manage_notifications_json, name='notifications_json'),
    path('api/mark-seen/', views_manage.manage_mark_seen_json, name='mark_seen_json'),
    path('api/mark-seen-bulk/', views_manage.manage_mark_seen_bulk_json, name='mark_seen_bulk_json'),
    path('api/packers-availability/', views_manage.packers_availability_live, name='packers_availability_live'),
    path('api/couriers-availability/', views_manage.couriers_availability_live, name='couriers_availability_live'),
    path('overview/', views_manage.overview, name='overview'),
    # خانات
    path('compartments/', views_manage.compartment_list, name='compartment_list'),
    path('compartments/add/', views_manage.compartment_add, name='compartment_add'),
    path('compartments/<int:pk>/edit/', views_manage.compartment_edit, name='compartment_edit'),
    path('compartments/<int:pk>/delete/', views_manage.compartment_delete, name='compartment_delete'),
    # رفوف
    path('shelves/', views_manage.shelf_list, name='shelf_list'),
    path('shelves/add/', views_manage.shelf_add, name='shelf_add'),
    path('shelves/<int:pk>/edit/', views_manage.shelf_edit, name='shelf_edit'),
    path('shelves/<int:pk>/delete/', views_manage.shelf_delete, name='shelf_delete'),
    # أصناف
    path('categories/', views_manage.category_list, name='category_list'),
    path('categories/add/', views_manage.category_add, name='category_add'),
    path('categories/<int:pk>/edit/', views_manage.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views_manage.category_delete, name='category_delete'),
    # منتجات
    path('products/', views_manage.product_list, name='product_list'),
    path('products/add/', views_manage.product_add, name='product_add'),
    path('products/<int:pk>/edit/', views_manage.product_edit, name='product_edit'),
    path('products/<int:pk>/variants/', views_manage.product_variants_manage, name='product_variants_manage'),
    path('products/variants/export.csv', views_manage.variants_inventory_export_csv, name='variants_inventory_export_csv'),
    path('products/variants/<int:variant_id>/stock.json', views_manage.variant_stock_json, name='variant_stock_json'),
    path('products/<int:pk>/delete/', views_manage.product_delete, name='product_delete'),

    # عروض / خصومات
    path('promotions/', views_manage.promotion_list, name='promotion_list'),
    path('promotions/add/', views_manage.promotion_add, name='promotion_add'),
    path('promotions/<int:pk>/edit/', views_manage.promotion_edit, name='promotion_edit'),
    path('promotions/<int:pk>/delete/', views_manage.promotion_delete, name='promotion_delete'),
    path('promotions/<int:pk>/toggle-active/', views_manage.promotion_toggle_active, name='promotion_toggle_active'),

    # كوبونات
    path('coupons/', views_manage.coupon_list, name='coupon_list'),
    path('coupons/add/', views_manage.coupon_add, name='coupon_add'),
    path('coupons/<int:pk>/edit/', views_manage.coupon_edit, name='coupon_edit'),
    path('coupons/<int:pk>/delete/', views_manage.coupon_delete, name='coupon_delete'),
    path('coupons/<int:pk>/toggle-active/', views_manage.coupon_toggle_active, name='coupon_toggle_active'),
    # طلبات
    path('orders/', views_manage.order_list, name='order_list'),
    path('orders/<int:pk>/', views_manage.order_detail, name='order_detail'),
    path('orders/<int:pk>/edit/', views_manage.order_edit, name='order_edit'),
    path('orders/<int:pk>/live-state/', views_manage.order_detail_live_state, name='order_detail_live_state'),
    path('orders/<int:pk>/waybill-qr.png', views_manage.order_waybill_qr_png, name='order_waybill_qr'),
    path('orders/<int:pk>/shipping-label/', views_manage.manage_order_shipping_label, name='order_shipping_label_print'),
    # الشحن
    path('shipments/', views_manage.shipments_list_manage, name='shipments_list_manage'),
    path('shipments/<int:pk>/', views_manage.shipment_detail_manage, name='shipment_detail_manage'),
    path('couriers/', views_manage.couriers_list, name='couriers_list'),
    path('packers/', views_manage.packers_list, name='packers_list'),
    # المستودع
    path('warehouse/', views_manage.warehouse_orders_manage, name='warehouse_orders_manage'),
    # مرتجعات
    path('returns/', views_manage.returns_list, name='returns_list'),
    path('returns/<int:pk>/', views_manage.return_detail, name='return_detail'),
    path('returns/<int:pk>/live-state/', views_manage.return_detail_live_state, name='return_detail_live_state'),
    # إدارة المستخدمين العاديين
    path('users/', views_manage.users_list, name='users_list'),
    path('users/<int:user_id>/', views_manage.user_detail, name='user_detail'),
    path('users/<int:user_id>/edit/', views_manage.user_profile_edit, name='user_profile_edit'),
    path('users/<int:user_id>/toggle/', views_manage.user_toggle_active, name='user_toggle_active'),
    path('users/<int:user_id>/toggle-availability/', views_manage.user_toggle_availability, name='user_toggle_availability'),
    path('users/roles/shipping-managers/', views_manage.shipping_managers_list, name='shipping_managers_list'),
    path('users/roles/warehouse-managers/', views_manage.warehouse_managers_list, name='warehouse_managers_list'),
    path('users/roles/customer-service/', views_manage.customer_service_accounts_list, name='customer_service_accounts_list'),
    path('users/roles/customer-service-managers/', views_manage.customer_service_managers_list, name='customer_service_managers_list'),
    # إدارة المسؤولين
    path('admins/', views_manage.admins_list, name='admins_list'),
    # خدمة العملاء (الدردشة)
    path('support/', views_manage.support_portal, name='support_portal'),
    path('support/thread/<int:thread_id>/', views_manage.support_thread_detail, name='support_thread_detail'),
    path('support/api/signature/', views_manage.support_portal_signature_json, name='support_portal_signature_json'),
    path('support/api/thread/<int:thread_id>/messages/', views_manage.support_thread_messages_json, name='support_thread_messages_json'),
    path('support/api/thread/<int:thread_id>/send/', views_manage.support_thread_send_json, name='support_thread_send_json'),
    path('support/api/thread/<int:thread_id>/claim/', views_manage.support_thread_claim_json, name='support_thread_claim_json'),
    path('support/api/thread/<int:thread_id>/mark-read/', views_manage.support_thread_mark_read_json, name='support_thread_mark_read_json'),
    path('support/api/thread/<int:thread_id>/end/', views_manage.support_thread_end_json, name='support_thread_end_json'),
    path('support/team/', views_manage.support_team_accounts, name='support_team_accounts'),
    path('support/team/agent/<int:agent_id>/', views_manage.support_agent_detail, name='support_agent_detail'),
    path('support/team/<int:user_id>/toggle-availability/', views_manage.support_toggle_availability, name='support_toggle_availability'),
    path('support/archive/thread/<int:thread_id>/', views_manage.support_archive_thread, name='support_archive_thread'),
    path('support/archive/agent/<int:agent_id>/', views_manage.support_archive_agent, name='support_archive_agent'),
    # رسائل اتصل بنا
    path('contact-messages/', views_manage.contact_messages_list, name='contact_messages_list'),
]
