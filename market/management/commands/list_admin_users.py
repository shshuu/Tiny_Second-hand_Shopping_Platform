from django.core.management.base import BaseCommand

from market.models import User


class Command(BaseCommand):
    help = "List project operations users without exposing credentials."

    def handle(self, *args, **options):
        users = User.objects.exclude(role=User.Role.USER).order_by("username")
        if not users.exists():
            self.stdout.write("No administrative users found.")
            return
        for user in users:
            self.stdout.write(f"username={user.username}\tpublic_id={user.public_id}\trole={user.role}\tstatus={user.status}\tis_staff={user.is_staff}\tis_superuser={user.is_superuser}")
