import json
from pathlib import Path
from unittest import TestCase


class OrcaCrealityFixtureManifestTests(TestCase):
    def test_upstream_paths_are_only_candidate_references(self):
        source = Path(__file__).parents[1] / "fixtures" / "creality-orca-v2.4.2.json"
        result = json.loads(source.read_text())
        self.assertEqual(result["upstream_ref"], "v2.4.2")
        self.assertTrue(result["status"].startswith("candidate"))
        self.assertEqual([item["model"] for item in result["printers"]], ["Creality K1", "Creality K2"])
        for printer in result["printers"]:
            self.assertEqual(len(printer["declared_volume_mm"]), 3)
            for field in ("machine_profile", "filament_profile", "process_profile"):
                self.assertTrue(printer[field].startswith("resources/profiles/Creality/"))
                self.assertTrue(printer[field].endswith(".json"))
            for field in ("unresolved_machine_parent", "unresolved_process_parent", "unresolved_filament_parent"):
                self.assertTrue(printer[field])
            for kind in ("machine", "process", "filament"):
                chain = printer["parent_chains"][kind]
                self.assertGreaterEqual(len(chain), 3)
                self.assertTrue(all(isinstance(name, str) and name for name in chain))
        k1 = result["printers"][0]
        self.assertTrue(k1["filament_profile"].endswith("/Creality Generic PLA.json"))
        self.assertNotIn("@K1-all", k1["filament_profile"])
