from django.core.management.base import BaseCommand

from market.models import Category


DEFAULT_CATEGORIES = (
    ("디지털·가전", "electronics"),
    ("패션·잡화", "fashion"),
    ("생활·가구", "home"),
    ("도서·취미", "books-hobby"),
    ("스포츠·레저", "sports"),
    ("기타", "other"),
)


class Command(BaseCommand):
    help = "Create the baseline active product categories without duplicates."

    def handle(self, *args, **options):
        created = 0
        for name, slug in DEFAULT_CATEGORIES:
            _, was_created = Category.objects.get_or_create(slug=slug, defaults={"name": name, "is_active": True})
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Categories ready: {len(DEFAULT_CATEGORIES) - created} existing, {created} created."))
