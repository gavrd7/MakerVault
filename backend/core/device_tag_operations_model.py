"""Django model for durable, owner/device-bound MakerTag NFC operations.

Imported by CoreConfig.ready() rather than enlarging the monolithic models.py.
"""
import uuid
from django.conf import settings
from django.db import models
from .models import TimeStampedModel


class DeviceMakerTagOperation(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="maker_tag_operations")
    device = models.ForeignKey("core.ConnectedDevice", on_delete=models.CASCADE,
                               related_name="maker_tag_operations")
    tag = models.ForeignKey("core.MakerTag", on_delete=models.SET_NULL, null=True, blank=True)
    tag_id_snapshot = models.UUIDField()
    expected_uid = models.CharField(max_length=24)
    expected_short_id = models.CharField(max_length=8)
    target_type = models.CharField(max_length=24)
    target_id = models.UUIDField()
    action = models.CharField(max_length=8, choices=[("clean", "Clean"), ("remove", "Remove")])
    also_clean = models.BooleanField(default=False)
    source = models.CharField(max_length=10, choices=[("browser", "Browser"), ("terminal", "Terminal")])
    state = models.CharField(max_length=12, default="pending", choices=[
        ("pending", "Pending"), ("cleaned", "NFC cleared"),
        ("completed", "Completed"), ("cancelled", "Cancelled"),
    ])
    expires_at = models.DateTimeField()
    cleaned_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "core"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["device", "state", "expires_at"],
                                name="mkt_op_device_state_idx")]
