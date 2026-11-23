"""Persistent one-worker/many-engine registry acceptance and failure modes."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slicer_worker import engine_registry as registry


class PersistentEngineRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)
        self.approved = self.store / "versions" / "orcaslicer" / "2.5.0"
        self.approved.mkdir(parents=True)
        self.binary = self.approved / "orcaslicer.AppImage"
        self.binary.write_bytes(b"approved test fixture (not an executable slicer)")
        self.binary.chmod(0o755)
        self.digest = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.env = patch.dict(os.environ, {
            "SLICER_WORKER_TOKEN": "x" * 64,
            "SLICER_ENGINES_JSON": "{}",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store_patch = patch.object(registry, "ENGINE_STORE", self.store)
        self.manifest_patch = patch.object(registry, "ACTIVE_MANIFEST", self.store / "active.json")
        self.store_patch.start()
        self.manifest_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.addCleanup(self.manifest_patch.stop)
        registry._hash_binary.cache_clear()
        self.addCleanup(registry._hash_binary.cache_clear)

    def save(self, *, binary=None, version="2.5.0", digest=None):
        (self.store / "active.json").write_text(json.dumps({
            "schema_version": 1,
            "engines": {"orcaslicer": {
                "binary": str(binary or self.binary),
                "version": version,
                "binary_sha256": digest or self.digest,
            }},
        }))

    def test_no_worker_token_fail_closed(self):
        self.save()
        with patch.dict(os.environ, {"SLICER_WORKER_TOKEN": ""}):
            self.assertEqual(registry.configured_engines(), {})

    def test_approved_versioned_engine_appears_in_one_worker(self):
        self.save()
        engines = registry.configured_engines()
        self.assertEqual(list(engines), ["orcaslicer"])
        self.assertEqual(engines["orcaslicer"]["version"], "2.5.0")
        self.assertEqual(engines["orcaslicer"]["binary_sha256"], self.digest)

    def test_wrong_binary_hash_disables_engine(self):
        self.save(digest="0" * 64)
        self.assertEqual(registry.configured_engines(), {})

    def test_manifest_is_not_ignored_if_invalid(self):
        (self.store / "active.json").write_text("{broken json")
        self.assertEqual(registry.configured_engines(), {})

    def test_outside_store_binary_rejected(self):
        external = self.store.parent / ("wrong-engine-" + self.store.name)
        external.write_bytes(self.binary.read_bytes())
        external.chmod(0o755)
        self.addCleanup(lambda: external.unlink(missing_ok=True))
        self.save(binary=external)
        self.assertEqual(registry.configured_engines(), {})

    def test_path_traversal_version_rejected(self):
        self.save(version="../2.5.0")
        self.assertEqual(registry.configured_engines(), {})

    def test_symlinked_binary_rejected(self):
        symlink = self.approved / "linked.AppImage"
        symlink.symlink_to(self.binary)
        self.save(binary=symlink)
        self.assertEqual(registry.configured_engines(), {})

    def test_extracted_creality_apprun_symlink_stays_inside_version(self):
        import hashlib
        cp = self.store / "versions" / "crealityprint" / "7.3.1"
        (cp / "squashfs-root" / "usr" / "bin").mkdir(parents=True)
        executable = cp / "squashfs-root" / "usr" / "bin" / "CrealityPrint"
        executable.write_bytes(b"mock headless executable")
        executable.chmod(0o755)
        apprun = cp / "squashfs-root" / "AppRun"
        apprun.symlink_to("usr/bin/CrealityPrint")
        sha = hashlib.sha256(executable.read_bytes()).hexdigest()
        (self.store / "active.json").write_text(json.dumps({
            "schema_version": 1, "engines": {
                "orcaslicer": {"binary": str(self.binary),
                              "version": "2.5.0", "binary_sha256": self.digest},
                "crealityprint": {"binary": str(apprun),
                                  "version": "7.3.1", "binary_sha256": sha},
            },
        }))
        self.assertEqual(set(registry.configured_engines()), {"orcaslicer", "crealityprint"})
        # A hostile link cannot escape the installed runtime's version root.
        apprun.unlink()
        apprun.symlink_to("/etc/passwd")
        self.assertNotIn("crealityprint", registry.configured_engines())


    def test_unreadable_bambu_runtime_does_not_break_other_engines(self):
        """A 0700 AppImage directory must not crash /health discovery."""
        bambu = self.store / "versions" / "bambustudio" / registry.BAMBU_VERSION
        runtime = bambu / "squashfs-root" / "AppRun"
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b"test fixture")
        runtime.chmod(0o755)
        (self.store / "active.json").write_text(json.dumps({
            "schema_version": 1, "engines": {
                "orcaslicer": {"binary": str(self.binary),
                              "version": "2.5.0", "binary_sha256": self.digest},
                "bambustudio": {"binary": str(runtime),
                                 "version": registry.BAMBU_VERSION,
                                 "binary_sha256": registry.BAMBU_RUNTIME_SHA256},
            },
        }))
        original = Path.is_file

        def denied(path):
            if path == runtime:
                raise PermissionError(13, "Permission denied", str(path))
            return original(path)

        with patch.object(Path, "is_file", denied):
            engines = registry.configured_engines()
        self.assertEqual(set(engines), {"orcaslicer"})

    def test_manifest_symlink_rejected(self):
        self.save()
        other = self.store / "other.json"
        (self.store / "active.json").rename(other)
        (self.store / "active.json").symlink_to(other)
        self.assertEqual(registry.configured_engines(), {})

    def test_empty_engine_manifest_fail_closed(self):
        (self.store / "active.json").write_text(json.dumps({
            "schema_version": 1, "engines": {},
        }))
        self.assertEqual(registry.configured_engines(), {})


if __name__ == "__main__":
    unittest.main()
