import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0056_personal_spool_image_paths"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ReusableSpoolCatalogueSuggestion",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("manufacturer", models.CharField(max_length=120)),
                ("name", models.CharField(max_length=200)),
                ("design_type", models.CharField(max_length=20, choices=[("manufacturer", "Manufacturer-made"), ("printed", "3D printed")])),
                ("source_url", models.URLField(max_length=500)),
                ("proposed_specs", models.JSONField(default=dict, blank=True)),
                ("status", models.CharField(max_length=20, default="pending", choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")])),
                ("review_note", models.TextField(blank=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
