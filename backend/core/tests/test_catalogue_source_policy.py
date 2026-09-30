from django.test import SimpleTestCase

from core.catalogue_source_policy import (
    append_source_trace,
    classify_source_url,
    ordered_source_candidates,
    source_tier,
)


class CatalogueSourcePolicyTests(SimpleTestCase):
    def test_authority_order_is_stable(self):
        self.assertLess(source_tier("manual").priority, source_tier("manufacturer").priority)
        self.assertLess(source_tier("manufacturer").priority, source_tier("curated").priority)
        self.assertLess(source_tier("curated").priority, source_tier("specialist").priority)
        self.assertLess(source_tier("specialist").priority, source_tier("community").priority)
        self.assertLess(source_tier("community").priority, source_tier("open_media").priority)
        self.assertLess(source_tier("open_media").priority, source_tier("generic").priority)

    def test_known_manufacturer_hosts_are_high_authority(self):
        self.assertEqual(
            classify_source_url("https://docs.arduino.cc/hardware/uno-r4-wifi/").key,
            "manufacturer",
        )
        self.assertEqual(
            classify_source_url("https://learn.adafruit.com/example").key,
            "manufacturer",
        )

    def test_sbc_vendor_hosts_are_manufacturer_sources(self):
        urls = [
            "https://www.orangepi.org/html/hardWare/example.html",
            "https://www.hardkernel.com/shop/example/",
            "https://docs.radxa.com/en/rock5/example",
            "https://docs.banana-pi.org/en/example",
            "https://docs.beagleboard.org/boards/example/",
            "https://www.lattepanda.com/example",
            "https://developer.nvidia.com/embedded/example",
            "https://docs.khadas.com/products/sbc/example",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(classify_source_url(url).key, "manufacturer")

    def test_specialist_and_community_sources_are_distinct(self):
        self.assertEqual(
            classify_source_url("https://www.espboards.dev/esp32/example/").key,
            "specialist",
        )
        self.assertEqual(
            classify_source_url("https://github.com/example/project", source_type="github").key,
            "community",
        )

    def test_candidates_are_sorted_by_authority_not_input_order(self):
        ordered = ordered_source_candidates([
            {"url": "https://example.net/widget"},
            {"url": "https://www.espboards.dev/esp32/widget/"},
            {"url": "https://docs.arduino.cc/hardware/widget/"},
        ])
        self.assertEqual(
            [item["tier"] for item in ordered],
            ["manufacturer", "specialist", "generic"],
        )

    def test_source_trace_is_bounded_and_deduplicated(self):
        metadata = {}
        for index in range(25):
            metadata = append_source_trace(
                metadata,
                provider=f"provider-{index}",
                url=f"https://example.test/{index}",
                tier="generic",
                result="checked",
            )
        self.assertEqual(len(metadata["source_trace"]), 20)
        latest = metadata["source_trace"][-1]
        metadata = append_source_trace(
            metadata,
            provider=latest["provider"],
            url=latest["url"],
            tier=latest["tier"],
            result=latest["result"],
        )
        self.assertEqual(len(metadata["source_trace"]), 20)
