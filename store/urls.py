"""
Store URLs: مسارات المتجر (الدولاب) + لوحة الإدارة (نظامك فقط).
"""
from django.urls import include, path

from . import views, views_welcome

urlpatterns = [
    path('', views_welcome.welcome_page, name='welcome'),
    path('home/', views.wardrobe_view, name='wardrobe'),
    path('compartment/<int:compartment_id>/', views.compartment_view, name='compartment'),
    path('shelf/<int:shelf_id>/', views.shelf_view, name='shelf'),
    path('category/<int:category_id>/', views.category_view, name='category'),
    path('products/', views.products_all_view, name='products_all'),
    path('product/<int:product_id>/', views.product_view, name='product'),
    path('p/<slug:slug>/', views.product_view_by_slug, name='product_by_slug'),
    # السلة والطلبات
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/coupon/', views.cart_coupon_apply, name='cart_coupon_apply'),
    path('cart/add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('cart/update/<int:product_id>/', views.cart_update, name='cart_update'),
    path('cart/remove/<int:product_id>/', views.cart_remove, name='cart_remove'),
    path('cart/share/create/', views.cart_share_create, name='cart_share_create'),
    path('cart/share/<str:token>/', views.cart_share_view, name='cart_share_view'),
    path('cart/share/<str:token>/apply/', views.cart_share_apply, name='cart_share_apply'),
    path('checkout/', views.checkout, name='checkout'),
    path('order/success/<int:order_id>/', views.order_success, name='order_success'),
    path('order/track/', views.order_track, name='order_track'),
    # بوابة الدفع الوهمية (اختبار)
    path('pay/fake/<int:attempt_id>/', views.fake_gateway_pay, name='fake_gateway_pay'),
    path('pay/fake/<int:attempt_id>/callback/', views.fake_gateway_callback, name='fake_gateway_callback'),
    # Webhooks (محاكاة)
    path('webhooks/fake-gateway/', views.fake_gateway_webhook, name='fake_gateway_webhook'),
    path('webhooks/fake-shipping/', views.fake_shipping_webhook, name='fake_shipping_webhook'),
    # المستخدمين
    path('register/', views.user_register, name='user_register'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('login/', views.user_login, name='user_login'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('forgot-password/otp/', views.forgot_password_otp, name='forgot_password_otp'),
    path('forgot-password/new-password/', views.forgot_password_new_password, name='forgot_password_new_password'),
    path('logout/', views.user_logout, name='user_logout'),
    # المفضلات
    path('wishlist/', views.wishlist_view, name='wishlist_view'),
    path('wishlist/add/<int:product_id>/', views.wishlist_add, name='wishlist_add'),
    path('wishlist/remove/<int:product_id>/', views.wishlist_remove, name='wishlist_remove'),
    # طلباتي
    path('my-orders/', views.my_orders, name='my_orders'),
    path('order/<int:order_id>/', views.order_detail, name='order_detail'),
    path('order/<int:order_id>/poll/', views.order_detail_poll, name='order_detail_poll'),
    path('order/track/poll/', views.order_track_poll, name='order_track_poll'),
    path('reorder/<int:order_id>/', views.reorder, name='reorder'),
    # المرتجعات
    path('my-returns/', views.my_returns_view, name='my_returns'),
    path('return/<int:return_id>/', views.return_detail_view, name='return_detail'),
    path('return/<int:return_id>/poll/', views.return_detail_poll, name='return_detail_poll'),
    path('return/create/<int:order_id>/', views.create_return_view, name='create_return'),
    # التقييمات
    path('review/add/<int:product_id>/', views.review_add, name='review_add'),
    path('review/delete/<int:review_id>/', views.review_delete, name='review_delete'),
    path('reviews/', views.my_reviews, name='my_reviews'),
    # الملف الشخصي
    path('profile/', views.profile_view, name='profile_view'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    # العناوين
    path('addresses/', views.addresses_list, name='addresses_list'),
    path('addresses/add/', views.address_add, name='address_add'),
    path('addresses/<int:address_id>/edit/', views.address_edit, name='address_edit'),
    path('addresses/<int:address_id>/delete/', views.address_delete, name='address_delete'),
    path('addresses/<int:address_id>/set-default/', views.address_set_default, name='address_set_default'),
    # البحث
    path('search/', views.search, name='search'),
    # عن المتجر واتصل بنا
    path('about/', views.about_view, name='about'),
    path('contact/', views.contact_view, name='contact'),

    # خدمة العملاء (الدردشة)
    path('support/', views.support_chat, name='support_chat'),
    path('support/new/', views.support_new_conversation, name='support_new_conversation'),
    path('support/poll/', views.support_poll, name='support_poll'),
    path('support/send/', views.support_send, name='support_send'),
    path('support/end/', views.support_end, name='support_end'),
    # لوحة الإدارة
    path('manage/', include('store.urls_manage')),
]
