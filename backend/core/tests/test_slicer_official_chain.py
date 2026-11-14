import json
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_official_chain import official_profile_chain
from core.slicer_official_profiles import OfficialProfileError


class OfficialNativeProfileChainTests(SimpleTestCase):
    def setUp(self):
        self.entries = [
            ("K1 0.4 nozzle", "machine/k1.json"),
            ("fdm_creality_common", "machine/common.json"),
            ("fdm_base", "machine/base.json"),
        ]
        self.files = {
            "K1 0.4 nozzle": {"type": "machine", "name": "K1 0.4 nozzle",
                              "inherits": "fdm_creality_common", "nozzle_diameter": "0.4"},
            "fdm_creality_common": {"type": "machine", "name": "fdm_creality_common",
                                     "inherits": "fdm_base", "gcode_flavor": "klipper"},
            "fdm_base": {"type": "machine", "name": "fdm_base",
                         "printable_area": ["0x0", "220x0", "220x220", "0x220"]},
        }

    def fetch(self, kind, name, subpath, vendor):
        return json.dumps(self.files[name]).encode("utf-8")

    @patch("core.slicer_official_chain.fetch_official_profile")
    @patch("core.slicer_official_chain.orca_entries")
    def test_imports_entire_native_chain_parent_first(self, index, fetch):
        index.return_value = self.entries
        fetch.side_effect = self.fetch
        chain = official_profile_chain("orcaslicer", "printer", "K1 0.4 nozzle", "machine/k1.json")
        self.assertEqual([row[0] for row in chain], [
            "fdm_base", "fdm_creality_common", "K1 0.4 nozzle",
        ])
        self.assertEqual(len(chain), 3)
        self.assertEqual(fetch.call_count, 3)

    @patch("core.slicer_official_chain.fetch_official_profile")
    @patch("core.slicer_official_chain.orca_entries")
    def test_non_creality_vendor_uses_its_own_pinned_parent_chain(self, index, fetch):
        index.return_value = self.entries
        fetch.side_effect = self.fetch
        chain = official_profile_chain(
            "orcaslicer", "printer", "K1 0.4 nozzle", "machine/k1.json", "Prusa"
        )
        self.assertEqual([row[0] for row in chain], [
            "fdm_base", "fdm_creality_common", "K1 0.4 nozzle",
        ])
        self.assertEqual(index.call_args.args, ("Prusa", "printer"))
        self.assertTrue(all(call.args[3] == "Prusa" for call in fetch.call_args_list))

    @patch("core.slicer_official_chain.fetch_creality_profile")
    @patch("core.slicer_official_chain.creality_entries")
    def test_creality_uses_own_pinned_parents(self, index, fetch):
        index.return_value = self.entries
        fetch.side_effect = self.fetch
        chain = official_profile_chain("crealityprint", "printer", "K1 0.4 nozzle", "machine/k1.json")
        self.assertEqual(chain[0][0], "fdm_base")

    @patch("core.slicer_official_chain.fetch_official_profile")
    @patch("core.slicer_official_chain.orca_entries")
    def test_missing_or_circular_parent_is_rejected_not_partially_imported(self, index, fetch):
        index.return_value = self.entries
        fetch.side_effect = self.fetch
        self.files["fdm_creality_common"]["inherits"] = "unknown-parent"
        with self.assertRaisesRegex(OfficialProfileError, "unavailable"):
            official_profile_chain("orcaslicer", "printer", "K1 0.4 nozzle", "machine/k1.json")
        self.files["fdm_creality_common"]["inherits"] = "K1 0.4 nozzle"
        with self.assertRaisesRegex(OfficialProfileError, "circular"):
            official_profile_chain("orcaslicer", "printer", "K1 0.4 nozzle", "machine/k1.json")

    @patch("core.slicer_official_chain.fetch_creality_profile")
    @patch("core.slicer_official_chain.creality_entries")
    def test_crealityprint_cross_manufacturer_parent_chain(self, index, fetch):
        index.return_value = self.entries
        fetch.side_effect = self.fetch
        chain = official_profile_chain(
            "crealityprint", "printer", "K1 0.4 nozzle", "machine/k1.json", "Voron"
        )
        self.assertEqual(chain[0][0], "fdm_base")
        self.assertEqual(index.call_args.args, ("printer", "Voron"))
        self.assertTrue(all(call.args[3] == "Voron" for call in fetch.call_args_list))

    @patch("core.slicer_official_chain.orca_entries")
    def test_client_cannot_select_a_profile_url_outside_pinned_manifest(self, index):
        index.return_value = self.entries
        with self.assertRaisesRegex(OfficialProfileError, "pinned"):
            official_profile_chain("orcaslicer", "printer", "K1 0.4 nozzle", "https://attacker.invalid/payload.json")
