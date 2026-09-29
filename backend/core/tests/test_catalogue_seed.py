import unittest

from core.catalogue_seed import BOARD_DEFINITIONS, CATEGORY_TREE, COMPONENT_DEFINITIONS


class CatalogueSeedTests(unittest.TestCase):
    def test_catalogue_has_broad_board_coverage(self):
        manufacturers = {item["manufacturer"] for item in BOARD_DEFINITIONS}
        expected = {
            "Espressif", "Raspberry Pi", "Arduino", "Seeed Studio", "M5Stack",
            "Adafruit", "SparkFun", "PJRC", "Waveshare", "LilyGo", "Heltec",
            "Olimex", "Elecrow",
        }
        self.assertTrue(expected.issubset(manufacturers))
        self.assertGreaterEqual(len(BOARD_DEFINITIONS), 65)

    def test_component_catalogue_is_substantial(self):
        self.assertGreaterEqual(len(COMPONENT_DEFINITIONS), 350)
        categories = {item["category"] for item in COMPONENT_DEFINITIONS}
        self.assertGreaterEqual(len(categories), 15)
        self.assertTrue(categories.issubset(set(CATEGORY_TREE)))

    def test_component_catalogue_covers_common_maker_project_staples(self):
        names = {item["name"] for item in COMPONENT_DEFINITIONS}
        expected = {
            "330 ohm resistor",
            "TMP36 analog temperature sensor",
            "Photoresistor LDR",
            "NE555 timer IC",
            "L293D dual H-bridge IC",
            "NEMA 17 bipolar stepper motor",
            "SCD40 CO2 temperature/humidity sensor",
            "MPR121 12-channel capacitive touch sensor",
            "NEO-6M GPS module",
            "USB-C female breakout connector",
            "18650 single-cell battery holder",
            "74HC00 quad NAND gate",
        }
        self.assertTrue(expected.issubset(names))

    def test_component_identity_keys_are_unique(self):
        keys = [
            (item["name"], item.get("part_number", ""))
            for item in COMPONENT_DEFINITIONS
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_board_identity_keys_are_unique(self):
        keys = [
            (item["manufacturer"], item["name"], item.get("variant", ""))
            for item in BOARD_DEFINITIONS
        ]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
