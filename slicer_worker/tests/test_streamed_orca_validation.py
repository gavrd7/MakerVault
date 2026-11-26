import io
import zipfile
import unittest
from unittest.mock import patch

from slicer_worker.runner import WorkerError
from slicer_worker.streamed_orca_validation import validate_streamed_orca_3mf

NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def plate_data(*, duplicate=False, bad_index=False, doctype=False):
    vertices = '<vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/>'
    face = '<triangle v1="0" v2="1" v3="%s"/>' % ("3" if bad_index else "2")
    content = ('<?xml version="1.0" encoding="utf-8"?>'
               + ('<!DOCTYPE model [<!ENTITY x "bad">]>' if doctype else '')
               + '<model xmlns="%s" unit="millimeter" xml:lang="en-US">' % NS
               + '<resources><object id="1" type="model"><mesh><vertices>'
               + vertices + '</vertices><triangles>' + face
               + '</triangles></mesh></object></resources>'
               + '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></build></model>')
    if duplicate:
        content = content.replace("</resources>", '<object id="2" type="model"/></resources>')
    out = io.BytesIO()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model",content)
        archive.writestr("[Content_Types].xml",
                         '<Types><Default ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        archive.writestr("_rels/.rels",
                         '<Relationships><Relationship Target="/3D/3dmodel.model"/></Relationships>')
    return out.getvalue()


class StreamedOrcaWorkerValidationTests(unittest.TestCase):
    @patch("slicer_worker.streamed_orca_validation._memory_headroom",return_value=8*1024**3)
    def test_valid_plain_mesh(self, _memory):
        self.assertEqual(validate_streamed_orca_3mf(plate_data()),
                         {"vertices":3,"triangles":1})

    @patch("slicer_worker.streamed_orca_validation._memory_headroom",return_value=8*1024**3)
    def test_triangle_reference_cannot_escape_mesh(self, _memory):
        with self.assertRaises(WorkerError):
            validate_streamed_orca_3mf(plate_data(bad_index=True))

    @patch("slicer_worker.streamed_orca_validation._memory_headroom",return_value=8*1024**3)
    def test_no_extra_resource(self, _memory):
        with self.assertRaises(WorkerError):
            validate_streamed_orca_3mf(plate_data(duplicate=True))

    @patch("slicer_worker.streamed_orca_validation._memory_headroom",return_value=8*1024**3)
    def test_no_document_type_entities(self, _memory):
        with self.assertRaises(WorkerError):
            validate_streamed_orca_3mf(plate_data(doctype=True))


    @patch("slicer_worker.streamed_orca_validation._memory_headroom",return_value=8*1024**3)
    def test_worker_http_contract_keeps_streaming_strictly_orca_only(self, _memory):
        import base64
        import hashlib
        import uuid
        from slicer_worker.service import _decode_payload
        project = plate_data()
        profile = base64.b64encode(b"{}").decode("ascii")
        request = {
            "job_id": str(uuid.uuid4()),
            "engine": "orcaslicer", "engine_version": "2.5.0",
            "model_format": "3mf",
            "model": base64.b64encode(project).decode("ascii"),
            "printer_profile": profile, "process_profile": profile,
            "filament_profile": profile,
            "orca_streamed_plate": True,
            "orca_streamed_sha256": hashlib.sha256(project).hexdigest(),
        }
        self.assertEqual(_decode_payload(request)["model"], project)
        for update in (
            {"orca_streamed_sha256": "0"*64},
            {"engine": "bambustudio"},
            {"engine_version": "2.4.2"},
            {"filament_profiles": [profile,profile]},
        ):
            with self.subTest(update=update), self.assertRaises(WorkerError):
                _decode_payload({**request,**update})

    @patch("slicer_worker.streamed_orca_validation._memory_headroom",return_value=256*1024**2)
    def test_low_memory_rejects_before_xml_expansion(self, _memory):
        with self.assertRaises(WorkerError):
            validate_streamed_orca_3mf(plate_data())
