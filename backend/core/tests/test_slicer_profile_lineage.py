"""Native Orca dependency inspection never resolves profiles from other owners."""
import hashlib
import json
import uuid
from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase

from core.slicer_profile_lineage import inspect_orca_lineage


class NativeFile:
    def __init__(self, raw):
        self.raw = raw

    def __bool__(self):
        return True

    def open(self, mode="rb"):
        return BytesIO(self.raw)


def profile(name, *, parent=None, owner=1, engine_version="2.3", kind="filament", tamper=False):
    data = {"name": name, "filament_type": ["PLA"]}
    if parent is not None:
        data["inherits"] = parent
    raw = json.dumps(data).encode()
    return SimpleNamespace(
        pk=uuid.uuid4(), owner_id=owner, engine="orcaslicer",
        engine_version=engine_version, kind=kind, name=name, status="candidate",
        content_sha256=("0" * 64 if tamper else hashlib.sha256(raw).hexdigest()),
        file_asset=SimpleNamespace(file=NativeFile(raw)),
    )


class OrcaLineageTests(SimpleTestCase):
    def test_resolves_exact_chain_with_all_checksums_no_execution_approval(self):
        root = profile("base")
        mid = profile("parent", parent="base")
        leaf = profile("PLA child", parent="parent")
        result = inspect_orca_lineage(leaf, [leaf, root, mid])
        self.assertEqual(result["status"], "complete")
        self.assertEqual([p["name"] for p in result["chain"]], ["PLA child", "parent", "base"])
        self.assertFalse(result["approved_for_execution"])

    def test_missing_parent_and_foreign_owner_are_not_filled_by_guess(self):
        leaf = profile("child", parent="Generic PLA")
        foreign = profile("Generic PLA", owner=2)
        wrong_version = profile("Generic PLA", engine_version="2.2")
        wrong_kind = profile("Generic PLA", kind="printer")
        result = inspect_orca_lineage(leaf, [leaf, foreign, wrong_version, wrong_kind])
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["missing"], "Generic PLA")

    def test_cycle_and_modified_source_fail_closed(self):
        a = profile("A", parent="B")
        b = profile("B", parent="A")
        self.assertEqual(inspect_orca_lineage(a, [a, b])["status"], "cycle")
        bad = profile("Tampered", tamper=True)
        result = inspect_orca_lineage(bad, [bad])
        self.assertEqual(result["status"], "invalid")
        self.assertIn("changed", result["error"])

    def test_parent_of_parent_still_requires_same_kind(self):
        a = profile("A", parent="B")
        b = profile("B", parent="C")
        c = profile("C", kind="printer")
        result = inspect_orca_lineage(a, [a, b, c])
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["missing"], "C")
