from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import DeviceWeightMeasurement, Project


class BrowserWeightHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="history-owner", password="pass")
        self.other = User.objects.create_user(username="history-other", password="pass")
        self.project = Project.objects.create(owner=self.owner, name="Finished product")
        self.foreign = Project.objects.create(owner=self.other, name="Private product")
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_project"))
        DeviceWeightMeasurement.objects.create(
            owner=self.owner, request_id=uuid4(), target_type="project",
            target_id=self.project.pk, gross_weight_g=Decimal("22.50"),
            tare_weight_g=Decimal("2.50"), net_weight_g=Decimal("20.00"),
        )

    def test_authenticated_owner_can_read_history(self):
        self.client.force_login(self.owner)
        response = self.client.get("/api/weight-history/", {
            "target_type": "project", "target_id": str(self.project.pk),
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["rows"][0]["net_weight_g"], "20.00")

    def test_sessions_required_and_other_owner_invisible(self):
        params = {"target_type": "project", "target_id": str(self.project.pk)}
        self.assertEqual(self.client.get("/api/weight-history/", params).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/weight-history/", {
            "target_type": "project", "target_id": str(self.foreign.pk),
        }).status_code, 404)

    def test_permission_revocation_and_invalid_limits(self):
        self.client.force_login(self.owner)
        params = {"target_type": "project", "target_id": str(self.project.pk)}
        self.assertEqual(self.client.get("/api/weight-history/", {**params, "limit": "0"}).status_code, 400)
        self.owner.user_permissions.clear()
        self.assertEqual(self.client.get("/api/weight-history/", params).status_code, 403)
