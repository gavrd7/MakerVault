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

    def test_catalogue_covers_sbc_and_compute_module_ecosystems(self):
        manufacturers = {item["manufacturer"] for item in BOARD_DEFINITIONS}
        expected = {"Orange Pi", "Hardkernel", "Radxa", "Banana Pi", "BeagleBoard.org", "LattePanda", "NVIDIA", "Khadas"}
        self.assertTrue(expected.issubset(manufacturers))
        board_types = {item.get("specifications", {}).get("board_type") for item in BOARD_DEFINITIONS}
        self.assertTrue({"microcontroller", "sbc", "compute_module"}.issubset(board_types))
        self.assertTrue(any(item["name"] == "Raspberry Pi 5" and item["specifications"]["board_type"] == "sbc" for item in BOARD_DEFINITIONS))
        self.assertTrue(any(item["name"] == "Jetson Orin NX 16GB" and item["specifications"]["board_type"] == "compute_module" for item in BOARD_DEFINITIONS))

    def test_expansion_boards_are_components_with_host_metadata(self):
        expansions = [item for item in COMPONENT_DEFINITIONS if item["category"] == "Expansion Boards"]
        self.assertGreaterEqual(len(expansions), 15)
        self.assertTrue(all(item["specifications"].get("host_family") for item in expansions))
        types = {item["specifications"].get("type") for item in expansions}
        self.assertTrue({"hat", "shield", "featherwing"}.issubset(types))

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
