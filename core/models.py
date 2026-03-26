from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Product(models.Model):
    name = models.CharField("Название", max_length=150)
    sku = models.CharField("Артикул (SKU)", max_length=50, unique=True)

    image = models.ImageField("Фото товара", upload_to="products/", blank=True, null=True)

    purchase_price = models.DecimalField(
        "Закупочная цена",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    sale_price = models.DecimalField(
        "Цена продажи",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    stock = models.IntegerField("Остаток (если нет размеров)", validators=[MinValueValidator(0)], default=0)
    reserved = models.IntegerField("Резерв (если нет размеров)", validators=[MinValueValidator(0)], default=0)

    import_uid = models.CharField("UID импорта", max_length=255, blank=True, null=True, unique=True)
    import_source = models.CharField("Источник импорта", max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def profit_per_item(self):
        return self.sale_price - self.purchase_price
    profit_per_item.short_description = "Прибыль за 1 шт."

    def _prefetched_sizes(self):
        cache = getattr(self, "_prefetched_objects_cache", {})
        return cache.get("sizes")

    def has_sizes(self):
        prefetched_sizes = self._prefetched_sizes()
        if prefetched_sizes is not None:
            return bool(prefetched_sizes)
        return self.sizes.exists()
    has_sizes.short_description = "Есть размеры?"

    def total_stock(self):
        prefetched_sizes = self._prefetched_sizes()
        if prefetched_sizes is not None:
            if prefetched_sizes:
                return sum(size.stock for size in prefetched_sizes)
            return self.stock
        if self.has_sizes():
            return sum(s.stock for s in self.sizes.all())
        return self.stock
    total_stock.short_description = "Остаток"

    def total_reserved(self):
        prefetched_sizes = self._prefetched_sizes()
        if prefetched_sizes is not None:
            if prefetched_sizes:
                return sum(size.reserved for size in prefetched_sizes)
            return self.reserved
        if self.has_sizes():
            return sum(s.reserved for s in self.sizes.all())
        return self.reserved
    total_reserved.short_description = "Резерв"

    def available_stock(self):
        return max(0, self.total_stock() - self.total_reserved())
    available_stock.short_description = "Доступно"


class ProductSize(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="sizes", verbose_name="Товар")
    label = models.CharField("Размер", max_length=20)
    stock = models.IntegerField("Остаток размера", validators=[MinValueValidator(0)], default=0)
    reserved = models.IntegerField("Резерв размера", validators=[MinValueValidator(0)], default=0)

    class Meta:
        unique_together = ("product", "label")
        verbose_name = "Размер товара"
        verbose_name_plural = "Размеры товара"
        ordering = ("product", "label")

    def __str__(self):
        return f"{self.product.sku} — {self.label}"

    def available(self):
        return max(0, self.stock - self.reserved)


class Order(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "В обработке"
        SHIPPED = "shipped", "Отправлен"
        DELIVERED = "delivered", "Доставлен"

    class ShippingService(models.TextChoices):
        NONE = "none", "—"
        CDEK = "cdek", "СДЭК"
        RUS_POST = "rus_post", "Почта России"
        BOXBERRY = "boxberry", "Boxberry"
        YANDEX = "yandex", "Яндекс"
        OTHER = "other", "Другое"

    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.PROCESSING)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    reserved_applied = models.BooleanField("Резерв применён", default=False)
    stock_deducted = models.BooleanField("Остаток списан", default=False)

    shipping_service = models.CharField(
        "Служба доставки",
        max_length=30,
        choices=ShippingService.choices,
        default=ShippingService.NONE,
    )
    tracking_number = models.CharField("Трек-номер", max_length=80, blank=True)
    shipped_at = models.DateTimeField("Отправлен (дата)", blank=True, null=True)
    delivered_at = models.DateTimeField("Доставлен (дата)", blank=True, null=True)

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ("-created_at",)

    def __str__(self):
        return f"Заказ #{self.id}"

    def _prefetched_items(self):
        cache = getattr(self, "_prefetched_objects_cache", {})
        return cache.get("items")

    def total_sum(self):
        total = Decimal("0.00")
        items = self._prefetched_items()
        if items is None:
            items = self.items.select_related("product").all()
        for item in items:
            total += item.line_sum()
        return total
    total_sum.short_description = "Сумма заказа"

    def total_profit(self):
        if self.status != Order.Status.DELIVERED:
            return Decimal("0.00")

        total = Decimal("0.00")
        items = self._prefetched_items()
        if items is None:
            items = self.items.select_related("product").all()
        for item in items:
            total += item.profit()
        return total
    total_profit.short_description = "Прибыль заказа"

    def _reserve_item(self, item):
        product = item.product

        if product.has_sizes():
            size_obj = product.sizes.get(label=item.size)

            if size_obj.available() < item.quantity:
                raise ValidationError(
                    f"Недостаточно товара '{product.name}' размера '{item.size}'. "
                    f"Нужно: {item.quantity}, доступно: {size_obj.available()}."
                )

            size_obj.reserved += item.quantity
            size_obj.save(update_fields=["reserved"])
        else:
            available = max(0, product.stock - product.reserved)

            if available < item.quantity:
                raise ValidationError(
                    f"Недостаточно товара '{product.name}'. "
                    f"Нужно: {item.quantity}, доступно: {available}."
                )

            product.reserved += item.quantity
            product.save(update_fields=["reserved"])

    def _release_reserve_item(self, item):
        product = item.product

        if product.has_sizes():
            size_obj = product.sizes.get(label=item.size)
            size_obj.reserved = max(0, size_obj.reserved - item.quantity)
            size_obj.save(update_fields=["reserved"])
        else:
            product.reserved = max(0, product.reserved - item.quantity)
            product.save(update_fields=["reserved"])

    def _deduct_item_from_stock(self, item):
        product = item.product

        if product.has_sizes():
            size_obj = product.sizes.get(label=item.size)

            if size_obj.stock < item.quantity:
                raise ValidationError(
                    f"Недостаточно физического остатка '{product.name}' размера '{item.size}'. "
                    f"Нужно: {item.quantity}, stock: {size_obj.stock}."
                )

            size_obj.stock -= item.quantity
            size_obj.save(update_fields=["stock"])
        else:
            if product.stock < item.quantity:
                raise ValidationError(
                    f"Недостаточно физического остатка '{product.name}'. "
                    f"Нужно: {item.quantity}, stock: {product.stock}."
                )

            product.stock -= item.quantity
            product.save(update_fields=["stock"])

    def apply_status_transition(self, old_status, new_status, changed_by_user=None):
        items = list(self.items.select_related("product").all())

        if not items:
            return

        for item in items:
            item.full_clean()

        if old_status != new_status or old_status is None:
            OrderStatusHistory.objects.create(
                order=self,
                old_status=old_status or "",
                new_status=new_status,
                changed_by=changed_by_user if changed_by_user and getattr(changed_by_user, "is_authenticated", False) else None,
            )

        if new_status == Order.Status.PROCESSING and not self.reserved_applied and not self.stock_deducted:
            for item in items:
                self._reserve_item(item)

            self.reserved_applied = True
            self.save(update_fields=["reserved_applied"])

        if new_status in {Order.Status.SHIPPED, Order.Status.DELIVERED} and not self.stock_deducted:
            if not self.reserved_applied:
                for item in items:
                    self._reserve_item(item)
                self.reserved_applied = True

            for item in items:
                self._deduct_item_from_stock(item)

            for item in items:
                self._release_reserve_item(item)

            self.stock_deducted = True
            self.reserved_applied = False
            self.shipped_at = self.shipped_at or timezone.now()
            self.save(update_fields=["stock_deducted", "reserved_applied", "shipped_at"])

        if new_status == Order.Status.DELIVERED and self.delivered_at is None:
            self.delivered_at = timezone.now()
            self.save(update_fields=["delivered_at"])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", verbose_name="Заказ")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Товар")
    size = models.CharField("Размер", max_length=20, blank=True)
    quantity = models.IntegerField("Количество", validators=[MinValueValidator(1)], default=1)

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"

    def __str__(self):
        if self.size:
            return f"{self.product.name} [{self.size}] x {self.quantity}"
        return f"{self.product.name} x {self.quantity}"

    def clean(self):
        if self.product_id:
            has_sizes = self.product.sizes.exists()

            if has_sizes:
                if not self.size:
                    raise ValidationError("Для товара с размерами нужно указать размер.")
                if not self.product.sizes.filter(label=self.size).exists():
                    raise ValidationError(f"Размер '{self.size}' не существует у товара {self.product.sku}.")
            else:
                if self.size:
                    raise ValidationError("Нельзя указывать размер у товара без размеров.")

    def line_sum(self):
        return self.product.sale_price * self.quantity

    def profit(self):
        return (self.product.sale_price - self.product.purchase_price) * self.quantity


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history", verbose_name="Заказ")
    old_status = models.CharField("Старый статус", max_length=20, blank=True)
    new_status = models.CharField("Новый статус", max_length=20)
    changed_at = models.DateTimeField("Изменено", auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Кто изменил",
    )

    class Meta:
        verbose_name = "История статусов"
        verbose_name_plural = "История статусов"
        ordering = ("-changed_at",)

    def __str__(self):
        return f"Order #{self.order_id}: {self.old_status} -> {self.new_status}"
