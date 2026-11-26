import io
import zipfile
from unittest import TestCase
from unittest.mock import patch
from slicer_worker.runner import WorkerError
from slicer_worker.three_mf_validation import validate_worker_3mf, MAX_TRIANGLES


class Core3MFWorkerTests(TestCase):
    def package(self, *, malformed=False):
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        content = (f'<model xmlns="{ns}" unit="millimeter">'
                   '<resources><object id="1" type="model"><mesh>'
                   '<vertices><vertex x="0" y="0" z="0"/>'
                   '<vertex x="1" y="0" z="0"/>'
                   '<vertex x="0" y="1" z="0"/></vertices>'
                   '<triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
                   '</mesh></object></resources>'
                   '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 10 10 0"/></build>'
                   '</model>').encode()
        if malformed:
            content = content.replace(b'objectid="1"', b'objectid="999"')
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("3D/3dmodel.model", content)
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
        return data.getvalue()


    def with_object_metadata(self, overrides):
        """Build two core objects and a single native plate mapping."""
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        def mesh(index):
            return (f'<object id="{index}" type="model"><mesh><vertices>'
                    '<vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>'
                    '<vertex x="0" y="1" z="0"/></vertices>'
                    '<triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
                    '</mesh></object>')
        model = (f'<model xmlns="{ns}" unit="millimeter"><resources>'
                 + mesh(1) + mesh(2) + '</resources><build>'
                 '<item objectid="1" transform="1 0 0 0 1 0 0 0 1 10 10 0"/>'
                 '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 40 40 0"/>'
                 '</build></model>')
        metadata = ''.join(f'<metadata key="{key}" value="{value}"/>' for key, value in overrides)
        manifest = ('<config><object id="2">' + metadata + '</object>'
                    '<plate><metadata key="plater_id" value="1"/>'
                    '<model_instance><metadata key="object_id" value="1"/>'
                    '<metadata key="instance_id" value="0"/>'
                    '<metadata key="identify_id" value="1"/></model_instance>'
                    '<model_instance><metadata key="object_id" value="2"/>'
                    '<metadata key="instance_id" value="0"/>'
                    '<metadata key="identify_id" value="2"/></model_instance>'
                    '</plate></config>')
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zipfile_out:
            zipfile_out.writestr("3D/3dmodel.model", model)
            zipfile_out.writestr("Metadata/model_settings.config", manifest)
            zipfile_out.writestr("[Content_Types].xml", "<Types/>")
            zipfile_out.writestr("_rels/.rels", "<Relationships/>")
        return out.getvalue()

    def test_twenty_distinct_plate_objects_are_admitted(self):
        # Each resource has different geometry and its own build transform.
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        meshes = []
        items = []
        members = []
        for index in range(1, 21):
            meshes.append(
                f'<object id="{index}" type="model"><mesh><vertices>'
                '<vertex x="0" y="0" z="0"/>'
                f'<vertex x="{index}" y="0" z="0"/>'
                f'<vertex x="0" y="{index}" z="0"/>'
                '<triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
                '</mesh></object>'
            )
            items.append(
                f'<item objectid="{index}" transform="1 0 0 0 1 0 0 0 1 '
                f'{index * 2} {index * 2} 0"/>'
            )
            members.append(
                '<model_instance>'
                f'<metadata key="object_id" value="{index}"/>'
                '<metadata key="instance_id" value="0"/>'
                f'<metadata key="identify_id" value="{index}"/>'
                '</model_instance>'
            )
        model = (
            f'<model xmlns="{ns}" unit="millimeter"><resources>'
            + "".join(meshes) + '</resources><build>'
            + "".join(items) + '</build></model>'
        )
        manifest = (
            '<config><plate><metadata key="plater_id" value="1"/>'
            + "".join(members) + '</plate></config>'
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("3D/3dmodel.model", model)
            archive.writestr("Metadata/model_settings.config", manifest)
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
        self.assertTrue(validate_worker_3mf(output.getvalue()))

    def test_multi_object_3mf_has_separate_model_and_plate_budgets(self):
        # Two one-triangle objects verify the budget split without constructing
        # a potentially gigabyte-sized test fixture.
        source = self.with_object_metadata({"wall_loops": "2"})
        from slicer_worker import three_mf_validation as validator
        with (patch.object(validator, "MAX_TRIANGLES", 1),
              patch.object(validator, "MAX_PLATE_TRIANGLES", 2)):
            self.assertTrue(validate_worker_3mf(source))
        with (patch.object(validator, "MAX_TRIANGLES", 1),
              patch.object(validator, "MAX_PLATE_TRIANGLES", 1)):
            with self.assertRaisesRegex(WorkerError, "3MF triangle count exceeds"):
                validate_worker_3mf(source)

    def test_individual_3mf_object_still_has_triangle_budget(self):
        source = self.package()
        from slicer_worker import three_mf_validation as validator
        with patch.object(validator, "MAX_TRIANGLES", 0):
            with self.assertRaisesRegex(WorkerError, "3MF object triangle count"):
                validate_worker_3mf(source)

    def with_variable_layer_range(self, xml):
        """Wrap one real core model in MakerVault's bounded native metadata."""
        original = self.package()
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        contents["Metadata/model_settings.config"] = (
            '<config><plate><metadata key="plater_id" value="1"/>'
            '<model_instance><metadata key="object_id" value="1"/>'
            '<metadata key="instance_id" value="0"/>'
            '<metadata key="identify_id" value="1"/></model_instance>'
            '</plate></config>'
        ).encode()
        contents["Metadata/layer_config_ranges.xml"] = xml.encode()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in contents.items():
                archive.writestr(name, body)
        return out.getvalue()

    def test_native_variable_height_ranges_accept_only_layer_height(self):
        valid = ('<objects><object id="1">'
                 '<range min_z="1" max_z="4"><option opt_key="layer_height">0.12</option></range>'
                 '<range min_z="5" max_z="8"><option opt_key="layer_height">0.16</option></range>'
                 '</object></objects>')
        self.assertTrue(validate_worker_3mf(self.with_variable_layer_range(valid)))
        for xml in (
            valid.replace('opt_key="layer_height"', 'opt_key="machine_start_gcode"'),
            valid.replace('id="1"', 'id="999"'),
            valid.replace('max_z="4"', 'max_z="3000"'),
            valid.replace('0.12', 'NaN'),
            valid.replace('min_z="5"', 'min_z="3"'),
            valid.replace('<objects>', '<script>'),
        ):
            with self.subTest(xml=xml), self.assertRaises(WorkerError):
                validate_worker_3mf(self.with_variable_layer_range(xml))
        with self.assertRaises(WorkerError):
            validate_worker_3mf(self.with_variable_layer_range(valid), native_tool_count=2)

    def test_native_support_facets_are_strictly_bounded(self):
        original = self.package()
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        def with_state(value):
            entries = dict(files)
            entries["3D/3dmodel.model"] = entries["3D/3dmodel.model"].replace(
                b'<triangle v1="0" v2="1" v3="2"/>',
                b'<triangle v1="0" v2="1" v3="2" paint_supports="' +
                value.encode() + b'"/>',
            )
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in entries.items():
                    archive.writestr(name, raw)
            return out.getvalue()
        for state in ("4", "8"):
            with self.subTest(state=state):
                self.assertTrue(validate_worker_3mf(with_state(state)))
        for unsafe in ("0", "C", "1234", "40", "4;M104 S300"):
            with self.subTest(state=unsafe), self.assertRaises(WorkerError):
                validate_worker_3mf(with_state(unsafe))
        with self.assertRaises(WorkerError):
            validate_worker_3mf(with_state("4"), native_tool_count=2)

    def test_seam_paint_facets_allow_only_exact_native_states(self):
        original = self.package()
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        self.assertIn(b'<triangle v1="0" v2="1" v3="2"/>',
                      members["3D/3dmodel.model"])
        def with_seam(value, name="paint_seam"):
            contents = dict(members)
            contents["3D/3dmodel.model"] = contents["3D/3dmodel.model"].replace(
                b'<triangle v1="0" v2="1" v3="2"/>',
                b'<triangle v1="0" v2="1" v3="2" ' + name.encode() +
                b'="' + value.encode() + b'"/>')
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for filename, payload in contents.items():
                    archive.writestr(filename, payload)
            return output.getvalue()
        for value in ("4", "8"):
            with self.subTest(value=value):
                self.assertTrue(validate_worker_3mf(with_seam(value)))
        for value in ("0", "4 8", "40", "evil", "4;M104"):
            with self.subTest(value=value), self.assertRaises(WorkerError):
                validate_worker_3mf(with_seam(value))
        with self.assertRaises(WorkerError):
            validate_worker_3mf(with_seam("4"), native_tool_count=2)
        self.assertTrue(validate_worker_3mf(with_seam("4", "paint_fuzzy_skin")))
        for state in ("8", "0", "40", "4;M104"):
            with self.subTest(state=state), self.assertRaises(WorkerError):
                validate_worker_3mf(with_seam(state, "paint_fuzzy_skin"))
        with self.assertRaises(WorkerError):
            validate_worker_3mf(with_seam("4", "paint_fuzzy_skin"), native_tool_count=2)

    def test_combined_native_paint_and_variable_layers_are_accepted(self):
        base = self.with_variable_layer_range(
            '<objects><object id="1"><range min_z="1" max_z="4">'
            '<option opt_key="layer_height">0.12</option>'
            '</range></object></objects>')
        with zipfile.ZipFile(io.BytesIO(base)) as package:
            parts = {entry: package.read(entry) for entry in package.namelist()}
        original = b'<triangle v1="0" v2="1" v3="2"/>'
        def repack(attributes):
            payloads = dict(parts)
            payloads["3D/3dmodel.model"] = payloads["3D/3dmodel.model"].replace(
                original, b'<triangle v1="0" v2="1" v3="2" ' + attributes + b'/>')
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
                for path, payload in payloads.items():
                    package.writestr(path, payload)
            return output.getvalue()

        combined = (b'paint_supports="4" paint_seam="8" '
                    b'paint_fuzzy_skin="4"')
        self.assertTrue(validate_worker_3mf(repack(combined)))
        self.assertTrue(validate_worker_3mf(repack(
            b'paint_supports="4" paint_fuzzy_skin="4"')))
        for invalid in (
            b'paint_supports="40" paint_seam="8" paint_fuzzy_skin="4"',
            b'paint_supports="4" paint_seam="0" paint_fuzzy_skin="4"',
            b'paint_supports="4" paint_seam="8" paint_fuzzy_skin="8"',
            b'paint_supports="4" paint_seam="8" machine_start_gcode="M104"',
        ):
            with self.subTest(invalid=invalid), self.assertRaises(WorkerError):
                validate_worker_3mf(repack(invalid))
        with self.assertRaises(WorkerError):
            validate_worker_3mf(repack(combined), native_tool_count=2)

    def test_safe_per_object_metadata_passes_worker_validation(self):
        self.assertTrue(validate_worker_3mf(self.with_object_metadata([
            ("wall_loops", "5"), ("sparse_infill_density", "37%"),
        ])))

    def test_unsafe_per_object_metadata_is_rejected(self):
        for overrides in (
            [("machine_start_gcode", "M104 S300")],
            [("wall_loops", "999")],
            [("wall_loops", "-2")],
            [("wall_loops", "3.5")],
            [("sparse_infill_density", "50")],
            [("sparse_infill_density", "NaN%")],
            [("wall_loops", "3"), ("wall_loops", "5")],
        ):
            with self.subTest(overrides=overrides), self.assertRaises(WorkerError):
                validate_worker_3mf(self.with_object_metadata(overrides))


    def test_native_extruder_metadata_requires_matching_explicit_palette(self):
        raw = self.with_object_metadata([("extruder", "2")])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = contents["Metadata/model_settings.config"]
        manifest = manifest.replace(
            b'<config><object id="2">',
            b'<config><object id="1"><metadata key="extruder" value="1"/></object><object id="2">',
        )
        contents["Metadata/model_settings.config"] = manifest
        def archive(data):
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as package:
                for name, contents_ in data.items():
                    package.writestr(name, contents_)
            return out.getvalue()
        self.assertTrue(validate_worker_3mf(archive(contents), native_tool_count=2))
        with self.assertRaisesRegex(WorkerError, "Unsupported"):
            validate_worker_3mf(archive(contents))
        with self.assertRaises(WorkerError):
            validate_worker_3mf(archive(contents), native_tool_count=1)
        for invalid in (b"0", b"3", b"-1", b"1.5"):
            with self.subTest(invalid=invalid):
                changed = dict(contents)
                changed["Metadata/model_settings.config"] = manifest.replace(
                    b'key="extruder" value="2"',
                    b'key="extruder" value="' + invalid + b'"',
                )
                with self.assertRaises(WorkerError):
                    validate_worker_3mf(archive(changed), native_tool_count=2)
        changed = dict(contents)
        changed["Metadata/model_settings.config"] = manifest.replace(
            b'<object id="1"><metadata key="extruder" value="1"/></object>', b'',
        )
        with self.assertRaisesRegex(WorkerError, "Every native object"):
            validate_worker_3mf(archive(changed), native_tool_count=2)

    def test_single_painted_model_requires_two_real_native_tools(self):
        original = self.package()
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts["Metadata/model_settings.config"] = (
            '<config><object id="1"><metadata key="extruder" value="1"/></object>'
            '<plate><metadata key="plater_id" value="1"/>'
            '<model_instance><metadata key="object_id" value="1"/>'
            '<metadata key="instance_id" value="0"/>'
            '<metadata key="identify_id" value="1"/></model_instance>'
            '</plate></config>'
        ).encode()
        target = b'<triangle v1="0" v2="1" v3="2"/>'

        def painted(state):
            data = dict(parts)
            data["3D/3dmodel.model"] = data["3D/3dmodel.model"].replace(
                target, b'<triangle v1="0" v2="1" v3="2" paint_color="' +
                state.encode() + b'"/>'
            )
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as package:
                for name, contents in data.items():
                    package.writestr(name, contents)
            return out.getvalue()

        self.assertTrue(validate_worker_3mf(painted("8"), native_tool_count=2))
        self.assertTrue(validate_worker_3mf(painted("0C"), native_tool_count=3))
        for payload, tools in (
            (painted("8"), None),
            (painted("4"), 2),
            (painted("0C"), 2),
            (painted("3C"), 3),
            (painted("40"), 2),
            (painted("4;M104 S300"), 2),
        ):
            with self.subTest(tools=tools), self.assertRaises(WorkerError):
                validate_worker_3mf(payload, native_tool_count=tools)

    def test_valid_core_model_is_admitted(self):
        self.assertTrue(validate_worker_3mf(self.package()))

    def test_larger_than_old_150k_triangle_limit_is_accepted(self):
        # Regression: MakerVault's validated STL and build-plate builder both
        # support 500,000 faces; the worker must not reject at 150,000.
        self.assertEqual(MAX_TRIANGLES, 500_000)
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        faces = '<triangle v1="0" v2="1" v3="2"/>' * 150001
        model = (f'<model xmlns="{ns}"><resources><object id="1" type="model"><mesh>'
                 '<vertices><vertex x="0" y="0" z="0"/>'
                 '<vertex x="1" y="0" z="0"/>'
                 '<vertex x="0" y="1" z="0"/></vertices>'
                 f'<triangles>{faces}</triangles></mesh></object></resources>'
                 '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 10 10 0"/></build>'
                 '</model>')
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("3D/3dmodel.model", model)
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
        self.assertTrue(validate_worker_3mf(data.getvalue()))

    def test_unknown_object_is_rejected(self):
        with self.assertRaisesRegex(WorkerError, "unknown"):
            validate_worker_3mf(self.package(malformed=True))

    def test_arbitrary_extra_zip_member_is_rejected(self):
        data = io.BytesIO(self.package())
        with zipfile.ZipFile(data, "a") as archive:
            archive.writestr("../evil.sh", "malicious")
        with self.assertRaisesRegex(WorkerError, "members"):
            validate_worker_3mf(data.getvalue())

    def test_missing_and_malformed_archive_rejected(self):
        with self.assertRaises(WorkerError):
            validate_worker_3mf(b"not a zip")
