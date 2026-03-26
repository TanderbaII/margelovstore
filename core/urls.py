from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.site_login, name="login"),
    path("logout/", views.user_logout, name="user_logout"),
    path("", views.product_list, name="product_list"),
    path("orders/", views.orders_list, name="orders_list"),
    path("panel/", views.admin_dashboard, name="admin_dashboard"),
    path("panel/orders/<int:order_id>/status/", views.admin_change_order_status, name="admin_change_order_status"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/quick-order/", views.quick_order_create, name="quick_order_create"),
]