"""Unmodified official-profile probes must not reuse the legacy K2 test shim."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from scripts.build_orca_reference_fixture import FIXTURES, generate


class OfficialReferenceFixtureTests(unittest.TestCase):
    def test_unmodified_mode_preserves_exact_official_k2_setting(self):
        upstream = FIXTURES["k2"]

        def opener(request, timeout=30):
            url = unquote(request.full_url)
            kind = next(k for k, folder in (
                ("printer", "machine"), ("filament", "filament"), ("process", "process")
            ) if "/" + folder + "/" in url)
            data = {
                "name": upstream[kind],
                "type": "machine" if kind == "printer" else kind,
            }
            if kind == "printer":
                data.update({
                    "retraction_distances_when_cut": "30",
                    "long_retractions_when_cut": "1",
                    "nozzle_diameter": ["0.4"],
                })
            return io.BytesIO(json.dumps(data).encode())

        with tempfile.TemporaryDirectory() as directory:
            unmodified = generate(Path(directory) / "unmodified", "k2",
                                  opener=opener, preserve_official_values=True)
            legacy = generate(Path(directory) / "legacy", "k2", opener=opener)
            native = json.loads((unmodified / "printer.json").read_text())
            adjusted = json.loads((legacy / "printer.json").read_text())
        self.assertEqual(native["retraction_distances_when_cut"], "30")
        self.assertEqual(native["long_retractions_when_cut"], "1")
        self.assertEqual(adjusted["retraction_distances_when_cut"], "18")
        self.assertEqual(adjusted["long_retractions_when_cut"], "1")


if __name__ == "__main__":
    unittest.main()
