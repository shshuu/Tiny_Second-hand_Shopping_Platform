from django.core.management.base import BaseCommand

from market.models import User


class Command(BaseCommand):
    help = "List project operations users without exposing credentials."

    def handle(self, *args, **options):
        users = User.objects.exclude(role=User.Role.USER).order_by("username")
        if not users.exists():
            self.stdout.write("No operations users.")
            return
        for user in users:
            self.stdout.write(f"{user.username}\t{user.role}\t{user.status}\t{user.public_id}")
