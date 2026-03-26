from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.models import Product


class Command(BaseCommand):
    help = "Load the bundled product catalog when the database is empty."

    def handle(self, *args, **options):
        if Product.objects.exists():
            self.stdout.write("Catalog already exists, skipping seed.")
            return

        fixture_path = Path(settings.BASE_DIR) / "core" / "fixtures" / "catalog_seed.json"
        if not fixture_path.exists():
            self.stdout.write(
                self.style.WARNING(f"Catalog fixture not found: {fixture_path}")
            )
            return

        call_command("loaddata", str(fixture_path))
        self.stdout.write(self.style.SUCCESS("Loaded starter catalog."))
