import tempfile
from pathlib import Path
from unittest import TestCase

from scripts.setup_env import setup_env


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
