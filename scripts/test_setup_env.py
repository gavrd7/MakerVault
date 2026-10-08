import tempfile
from pathlib import Path
from unittest import TestCase

from scripts.generate_env_secrets import setup_env


class SetupEnvironmentTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.example = self.root / ".env.example"
        self.env = self.root / ".env"
        self.example.write_text(
            "# MakerVault\nDJANGO_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_VALUE\n"
            "POSTGRES_PASSWORD=CHANGE_ME_DATABASE_PASSWORD\n"
            "MAKERVAULT_PORT=8766\n",
            encoding="utf-8",
        )

    def test_generates_two_separate_secrets_and_preserves_them(self):
        self.assertEqual(set(setup_env(self.env, self.example)),
                         {"DJANGO_SECRET_KEY", "POSTGRES_PASSWORD"})
        first = self.env.read_text(encoding="utf-8")
        self.assertNotIn("CHANGE_ME", first)
        keys = dict(line.split("=", 1) for line in first.splitlines() if "=" in line)
        self.assertNotEqual(keys["DJANGO_SECRET_KEY"], keys["POSTGRES_PASSWORD"])
        self.assertGreaterEqual(len(keys["DJANGO_SECRET_KEY"]), 64)
        self.assertEqual(keys["MAKERVAULT_PORT"], "8766")
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(setup_env(self.env, self.example), [])
        self.assertEqual(self.env.read_text(encoding="utf-8"), first)

    def test_preserves_custom_secret_and_repairs_other_placeholder(self):
        self.env.write_text(
            "DJANGO_SECRET_KEY=existing-secret-value\n"
            "POSTGRES_PASSWORD=CHANGE_ME_DATABASE_PASSWORD\n",
            encoding="utf-8",
        )
        self.assertEqual(setup_env(self.env, self.example), ["POSTGRES_PASSWORD"])
        self.assertIn("DJANGO_SECRET_KEY=existing-secret-value\n",
                      self.env.read_text(encoding="utf-8"))

    def test_missing_secrets_are_appended(self):
        self.env.write_text("MAKERVAULT_PORT=8766\n", encoding="utf-8")
        self.assertEqual(len(setup_env(self.env, self.example)), 2)
        self.assertIn("POSTGRES_PASSWORD=", self.env.read_text(encoding="utf-8"))

    def test_existing_custom_configuration_is_unchanged(self):
        original = (
            "# User-managed settings must remain exactly as written.\n"
            "MAKERVAULT_PORT=9472\n"
            "MEDIA_STORAGE=/mnt/other path/media\n"
            "OIDC_ENABLED=true\n"
            "CUSTOM_SETTING=custom-value # intentional comment\n"
            "DJANGO_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_VALUE\n"
            "POSTGRES_PASSWORD=CHANGE_ME_DATABASE_PASSWORD\n"
            "DJANGO_ALLOWED_HOSTS=example.com,localhost\n"
        )
        self.env.write_text(original, encoding="utf-8")
        setup_env(self.env, self.example)
        updated = self.env.read_text(encoding="utf-8")
        original_lines = [line for line in original.splitlines() if not line.startswith(("DJANGO_SECRET_KEY=", "POSTGRES_PASSWORD="))]
        updated_lines = [line for line in updated.splitlines() if not line.startswith(("DJANGO_SECRET_KEY=", "POSTGRES_PASSWORD="))]
        self.assertEqual(updated_lines, original_lines)

    def test_configured_secrets_are_not_rotated(self):
        original = (
            "DJANGO_SECRET_KEY=keep-this-existing-secret\n"
            "POSTGRES_PASSWORD=keep-this-existing-password\n"
            "CUSTOM_SETTING=keep-me\n"
        )
        self.env.write_text(original, encoding="utf-8")
        self.assertEqual(setup_env(self.env, self.example), [])
        self.assertEqual(self.env.read_text(encoding="utf-8"), original)
