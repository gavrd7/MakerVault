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

    @patch("slicer_worker.streamed_orca_validation._memory_headroom",return_value=256*1024**2)
    def test_low_memory_rejects_before_xml_expansion(self, _memory):
        with self.assertRaises(WorkerError):
            validate_streamed_orca_3mf(plate_data())
