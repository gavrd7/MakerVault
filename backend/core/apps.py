from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "MakerVault"

    def ready(self):
        # Register the separately maintained physical MakerTag operation model.
        from . import device_tag_operations_model  # noqa: F401
