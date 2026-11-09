from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_bed_artwork import (
    _verify_svg, _verify_stl, official_artwork_source, official_bed_model_source,
)


class SlicerBedArtworkTests(SimpleTestCase):
    def setUp(self):
        self.profile = SimpleNamespace(
            engine="orcaslicer", engine_version="2.4.2", kind="printer",
            provenance="OrcaSlicer/OrcaSlicer@v2.4.2/Creality/machine/Creality K2.json",
        )

    @patch("core.slicer_bed_artwork._inspect_source")
    def test_resolves_owned_registered_official_texture_without_arbitrary_urls(self, inspect):
        inspect.return_value = {"bed_texture": "creality_k2_buildplate_texture.svg"}
        source = official_artwork_source(self.profile)
        self.assertIsNotNone(source)
        self.assertEqual(source[0],
                         "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/v2.4.2/resources/profiles/Creality/creality_k2_buildplate_texture.svg")
        self.assertTrue(source[1].startswith("slicer-reviewed-native-artwork/"))

    @patch("core.slicer_bed_artwork._inspect_source")
    def test_rejects_unpinned_urls_and_path_traversal(self, inspect):
        for filename in ("../../bad.svg", "https://example.com/bad.svg",
                         "javascript:bad.svg", "bad.png", "/tmp/bad.svg"):
            inspect.return_value = {"bed_texture": filename}
            self.assertIsNone(official_artwork_source(self.profile), filename)
        inspect.return_value = {"bed_texture": "valid.svg"}
        self.profile.provenance = "Unknown@latest/Creality/machine/anything.json"
        self.assertIsNone(official_artwork_source(self.profile))
        self.profile.provenance = "OrcaSlicer/OrcaSlicer@v2.4.2/Creality/machine/x.json"
        self.profile.engine = "prusaslicer"
        self.assertIsNone(official_artwork_source(self.profile))

    @patch("core.slicer_bed_artwork.resolved_native_profile")
    @patch("core.slicer_bed_artwork._inspect_source")
    def test_inherited_texture_uses_hash_checked_same_owner_chain(self, inspect, resolve):
        inspect.return_value = {"inherits": "Base printer"}
        resolve.return_value = b'{"bed_texture":"inherited_texture.svg"}'
        result = official_artwork_source(self.profile)
        self.assertEqual(result[0].split("/")[-1], "inherited_texture.svg")
        resolve.assert_called_once_with(self.profile)

    @patch("core.slicer_bed_artwork.resolved_native_profile")
    @patch("core.slicer_bed_artwork._inspect_source")
    def test_missing_parent_does_not_invent_artwork(self, inspect, resolve):
        from core.slicer_profiles import SlicerProfileError
        inspect.return_value = {"inherits": "Missing parent"}
        resolve.side_effect = SlicerProfileError("Missing parent")
        self.assertIsNone(official_artwork_source(self.profile))

    @patch("core.slicer_bed_artwork._inspect_source")
    def test_new_version_matching_requires_matching_registered_provenance(self, inspect):
        inspect.return_value = {"bed_texture": "future_plate.svg"}
        self.profile.engine_version = "2.5.0"
        self.assertIsNone(official_artwork_source(self.profile))
        self.profile.provenance = "OrcaSlicer/OrcaSlicer@v2.5.0/Creality/machine/K2.json"
        self.assertIn("/v2.5.0/", official_artwork_source(self.profile)[0])
        self.profile.engine_version = "../../master"
        self.assertIsNone(official_artwork_source(self.profile))

    @patch("core.slicer_bed_artwork.resolved_native_profile")
    def test_creality_native_artwork_adapter(self, resolve):
        self.profile.engine = "crealityprint"
        self.profile.engine_version = "7.3.0"
        self.profile.provenance = "CrealityOfficial/CrealityPrint@v7.3.0/Creality/machine/K2.json"
        resolve.return_value = b'{"bed_texture":"creality_k2.svg","bed_model":"creality_k2.stl"}'
        self.assertIn("CrealityPrint/v7.3.0", official_artwork_source(self.profile)[0])
        self.assertTrue(official_bed_model_source(self.profile)[0].endswith("/creality_k2.stl"))

    @patch("core.slicer_bed_artwork._inspect_source")
    def test_native_stl_discovery_rejects_untrusted_paths(self, inspect):
        inspect.return_value = {"bed_model": "../untrusted.stl"}
        self.assertIsNone(official_bed_model_source(self.profile))
        inspect.return_value = {"bed_model": "safe_bed.stl"}
        self.assertTrue(official_bed_model_source(self.profile)[0].endswith("/safe_bed.stl"))

    def test_invalid_stl_not_accepted(self):
        with self.assertRaises(ValueError):
            _verify_stl(b"not-a-real-stl")
        with self.assertRaises(ValueError):
            _verify_stl(b"x" * (4 * 1024 * 1024 + 1))

    def test_svg_validation_rejects_active_content_and_external_resources(self):
        good = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M1 2" style="fill:#abc"/></svg>'
        self.assertEqual(_verify_svg(good), good)
        for payload in (
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://x.invalid/a"/></svg>',
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg"/>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://x.invalid)"/></svg>',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                _verify_svg(payload)
