import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("backup", Path(__file__).with_name("backup.py"))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def container(name, *, running=True):
    return {"Id": name, "Name": "/" + name, "Image": "synthetic-image",
            "State": {"Running": running},
            "Config": {"Env": ["DATABASE_HOST=postgres"], "Labels": {"com.docker.compose.project": "test"}},
            "Mounts": [{"Destination": "/app/media", "Source": "/synthetic/media"},
                       {"Destination": "/app/keys", "Source": "/synthetic/keys"}],
            "NetworkSettings": {"Networks": {"test": {"Aliases": [name]}}}}


class BackupSafetyTests(unittest.TestCase):
    def test_external_database_is_rejected(self):
        app = container("app")
        app["Config"]["Env"] = ["DATABASE_HOST=external.example"]
        with self.assertRaises(backup.BackupError):
            backup.validate(app, container("postgres"))

    def test_other_compose_project_is_rejected(self):
        db = container("postgres")
        db["Config"]["Labels"]["com.docker.compose.project"] = "other"
        with self.assertRaises(backup.BackupError):
            backup.validate(container("app"), db)

    def test_key_outside_archive_is_rejected(self):
        app = container("app")
        app["Config"]["Env"].append("MAKERVAULT_STORAGE_KEY_FILE=/other/key")
        with self.assertRaises(backup.BackupError):
            backup.validate(app, container("postgres"))

    def test_dump_failure_restarts_app_and_never_publishes_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("SYNTHETIC=true")
            (root / "compose.yaml").write_text("services: {}")
            args = SimpleNamespace(sudo=False, source_dir=root, destination=root / "backups",
                                   app_container="app", database_container="postgres")
            stopped = False
            calls = []
            def fake_run(command, **kwargs):
                nonlocal stopped
                calls.append(command)
                if "inspect" in command:
                    name = command[-1]
                    return json.dumps([container(name, running=not (name == "app" and stopped))]).encode()
                if "stop" in command:
                    stopped = True
                if "pg_dump" in command:
                    raise backup.BackupError("synthetic dump failure")
                return b""
            with patch.object(backup, "run", side_effect=fake_run), patch.object(
                backup.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"synthetic-sha\n")
            ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(backup.BackupError):
                    backup.backup(args)
            self.assertIn(["docker", "start", "app"], calls)
            self.assertFalse(list((root / "backups").glob("*.tar.gz")))
            self.assertTrue(list((root / "backups").glob(".incomplete-*")))


if __name__ == "__main__":
    unittest.main()
