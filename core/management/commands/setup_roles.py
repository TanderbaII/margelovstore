from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from core.models import Order, OrderItem, OrderStatusHistory, Product, ProductSize


class Command(BaseCommand):
    help = "Создает и обновляет роль 'Сотрудник'"

    def handle(self, *args, **kwargs):
        employee_group, _ = Group.objects.get_or_create(name="Сотрудник")

        permissions = []

        order_models = [Order, OrderItem, OrderStatusHistory]
        view_only_models = [Product, ProductSize]

        for model in order_models:
            content_type = ContentType.objects.get_for_model(model)
            model_permissions = Permission.objects.filter(
                content_type=content_type,
                codename__in=[
                    f"view_{model._meta.model_name}",
                    f"add_{model._meta.model_name}",
                    f"change_{model._meta.model_name}",
                    f"delete_{model._meta.model_name}",
                ],
            )
            permissions.extend(list(model_permissions))

        for model in view_only_models:
            content_type = ContentType.objects.get_for_model(model)
            model_permissions = Permission.objects.filter(
                content_type=content_type,
                codename__in=[
                    f"view_{model._meta.model_name}",
                ],
            )
            permissions.extend(list(model_permissions))

        employee_group.permissions.set(permissions)

        self.stdout.write(self.style.SUCCESS("Роль 'Сотрудник' создана/обновлена."))