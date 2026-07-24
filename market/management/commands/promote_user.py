from django.core.management.base import BaseCommand, CommandError

from market.models import AuditLog, User


class Command(BaseCommand):
    help = "Set a local user's project operations role."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", required=True, choices=User.Role.values)

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{options['username']}' does not exist.") from exc
        before, after = user.role, options["role"]
        if before == after:
            self.stdout.write(f"User '{user.username}' role unchanged: {after} -> {after}.")
            return
        user.role = after
        user.save(update_fields=["role"])
        AuditLog.objects.create(action="user.role", target=str(user.public_id), reason=f"management-command: {before}->{after}")
        self.stdout.write(self.style.SUCCESS(f"User '{user.username}' role changed: {before} -> {after}"))
