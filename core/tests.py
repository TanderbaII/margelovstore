from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Order, OrderItem, OrderStatusHistory, Product, ProductSize


class QuickOrderCreateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="employee",
            password="test-pass-123",
            is_staff=True,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["site_access_granted"] = True
        session.save()

    def test_does_not_persist_order_when_product_is_out_of_stock(self):
        product = Product.objects.create(
            name="No Stock Product",
            sku="NO-STOCK-001",
            purchase_price="100.00",
            sale_price="150.00",
            stock=0,
            reserved=0,
        )

        response = self.client.post(
            reverse("quick_order_create", args=[product.pk]),
            {"quantity": "1"},
        )

        self.assertRedirects(response, reverse("product_detail", args=[product.pk]))
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(OrderStatusHistory.objects.count(), 0)
        product.refresh_from_db()
        self.assertEqual(product.reserved, 0)

    def test_does_not_persist_order_when_size_is_out_of_stock(self):
        product = Product.objects.create(
            name="Sized Product",
            sku="SIZE-001",
            purchase_price="100.00",
            sale_price="150.00",
            stock=0,
            reserved=0,
        )
        ProductSize.objects.create(product=product, label="M", stock=0, reserved=0)

        response = self.client.post(
            reverse("quick_order_create", args=[product.pk]),
            {"size": "M", "quantity": "1"},
        )

        self.assertRedirects(response, reverse("product_detail", args=[product.pk]))
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(OrderStatusHistory.objects.count(), 0)

    def test_persists_order_when_stock_is_available(self):
        product = Product.objects.create(
            name="Available Product",
            sku="IN-STOCK-001",
            purchase_price="100.00",
            sale_price="150.00",
            stock=2,
            reserved=0,
        )

        response = self.client.post(
            reverse("quick_order_create", args=[product.pk]),
            {"quantity": "1"},
        )

        self.assertRedirects(response, reverse("orders_list"))
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)
        self.assertEqual(OrderStatusHistory.objects.count(), 1)

        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.PROCESSING)
        self.assertTrue(order.reserved_applied)

        product.refresh_from_db()
        self.assertEqual(product.reserved, 1)
