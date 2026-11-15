"""Offline checks for Orca source correction: exact upstream version, no profile changes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.orca_compatibility_patch import (
    AFTER, BEFORE, ORCA_COMMIT, TARGET, apply_to_checkout, patched_source
)


class OrcaSourceCompatibilityTests(unittest.TestCase):
    def test_only_native_long_retraction_validation_bound_changes(self):
        source = "prefix\n" + BEFORE + "\nsuffix\n"
        result = patched_source(source)
        self.assertEqual(result, "prefix\n" + AFTER + "\nsuffix\n")
        self.assertEqual(result.count("def->max = 30;"), 1)
        self.assertEqual(result.replace(AFTER, BEFORE), source)

    def test_reject_changed_or_already_patched_source(self):
        for data in (AFTER, "", BEFORE + BEFORE):
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                patched_source(data)

    def test_refuses_unpinned_checkout_and_modified_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            target = root / TARGET
            target.parent.mkdir(parents=True)
            target.write_text(BEFORE)
            with patch("scripts.orca_compatibility_patch.subprocess.run") as run:
                run.return_value.stdout = "another commit\n"
                with self.assertRaisesRegex(ValueError, "revision"):
                    apply_to_checkout(root)
                run.return_value.stdout = ORCA_COMMIT + "\n"
                run.side_effect = [
                    type("Result", (), {"stdout": ORCA_COMMIT + "\n"})(),
                    type("Result", (), {"stdout": " M source\n"})(),
                ]
                with self.assertRaisesRegex(ValueError, "clean"):
                    apply_to_checkout(root)
            self.assertEqual(target.read_text(), BEFORE)


if __name__ == "__main__":
    unittest.main()
