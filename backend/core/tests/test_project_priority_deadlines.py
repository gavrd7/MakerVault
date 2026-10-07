from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import Project


class ProjectPriorityDeadlineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="project-priority-admin",
            email="priority@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_project_create_and_update_support_priority_and_due_date(self):
        due = timezone.localdate() + timedelta(days=3)
        response = self.client.post(
            "/api/projects/",
            data={
                "name": "Priority build",
                "status": "active",
                "priority": 1,
                "due_date": due.isoformat(),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()["project"]
        self.assertEqual(payload["priority"], 1)
        self.assertEqual(payload["priority_label"], "P1 — Highest")
        self.assertEqual(payload["due_date"], due.isoformat())
        self.assertEqual(payload["deadline_state"], "due_soon")
        self.assertEqual(payload["days_until_due"], 3)

        project_id = payload["id"]
        updated = self.client.patch(
            f"/api/projects/{project_id}/",
            data={"priority": 4, "due_date": ""},
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        payload = updated.json()["project"]
        self.assertEqual(payload["priority"], 4)
        self.assertEqual(payload["due_date"], "")
        self.assertEqual(payload["deadline_state"], "none")

    def test_project_rejects_priority_outside_one_to_five(self):
        response = self.client.post(
            "/api/projects/",
            data={"name": "Bad priority", "priority": 6},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("priority", response.json()["fields"])

    def test_overdue_deadline_is_suppressed_for_completed_project(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        active = Project.objects.create(
            owner=self.user,
            created_by=self.user,
            name="Late active project",
            status="active",
            priority=2,
            due_date=yesterday,
        )
        complete = Project.objects.create(
            owner=self.user,
            created_by=self.user,
            name="Late completed project",
            status="complete",
            priority=1,
            due_date=yesterday,
        )

        active_payload = self.client.get(f"/api/projects/{active.id}/").json()["project"]
        complete_payload = self.client.get(f"/api/projects/{complete.id}/").json()["project"]

        self.assertEqual(active_payload["deadline_state"], "overdue")
        self.assertEqual(active_payload["deadline_label"], "Overdue by 1 day")
        self.assertEqual(complete_payload["deadline_state"], "closed")
        self.assertFalse(complete_payload["days_until_due"])

    def test_dashboard_attention_orders_deadline_urgency_then_priority(self):
        today = timezone.localdate()
        overdue = Project.objects.create(
            owner=self.user,
            created_by=self.user,
            name="Overdue P5",
            status="active",
            priority=5,
            due_date=today - timedelta(days=2),
        )
        due_soon = Project.objects.create(
            owner=self.user,
            created_by=self.user,
            name="Soon P3",
            status="planning",
            priority=3,
            due_date=today + timedelta(days=2),
        )
        high_priority = Project.objects.create(
            owner=self.user,
            created_by=self.user,
            name="P1 no deadline",
            status="idea",
            priority=1,
        )
        Project.objects.create(
            owner=self.user,
            created_by=self.user,
            name="No attention metadata",
            status="active",
        )
        Project.objects.create(
            owner=self.user,
            created_by=self.user,
            name="Completed overdue",
            status="complete",
            priority=1,
            due_date=today - timedelta(days=5),
        )

        response = self.client.get("/api/dashboard/")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        ids = [row["id"] for row in payload["project_attention"]]

        self.assertEqual(ids[:3], [str(overdue.id), str(due_soon.id), str(high_priority.id)])
        self.assertEqual(payload["projects_deadline_alerts"], 2)
        self.assertEqual(payload["project_attention"][0]["deadline_state"], "overdue")
