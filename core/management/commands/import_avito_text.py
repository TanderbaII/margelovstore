import re
import hashlib
from decimal import Decimal

from django.core.management.base import BaseCommand
from core.models import Product


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def parse_price(line: str):
    if not line or "₽" not in line:
        return None

    cleaned = line.replace("₽", "")
    cleaned = cleaned.replace("\u202f", " ")  # узкий пробел
    cleaned = cleaned.replace("\xa0", " ")   # неразрывный пробел
    cleaned = cleaned.strip()

    cleaned = re.sub(r"[^\d ]", "", cleaned)
    cleaned = cleaned.replace(" ", "").strip()
    if not cleaned.isdigit():
        return None

    return Decimal(cleaned)


def build_uid(source: str, title: str, price: Decimal | None):
    base = f"{source}|{normalize_spaces(title).lower()}|{str(price) if price is not None else ''}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def build_sku(uid: str) -> str:
    # короткий SKU, уникальный
    return f"AV-{uid[:10].upper()}"


class Command(BaseCommand):
    help = (
        "Импорт товаров из копипасты страницы Авито (активные/архив). "
        "Добавляет только новые позиции, не удаляет старые. "
        "Остатки не импортируются (stock=0). "
        "purchase_price ставится 0 (потом заполнишь вручную)."
    )

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к txt-файлу (например imports/active.txt)")
        parser.add_argument("--source", type=str, default="avito_active",
                            help="Источник (например avito_active или avito_archive)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Показать что будет импортировано, но ничего не сохранять")

    def handle(self, *args, **options):
        filepath = options["filepath"]
        source = options["source"]
        dry_run = options["dry_run"]

        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        lines = [normalize_spaces(x) for x in raw.splitlines()]

        created = 0
        skipped = 0

        i = 0
        while i < len(lines):
            line = lines[i]

            # название = любая непустая строка, после которой в ближайших 3 строках есть цена "₽"
            if line and "₽" not in line and len(line) >= 3:
                price = None
                price_line_index = None

                for j in range(i + 1, min(i + 4, len(lines))):
                    p = parse_price(lines[j])
                    if p is not None:
                        price = p
                        price_line_index = j
                        break

                if price_line_index is not None:
                    title = line
                    uid = build_uid(source, title, price)

                    if Product.objects.filter(import_uid=uid).exists():
                        skipped += 1
                        i = price_line_index + 1
                        continue

                    sku = build_sku(uid)

                    if dry_run:
                        self.stdout.write(f"[DRY] ADD: {title} | price={price} | purchase=0 | stock=0 | sku={sku}")
                        created += 1
                        i = price_line_index + 1
                        continue

                    Product.objects.create(
                        name=title,
                        sku=sku,
                        purchase_price=Decimal("0"),
                        sale_price=price,
                        stock=0,
                        import_uid=uid,
                        import_source=source,
                    )

                    created += 1
                    i = price_line_index + 1
                    continue

            i += 1

        self.stdout.write(self.style.SUCCESS(f"Готово. Добавлено: {created}, пропущено (дубли): {skipped}."))
        if dry_run:
            self.stdout.write(self.style.WARNING("Это был dry-run, в БД ничего не записано."))
