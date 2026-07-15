from django.core.management.base import BaseCommand
from apps.authentication.models import User, Role


class Command(BaseCommand):
    help = "Assign the USER role to all users who have no role assigned."

    def handle(self, *args, **options):
        role_obj, created = Role.objects.get_or_create(
            name=Role.ROLES.USER,
            defaults={"description": "Standard user role"},
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created missing role: {Role.ROLES.USER}")
            )

        users_without_role = User.objects.filter(roles=None)
        count = users_without_role.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("All users already have a role assigned."))
            return

        for user in users_without_role:
            user.roles.add(role_obj)
            self.stdout.write(f"Assigned USER role to {user.email or user.username}")

        self.stdout.write(
            self.style.SUCCESS(f"Done. Assigned USER role to {count} user(s).")
        )
