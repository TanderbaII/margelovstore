from datetime import timedelta
from decimal import Decimal

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Order, OrderItem, OrderStatusHistory, Product, ProductSize


admin.site.site_header = "CRM система"
admin.site.site_title = "CRM система"
admin.site.index_title = "Панель управления"


class ProductSizeInline(admin.TabularInline):
    model = ProductSize
    extra = 0
    fields = ("label", "stock", "reserved")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "image_preview",
        "name",
        "sku",
        "purchase_price",
        "sale_price",
        "profit_per_item",
        "stock_view",
        "reserved_view",
        "available_view",
        "has_sizes",
    )
    search_fields = ("name", "sku")
    ordering = ("name",)
    list_per_page = 50
    inlines = [ProductSizeInline]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.prefetch_related("sizes")

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height: 50px;" />', obj.image.url)
        return "—"
    image_preview.short_description = "Фото"

    def stock_view(self, obj):
        return obj.total_stock()
    stock_view.short_description = "Остаток"

    def reserved_view(self, obj):
        return obj.total_reserved()
    reserved_view.short_description = "Резерв"

    def available_view(self, obj):
        available = obj.available_stock()
        return "❌ 0" if available == 0 else f"✅ {available}"
    available_view.short_description = "Доступно"

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return request.user.has_perm("core.view_product")

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ProductSize)
class ProductSizeAdmin(admin.ModelAdmin):
    list_display = ("product", "label", "stock", "reserved", "available")
    search_fields = ("product__name", "product__sku", "label")
    list_filter = ("label",)
    list_select_related = ("product",)

    def available(self, obj):
        return obj.available()
    available.short_description = "Доступно"

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return request.user.has_perm("core.view_productsize")

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1
    fields = ("product", "size", "quantity")


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("changed_at", "changed_by", "old_status", "new_status")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "created_at",
        "reserved_applied",
        "stock_deducted",
        "total_sum",
        "total_profit",
    )
    list_filter = ("status", "created_at", "reserved_applied", "stock_deducted")
    search_fields = ("id",)
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50

    fields = (
        "status",
        "shipping_service",
        "tracking_number",
        "shipped_at",
        "delivered_at",
        "reserved_applied",
        "stock_deducted",
    )
    readonly_fields = ("reserved_applied", "stock_deducted", "shipped_at", "delivered_at")

    change_form_template = "admin/core/order/change_form.html"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related("product"))
        )

    def save_model(self, request, obj, form, change):
        if change and obj.pk:
            old_obj = Order.objects.get(pk=obj.pk)
            obj._old_status_for_transition = old_obj.status
            obj._is_new_for_transition = False
        else:
            obj._old_status_for_transition = None
            obj._is_new_for_transition = True

        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)

        order = form.instance
        old_status = getattr(order, "_old_status_for_transition", None)
        is_new = getattr(order, "_is_new_for_transition", False)

        if is_new or old_status != order.status:
            try:
                with transaction.atomic():
                    order.apply_status_transition(old_status, order.status, changed_by_user=request.user)
            except Exception as e:
                self.message_user(request, f"Ошибка обработки статуса: {e}", level=messages.ERROR)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("dashboard/", self.admin_site.admin_view(self.dashboard_view), name="core_dashboard"),
            path(
                "<int:order_id>/set-status/<str:new_status>/",
                self.admin_site.admin_view(self.set_status_view),
                name="core_order_set_status",
            ),
        ]
        return custom + urls

    def dashboard_view(self, request):
        now = timezone.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)

        def calc(qs):
            revenue = Decimal("0.00")
            profit = Decimal("0.00")
            count = qs.count()

            for order in qs.prefetch_related("items__product"):
                revenue += order.total_sum()
                profit += order.total_profit()

            return count, revenue, profit

        qs_all = Order.objects.all()
        c_today, r_today, p_today = calc(qs_all.filter(created_at__gte=day_start))
        c_7, r_7, p_7 = calc(qs_all.filter(created_at__gte=week_start))
        c_30, r_30, p_30 = calc(qs_all.filter(created_at__gte=month_start))

        context = dict(
            self.admin_site.each_context(request),
            title="CRM Dashboard",
            c_today=c_today,
            r_today=r_today,
            p_today=p_today,
            c_7=c_7,
            r_7=r_7,
            p_7=p_7,
            c_30=c_30,
            r_30=r_30,
            p_30=p_30,
        )
        return render(request, "admin/core/dashboard.html", context)

    def set_status_view(self, request, order_id, new_status):
        order = Order.objects.get(pk=order_id)
        old_status = order.status

        allowed = {status for status, _ in Order.Status.choices}
        if new_status not in allowed:
            messages.error(request, "Неверный статус.")
            return redirect("../..")

        try:
            with transaction.atomic():
                order.status = new_status
                order.save(update_fields=["status"])
                order.apply_status_transition(old_status, new_status, changed_by_user=request.user)
            messages.success(request, f"Статус изменён: {old_status} → {new_status}")
        except Exception as e:
            messages.error(request, f"Не получилось изменить статус: {e}")

        return redirect(reverse("admin:core_order_change", args=[order_id]))


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "size", "quantity")
    search_fields = ("order__id", "product__name", "product__sku", "size")
    list_select_related = ("order", "product")

    def has_module_permission(self, request):
        return request.user.is_superuser


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "old_status", "new_status", "changed_at", "changed_by")
    readonly_fields = ("order", "old_status", "new_status", "changed_at", "changed_by")
    list_select_related = ("order", "changed_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
