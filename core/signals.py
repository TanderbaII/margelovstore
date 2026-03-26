from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Order


@receiver(post_save, sender=Order)
def stock_actions_after_order_save(sender, instance: Order, created, **kwargs):
    """
    Надёжно для Django Admin:
    - Если статус SHIPPED и остаток ещё не списан -> списываем.
    - Если статус CANCELLED и остаток был списан -> возвращаем.
    Позиции заказа берём из БД (order.items.all()).
    """
    order = instance  # просто для читаемости

    # 1) Списание при SHIPPED
    if order.status == Order.Status.SHIPPED and not order.stock_deducted:
        items = list(order.items.select_related("product").all())

        # Если позиций нет — смысла списывать нет (и это сигнал, что заказ пустой)
        if not items:
            return

        # Проверка остатков
        for item in items:
            if item.product.stock < item.quantity:
                raise ValidationError(
                    f"Недостаточно товара '{item.product.name}' на складе. "
                    f"Нужно: {item.quantity}, есть: {item.product.stock}"
                )

        # Списываем
        with transaction.atomic():
            for item in items:
                p = item.product
                p.stock -= item.quantity
                p.save(update_fields=["stock"])

            # Обновляем флаг в базе (и не вызываем сигнал повторно)
            Order.objects.filter(pk=order.pk).update(stock_deducted=True)

    # 2) Возврат при CANCELLED
    if order.status == Order.Status.CANCELLED and order.stock_deducted:
        items = list(order.items.select_related("product").all())
        if not items:
            return

        with transaction.atomic():
            for item in items:
                p = item.product
                p.stock += item.quantity
                p.save(update_fields=["stock"])

            Order.objects.filter(pk=order.pk).update(stock_deducted=False)
