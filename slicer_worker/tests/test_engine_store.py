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
            "SLICER_WORKER_ENABLED": "1",
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
