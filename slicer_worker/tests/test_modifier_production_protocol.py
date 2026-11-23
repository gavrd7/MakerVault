"""The authenticated worker's modifier admission is never an unbounded bypass."""
import base64
import unittest
import uuid
from unittest.mock import patch

from slicer_worker.runner import WorkerError
from slicer_worker.service import _decode_payload
from slicer_worker.tests.test_modifier_3mf_validation import fixture


def payload(engine="orcaslicer", version="2.5.0"):
    encoded = lambda data: base64.b64encode(data).decode("ascii")
    return {
        "job_id": str(uuid.uuid4()),
        "engine": engine, "engine_version": version,
        "model_format": "3mf", "model": encoded(fixture()),
        "printer_profile": encoded(b'{"name":"Printer"}'),
        "filament_profile": encoded(b'{"name":"Filament"}'),
        "process_profile": encoded(b'{"name":"Process"}'),
        "native_modifier_project": True,
    }


class ProductionModifierProtocolTests(unittest.TestCase):
    def test_orca_and_bambu_only_approved_versions_admit_exact_fixture(self):
        for engine, version in (("orcaslicer", "2.5.0"),
                                ("bambustudio", "02.09.01.70")):
            with self.subTest(engine=engine):
                decoded = _decode_payload(payload(engine, version))
                self.assertTrue(decoded["native_modifier_project"])
                self.assertEqual(decoded["model_format"], "3mf")
                for wrong in (version + ".1", "0.0.0", "", None):
                    with self.subTest(wrong=wrong), self.assertRaises(WorkerError):
                        _decode_payload({**payload(engine, version),
                                         "engine_version": wrong})

    def test_creality_requires_explicit_native_project_validation(self):
        item = payload("crealityprint", "7.3.1")
        with patch("slicer_worker.creality_modifier_validation.validate_creality_modifier_project",
                   return_value=True) as validator:
            decoded = _decode_payload(item)
            self.assertTrue(decoded["native_modifier_project"])
            validator.assert_called_once_with(decoded["model"])
        with self.assertRaises(WorkerError):
            _decode_payload(item)

    def test_alternate_modes_cannot_mix_with_modifier_contract(self):
        original = payload()
        for change in (
            {"native_modifier_project": False},
            {"native_modifier_project": 1},
            {"model_format": "stl"},
            {"filament_profiles": [original["filament_profile"]] * 2},
            {"creality_native_project": True},
            {"creality_model_stls": [original["model"]] * 2},
            {"creality_tool_ids": [1, 2]},
            {"engine": "prusaslicer"},
        ):
            with self.subTest(change=change), self.assertRaises(WorkerError):
                _decode_payload({**original, **change})

    def test_default_worker_route_still_rejects_modifier_parts(self):
        original = payload()
        original.pop("native_modifier_project")
        with self.assertRaises(WorkerError):
            _decode_payload(original)

    def test_malicious_region_metadata_is_rejected_even_when_flagged(self):
        from slicer_worker.tests.test_modifier_3mf_validation import fixture
        original = payload()
        original["model"] = base64.b64encode(fixture(malicious=True)).decode()
        with self.assertRaises(WorkerError):
            _decode_payload(original)


if __name__ == "__main__":
    unittest.main()
