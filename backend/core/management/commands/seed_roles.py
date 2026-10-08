from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create MakerVault Viewer, Editor, User and Supervisor groups."

    def handle(self, *args, **options):
        viewer, _ = Group.objects.get_or_create(name="Viewer")
        editor, _ = Group.objects.get_or_create(name="Editor")
        user, _ = Group.objects.get_or_create(name="User")
        supervisor, _ = Group.objects.get_or_create(name="Supervisor")

        core_permissions = Permission.objects.filter(content_type__app_label="core")
        viewer.permissions.set(core_permissions.filter(codename__startswith="view_"))
        editor_permissions = core_permissions.filter(codename__regex=r"^(view|add|change)_")
        delete_inventory = core_permissions.filter(codename="delete_inventoryitem")
        editor.permissions.set(editor_permissions | delete_inventory)

        # Keep the historical Editor/Viewer presets usable. User and Supervisor
        # start with those same capabilities, with settings authorization handled
        # by explicit role checks, never merely by visibility in the frontend.
        user.permissions.set(editor_permissions | delete_inventory)
        supervisor.permissions.set(editor_permissions | delete_inventory)
        self.stdout.write(self.style.SUCCESS(
            "MakerVault roles are ready: Viewer, Editor, User, Supervisor."
        ))
