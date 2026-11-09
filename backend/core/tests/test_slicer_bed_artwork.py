from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_bed_artwork import (
    _verify_svg, official_artwork_source,
)


class SlicerBedArtworkTests(SimpleTestCase):
    def setUp(self):
        self.profile = SimpleNamespace(
            engine="orcaslicer", kind="printer",
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
