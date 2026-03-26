from collections import OrderedDict
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Order, OrderItem, Product


def _normalize_search_text(value: str) -> str:
    value = (value or "").lower().strip()
    value = value.replace("*", " ")
    value = value.replace("-", " ")
    value = value.replace("_", " ")
    value = " ".join(value.split())
    return value


def site_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.session.get("site_access_granted", False):
            return redirect("login")
        return view_func(request, *args, **kwargs)
    return wrapper


def superuser_site_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.session.get("site_access_granted", False):
            return redirect("login")
        if not request.user.is_superuser:
            messages.error(request, "У вас нет доступа к панели управления.")
            return redirect("product_list")
        return view_func(request, *args, **kwargs)
    return wrapper


def site_login(request):
    if request.user.is_authenticated and request.session.get("site_access_granted", False):
        return redirect("product_list")

    form = AuthenticationForm(request, data=request.POST or None)

    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            request.session["site_access_granted"] = True
            return redirect("product_list")
        messages.error(request, "Неверный логин или пароль.")

    return render(request, "registration/login.html", {"form": form})


@site_login_required
def product_list(request):
    query = (request.GET.get("q") or "").strip()

    products_qs = Product.objects.all().prefetch_related("sizes").order_by("name")
    products = list(products_qs)

    if query:
        q = _normalize_search_text(query)
        filtered = []

        for product in products:
            name_text = _normalize_search_text(product.name)
            sku_text = _normalize_search_text(product.sku)
            combined = f"{name_text} {sku_text}"

            if q in name_text or q in sku_text or q in combined:
                filtered.append(product)

        products = filtered

    context = {
        "products": products,
        "query": query,
    }
    return render(request, "core/product_list.html", context)


@site_login_required
def product_detail(request, pk: int):
    product = get_object_or_404(Product.objects.prefetch_related("sizes"), pk=pk)
    return render(request, "core/product_detail.html", {"product": product})


@site_login_required
def orders_list(request):
    orders = (
        Order.objects.prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related("product"))
        )
        .all()
        .order_by("-created_at")
    )

    grouped_orders = OrderedDict()
    for order in orders:
        local_dt = timezone.localtime(order.created_at)
        day_label = local_dt.strftime("%d.%m.%Y")
        grouped_orders.setdefault(day_label, []).append(order)

    return render(request, "core/orders_list.html", {"grouped_orders": grouped_orders})


@site_login_required
@require_http_methods(["POST"])
def quick_order_create(request, pk: int):
    product = get_object_or_404(Product.objects.prefetch_related("sizes"), pk=pk)

    size = (request.POST.get("size") or "").strip()
    qty_raw = (request.POST.get("quantity") or "1").strip()

    try:
        quantity = int(qty_raw)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        messages.error(request, "Количество должно быть числом больше 0.")
        return redirect("product_detail", pk=pk)

    try:
        order = Order.objects.create(status=Order.Status.PROCESSING)
        OrderItem.objects.create(order=order, product=product, size=size, quantity=quantity)
        order.apply_status_transition(None, Order.Status.PROCESSING, changed_by_user=request.user)
    except Exception as e:
        messages.error(request, f"Не получилось создать заказ: {e}")
        return redirect("product_detail", pk=pk)

    messages.success(request, f"Заказ #{order.id} создан.")
    return redirect("orders_list")


@superuser_site_required
def admin_dashboard(request):
    orders = (
        Order.objects.prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related("product"))
        )
        .all()
        .order_by("-created_at")
    )

    status_filter = (request.GET.get("status") or "").strip()
    if status_filter in {
        Order.Status.PROCESSING,
        Order.Status.SHIPPED,
        Order.Status.DELIVERED,
    }:
        orders = orders.filter(status=status_filter)

    today = timezone.localdate()
    today_orders = [o for o in orders if timezone.localtime(o.created_at).date() == today]

    total_orders = orders.count()
    processing_count = orders.filter(status=Order.Status.PROCESSING).count()
    shipped_count = orders.filter(status=Order.Status.SHIPPED).count()
    delivered_count = orders.filter(status=Order.Status.DELIVERED).count()

    total_revenue = Decimal("0.00")
    total_profit = Decimal("0.00")

    for order in orders:
        total_revenue += order.total_sum()
        total_profit += order.total_profit()

    low_stock_products = []
    for product in Product.objects.prefetch_related("sizes").all():
        if product.available_stock() <= 3:
            low_stock_products.append(product)

    grouped_orders = OrderedDict()
    for order in orders:
        local_dt = timezone.localtime(order.created_at)
        day_label = local_dt.strftime("%d.%m.%Y")
        grouped_orders.setdefault(day_label, []).append(order)

    context = {
        "grouped_orders": grouped_orders,
        "status_filter": status_filter,
        "total_orders": total_orders,
        "processing_count": processing_count,
        "shipped_count": shipped_count,
        "delivered_count": delivered_count,
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "today_orders_count": len(today_orders),
        "low_stock_products": low_stock_products[:12],
    }
    return render(request, "core/admin_dashboard.html", context)


@superuser_site_required
@require_http_methods(["POST"])
def admin_change_order_status(request, order_id: int):
    order = get_object_or_404(Order, pk=order_id)
    new_status = (request.POST.get("status") or "").strip()
    old_status = order.status

    allowed = {
        Order.Status.PROCESSING,
        Order.Status.SHIPPED,
        Order.Status.DELIVERED,
    }

    if new_status not in allowed:
        messages.error(request, "Неверный статус.")
        return redirect("admin_dashboard")

    try:
        with transaction.atomic():
            order.status = new_status
            order.save(update_fields=["status"])
            order.apply_status_transition(old_status, new_status, changed_by_user=request.user)
        messages.success(request, f"Заказ #{order.id}: статус изменён на «{order.get_status_display()}».")
    except Exception as e:
        messages.error(request, f"Не удалось изменить статус заказа #{order.id}: {e}")

    return redirect("admin_dashboard")


def user_logout(request):
    request.session.pop("site_access_granted", None)
    logout(request)
    return redirect("login")