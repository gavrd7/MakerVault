"""No-Docker/no-network tests for the real Orca acceptance command."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.probe_slicer_staging import _pinned_image, probe

IMAGE = "sha256:" + "a" * 64


class AcceptanceProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / ".slicer-staging.env"
        self.config.write_text("\n".join([
            "MAKERVAULT_SLICER_WORKER_IMAGE=" + IMAGE,
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST=" + IMAGE,
            "SLICER_ENGINES_JSON='" + json.dumps({"orcaslicer": {
                "binary": "/opt/engines/orcaslicer.AppImage",
                "version": "2.5.0", "binary_sha256": "b" * 64,
            }}) + "'",
        ]))
        self.config.chmod(0o600)
        self.profiles = []
        for kind in ("printer", "filament", "process"):
            item = self.root / (kind + ".json")
            item.write_text(json.dumps({"name": kind}))
            self.profiles.append(item)

    def test_immutable_worker_and_networkless_container(self):
        calls = []
        def runner(cmd, check):
            calls.append(cmd)
            self.assertFalse(check)
            self.assertEqual(cmd[cmd.index("--network") + 1], "none")
            self.assertIn("--read-only", cmd)
            self.assertEqual(cmd[cmd.index("--cap-drop") + 1], "ALL")
            self.assertIn(IMAGE, cmd)
            self.assertNotIn("/var/run/docker.sock", " ".join(cmd))
            return type("Result", (), {"returncode": 0})()
        self.assertEqual(probe(*self.profiles, config=self.config, runner=runner), 0)
        self.assertEqual(len(calls), 1)

    def test_two_object_3mf_only_passes_explicit_fixture_path_to_isolated_worker(self):
        fixture = self.root / "two-object.3mf"
        fixture.write_bytes(b"test-only-placeholder-worker-validates-3mf")
        def runner(command, check):
            self.assertEqual(check, False)
            self.assertIn("--network", command)
            self.assertEqual(command[command.index("--network") + 1], "none")
            self.assertEqual(command[command.index("--model") + 1], "/fixtures/fixture.3mf")
            self.assertEqual(command[command.index("--expected-objects") + 1], "2")
            self.assertIn("--read-only", command)
            return type("Result", (), {"returncode": 0})()
        self.assertEqual(probe(*self.profiles, model=fixture, config=self.config, runner=runner), 0)

    def test_reversed_object_effect_probe_is_passed_only_to_isolated_runner(self):
        fixture = self.root / "reversed.3mf"
        fixture.write_bytes(b"test-only-worker-validated-3mf")
        def runner(command, check):
            self.assertEqual(check, False)
            self.assertIn("--verify-object-effects", command)
            self.assertIn("--reverse-object-effects", command)
            self.assertEqual(command[command.index("--expected-objects") + 1], "2")
            self.assertEqual(command[command.index("--network") + 1], "none")
            return type("Result", (), {"returncode": 0})()
        self.assertEqual(probe(*self.profiles, model=fixture,
                               verify_object_effects=True, reverse_object_effects=True,
                               config=self.config, runner=runner), 0)

    def test_reject_unsafe_two_object_fixture_without_starting_container(self):
        fixture = self.root / "invalid.txt"
        fixture.write_bytes(b"not a 3mf")
        with self.assertRaisesRegex(ValueError, "3MF"):
            probe(*self.profiles, model=fixture, config=self.config,
                  runner=lambda *a, **k: self.fail("must not start"))

    def test_unresolved_profile_fails_without_launching(self):
        self.profiles[0].write_text('{"inherits":"base"}')
        with self.assertRaisesRegex(ValueError, "fully resolved"):
            probe(*self.profiles, config=self.config, runner=lambda *a, **k: self.fail("launched"))

    def test_world_readable_and_changed_worker_identity_rejected(self):
        self.config.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "Private"):
            _pinned_image(self.config)
        self.config.chmod(0o600)
        self.config.write_text(self.config.read_text().replace(IMAGE, "sha256:" + "c" * 64, 1))
        with self.assertRaisesRegex(ValueError, "not pinned"):
            _pinned_image(self.config)

    def test_engine_failure_is_reported(self):
        def runner(*args, **kwargs):
            return type("Result", (), {"returncode": 7})()
        self.assertEqual(probe(*self.profiles, config=self.config, runner=runner), 7)


if __name__ == "__main__":
    unittest.main()
