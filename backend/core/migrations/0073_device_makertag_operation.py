from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0072_spool_second_rfid_uid"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceMakerTagOperation",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tag_id_snapshot", models.UUIDField()),
                ("expected_uid", models.CharField(max_length=24)),
                ("expected_short_id", models.CharField(max_length=8)),
                ("target_type", models.CharField(max_length=24)),
                ("target_id", models.UUIDField()),
                ("action", models.CharField(max_length=8, choices=[("clean", "Clean"), ("remove", "Remove")])),
                ("also_clean", models.BooleanField(default=False)),
                ("source", models.CharField(max_length=10, choices=[("browser", "Browser"), ("terminal", "Terminal")])),
                ("state", models.CharField(max_length=12, default="pending", choices=[
                    ("pending", "Pending"), ("cleaned", "NFC cleared"),
                    ("completed", "Completed"), ("cancelled", "Cancelled")])),
                ("expires_at", models.DateTimeField()),
                ("cleaned_at", models.DateTimeField(null=True, blank=True)),
                ("completed_at", models.DateTimeField(null=True, blank=True)),
                ("device", models.ForeignKey(to="core.connecteddevice", on_delete=django.db.models.deletion.CASCADE,
                                            related_name="maker_tag_operations")),
                ("owner", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE,
                                           related_name="maker_tag_operations")),
                ("tag", models.ForeignKey(to="core.makertag", on_delete=django.db.models.deletion.SET_NULL,
                                         null=True, blank=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="devicemakertagoperation",
            index=models.Index(fields=["device", "state", "expires_at"], name="mkt_op_device_state_idx"),
        ),
    ]
