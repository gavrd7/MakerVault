from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create MakerVault Viewer and Editor groups and assign core permissions."

    def handle(self, *args, **options):
        viewer, _ = Group.objects.get_or_create(name="Viewer")
        editor, _ = Group.objects.get_or_create(name="Editor")
        core_permissions = Permission.objects.filter(content_type__app_label="core")
        viewer.permissions.set(core_permissions.filter(codename__startswith="view_"))
        editor_permissions = core_permissions.filter(codename__regex=r"^(view|add|change)_")
        delete_inventory = core_permissions.filter(codename="delete_inventoryitem")
        editor.permissions.set(editor_permissions | delete_inventory)
        self.stdout.write(self.style.SUCCESS("MakerVault roles are ready: Viewer, Editor."))
