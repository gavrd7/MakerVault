import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.first_run import create_token, token_valid


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class FirstRunSetupTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.location = Path(self.folder.name) / "setup.json"
        override = patch.dict("os.environ", {"MAKERVAULT_SETUP_TOKEN_FILE": str(self.location)})
        override.start()
        self.addCleanup(override.stop)

    def test_token_can_only_be_generated_before_admin_exists(self):
        token = create_token()
        self.assertTrue(token_valid(token))
        self.assertNotIn(token, self.location.read_text())
        get_user_model().objects.create_superuser("existing", "existing@example.test", "a-good-test-password")
        with self.assertRaises(ValueError):
            create_token()

    def test_invalid_token_cannot_create_admin(self):
        response = self.client.post("/setup/", {
            "token": "wrong", "username": "first", "email": "first@example.test",
            "password1": "a-distinct-strong-password-8", "password2": "a-distinct-strong-password-8"
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(is_superuser=True).exists())

    def test_valid_token_creates_first_admin_and_closes_wizard(self):
        token = create_token()
        response = self.client.post("/setup/", {
            "token": token, "username": "first", "email": "first@example.test",
            "password1": "a-distinct-strong-password-8", "password2": "a-distinct-strong-password-8"
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.get(username="first").is_superuser)
        self.assertFalse(self.location.exists())
        self.assertEqual(self.client.get("/setup/").status_code, 302)

    def test_expired_token_is_rejected(self):
        token = create_token()
        import json
        payload = json.loads(self.location.read_text())
        payload["expires"] = 0
        self.location.write_text(json.dumps(payload))
        self.assertFalse(token_valid(token))

    def test_token_page_is_not_embeddable(self):
        response = self.client.get("/setup/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "DENY")
