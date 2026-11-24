"""Offline safety tests for review-only Prusa candidate manifests."""
import tempfile
import unittest
from pathlib import Path

from scripts.prusa_candidate_manifest import manifest


class PrusaCandidateManifestTests(unittest.TestCase):
    def make_candidate(self, root):
        binary = root / "bin" / "prusa-slicer"
        binary.parent.mkdir()
        binary.write_bytes(b"\x7fELF" + b"review-fixture")
        binary.chmod(0o755)
        profiles = root / "resources" / "profiles"
        profiles.mkdir(parents=True)
        (profiles / "PrusaResearch.ini").write_text("fixture=1\n")
        (root / "LICENSE").write_text("licence fixture\n")
        return binary

    def test_pinned_identity_checksums_and_not_install_approved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_candidate(root)
            result = manifest(root)
            self.assertEqual(result["engine"], "prusaslicer")
            self.assertEqual(result["source_commit"],
                             "450d70dd81c9b8990bc6bc8e690e31f82ddceb11")
            self.assertFalse(result["install_approved"])
            self.assertEqual(result["file_count"], 3)
            self.assertEqual({row["path"] for row in result["files"]},
                             {"bin/prusa-slicer", "resources/profiles/PrusaResearch.ini", "LICENSE"})
            self.assertTrue(all(len(row["sha256"]) == 64 for row in result["files"]))

    def test_missing_licence_and_tampered_binary_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = self.make_candidate(root)
            (root / "LICENSE").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                manifest(root)
            (root / "LICENSE").write_text("licence fixture\n")
            binary.write_bytes(b"not ELF")
            with self.assertRaisesRegex(ValueError, "ELF"):
                manifest(root)

    def test_symlink_and_special_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_candidate(root)
            (root / "linked").symlink_to("LICENSE")
            with self.assertRaisesRegex(ValueError, "symlink"):
                manifest(root)


if __name__ == "__main__":
    unittest.main()
