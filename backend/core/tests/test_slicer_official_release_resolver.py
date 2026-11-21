"""Official profile catalogues follow the exact selected native engine release."""
from django.test import SimpleTestCase

from core.slicer_official_profiles import OfficialProfileError
from core.slicer_official_release_resolver import (
    approved_catalogue_versions, default_catalogue_version,
    resolve_official_release,
)


class ExactOfficialCatalogueReleaseTests(SimpleTestCase):
    def test_every_supported_engine_has_exact_source_and_approved_release(self):
        expected = {
            "orcaslicer": {
                "2.4.2": ("OrcaSlicer/OrcaSlicer", "v2.4.2"),
                "2.5.0": ("OrcaSlicer/OrcaSlicer", "v2.5.0"),
            },
            "crealityprint": {
                "7.3.1": ("CrealityOfficial/CrealityPrint", "v7.3.1"),
            },
            "bambustudio": {
                "02.09.01.70": ("bambulab/BambuStudio", "v02.09.01.70"),
            },
            "prusaslicer": {
                "2.9.6": ("prusa3d/PrusaSlicer", "version_2.9.6"),
            },
            "snapmakerorca": {
                "2.4.1": ("Snapmaker/OrcaSlicer", "v2.4.1"),
            },
        }
        for engine, releases in expected.items():
            self.assertEqual(approved_catalogue_versions(engine), tuple(releases))
            for version, (source, ref) in releases.items():
                with self.subTest(engine=engine, version=version):
                    result = resolve_official_release(engine, version)
                    self.assertEqual((result.engine, result.version,
                                      result.source, result.ref),
                                     (engine, version, source, ref))

    def test_unknown_or_cross_engine_version_cannot_fall_back(self):
        for engine, version in (
                ("crealityprint", "7.3.0"),
                ("crealityprint", "2.5.0"),
                ("orcaslicer", "7.3.1"),
                ("orcaslicer", "2.6.0"),
                ("bambustudio", "2.9.6"),
                ("prusaslicer", "02.09.01.70"),
                ("snapmakerorca", "2.5.0"),
                ("unsupported", "7.3.1"),
                ("crealityprint", "../7.3.1")):
            with self.subTest(engine=engine, version=version):
                with self.assertRaises(OfficialProfileError):
                    resolve_official_release(engine, version)
        self.assertEqual(approved_catalogue_versions("unsupported"), ())

    def test_unselected_release_defaults_only_to_reviewed_version(self):
        self.assertEqual(default_catalogue_version("crealityprint"), "7.3.1")
        self.assertEqual(default_catalogue_version("bambustudio"), "02.09.01.70")
        self.assertEqual(default_catalogue_version("prusaslicer"), "2.9.6")
        self.assertEqual(default_catalogue_version("snapmakerorca"), "2.4.1")
        self.assertEqual(default_catalogue_version("orcaslicer"), "2.4.2")
        with self.assertRaises(OfficialProfileError):
            default_catalogue_version("unknown")

    def test_provider_constants_match_shared_reviewed_mapping(self):
        from core import (
            slicer_creality_official_profiles as cre,
            slicer_bambu_official_profiles as bbl,
            slicer_prusa_official_profiles as prusa,
            slicer_snapmaker_official_profiles as snap,
        )
        for p in (cre, bbl, prusa, snap):
            with self.subTest(engine=p.ENGINE):
                source = resolve_official_release(p.ENGINE, p.ENGINE_VERSION)
                self.assertEqual((p.SOURCE, p.REF), (source.source, source.ref))
