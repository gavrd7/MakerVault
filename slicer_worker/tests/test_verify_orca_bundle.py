import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from slicer_worker.verify_orca_bundle import audit_bundle, BundleAuditError


class OrcaNativeBundleAuditTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "resources" / "profiles"
        self.root.mkdir(parents=True)
        self.manifest = Path(self.tmp.name) / "fixture.json"
        specimen = {
            "schema": "makervault.orca-fixture-candidates.v1",
            "upstream_ref": "test-pinned",
            "printers": [{
                "model": "Example",
                "machine_profile": "resources/profiles/Creality/machine/My Printer.json",
                "process_profile": "resources/profiles/Creality/process/My Process.json",
                "filament_profile": "resources/profiles/Creality/filament/My Filament.json",
            }],
        }
        self.manifest.write_text(json.dumps(specimen))
        for kind, name, parent in (
            ("machine", "My Printer", "Common machine"),
            ("process", "My Process", "Common process"),
            ("filament", "My Filament", "Shared PLA"),
        ):
            self.save("Creality/" + kind + "/" + name + ".json", name, parent)
            if kind != "filament":
                self.save("Creality/" + kind + "/Common " + kind + ".json", "Common " + kind)
        self.save("OrcaFilamentLibrary/filament/Shared PLA.json", "Shared PLA")

    def save(self, path, name, parent=None):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {"name": name, "instantiation": "false" if name.startswith("Common") else "true"}
        if parent:
            data["inherits"] = parent
        target.write_text(json.dumps(data))
        return target

    def test_exact_native_chain_is_hashed_but_never_approved(self):
        report = audit_bundle(self.root, self.manifest)
        self.assertFalse(report["approved_for_execution"])
        for kind in ("machine", "process", "filament"):
            value = report["results"][0]["profiles"][kind]
            self.assertEqual(value["status"], "complete")
            self.assertEqual(len(value["chain"]), 2)
            self.assertEqual(len(value["chain"][0]["sha256"]), 64)
            self.assertFalse(value["approved_for_execution"])

    def test_missing_parent_is_reported_without_guessing_defaults(self):
        (self.root / "Creality/machine/Common machine.json").unlink()
        result = audit_bundle(self.root, self.manifest)
        self.assertEqual(result["results"][0]["profiles"]["machine"]["status"], "missing")

    def test_symlink_or_malformed_json_is_not_accepted(self):
        file = self.root / "Creality/machine/My Printer.json"
        file.unlink()
        file.symlink_to(self.root / "Creality/process/My Process.json")
        with self.assertRaises(BundleAuditError):
            audit_bundle(self.root, self.manifest)
        file.unlink()
        file.write_text("{bad json")
        with self.assertRaises(BundleAuditError):
            audit_bundle(self.root, self.manifest)

    def test_cycles_are_rejected(self):
        self.save("Creality/machine/Common machine.json", "Common machine", "My Printer")
        report = audit_bundle(self.root, self.manifest)
        self.assertEqual(report["results"][0]["profiles"]["machine"]["status"], "cycle")
