import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update the administrator configured by environment variables."

    def handle(self, *args, **options):
        username = os.getenv("MAKERVAULT_ADMIN_USERNAME", "admin")
        password = os.getenv("MAKERVAULT_ADMIN_PASSWORD", "")
        email = os.getenv("MAKERVAULT_ADMIN_EMAIL", "")
        if not password:
            self.stdout.write("MAKERVAULT_ADMIN_PASSWORD is empty; nothing to do.")
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"email": email})
        user.email = email or user.email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} administrator '{username}'."))
