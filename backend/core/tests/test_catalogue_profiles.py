import unittest

from core.catalogue_profiles import apply_board_profile, apply_component_profile


class CatalogueProfileTests(unittest.TestCase):
    def test_pico_profile_adds_complete_baseline(self):
        item = apply_board_profile({
            "manufacturer": "Raspberry Pi",
            "name": "Raspberry Pi Pico",
            "mcu": "RP2040",
            "specifications": {},
        })
        self.assertEqual(item["flash_mb"], 2)
        self.assertEqual(item["ram_kb"], 264)
        self.assertEqual(item["gpio_count"], 26)
        self.assertEqual(item["specifications"]["clock_mhz"], 133)
        self.assertEqual(item["specifications"]["uart_count"], 2)

    def test_profile_never_overwrites_explicit_values(self):
        item = apply_board_profile({
            "manufacturer": "Raspberry Pi",
            "name": "Raspberry Pi Pico",
            "mcu": "RP2040",
            "ram_kb": 999,
            "specifications": {"clock_mhz": 200},
        })
        self.assertEqual(item["ram_kb"], 999)
        self.assertEqual(item["specifications"]["clock_mhz"], 200)

    def test_common_sbc_and_nano_profiles_fill_mechanical_and_io_gaps(self):
        pi5 = apply_board_profile({
            "manufacturer": "Raspberry Pi",
            "name": "Raspberry Pi 5",
            "mcu": "BCM2712",
            "specifications": {},
        })
        self.assertEqual(pi5["dimensions_mm"], {"length": 85, "width": 56})
        self.assertEqual(pi5["gpio_count"], 28)
        self.assertEqual(pi5["specifications"]["pin_count"], 40)
        self.assertEqual(pi5["specifications"]["cpu_cores"], 4)

        xiao = apply_board_profile({
            "manufacturer": "Seeed Studio",
            "name": "XIAO RP2350",
            "mcu": "RP2350",
            "specifications": {},
        })
        self.assertEqual(xiao["dimensions_mm"], {"length": 21, "width": 17.8})
        self.assertEqual(xiao["gpio_count"], 19)
        self.assertEqual(xiao["specifications"]["i2c_count"], 2)

        nano = apply_board_profile({
            "manufacturer": "Arduino",
            "name": "Nano RP2040 Connect",
            "mcu": "RP2040",
            "specifications": {},
        })
        self.assertEqual(nano["flash_mb"], 16)
        self.assertEqual(nano["dimensions_mm"], {"length": 43.18, "width": 17.77})
        self.assertEqual(nano["specifications"]["pin_count"], 30)

    def test_component_profile_fills_missing_part_metadata(self):
        item = apply_component_profile({
            "name": "BME280 sensor",
            "part_number": "BME280",
            "specifications": {"interface": "I2C/SPI"},
        })
        self.assertEqual(item["specifications"]["interface"], "I2C/SPI")
        self.assertIn("0x76", item["specifications"]["i2c_addresses"])


if __name__ == "__main__":
    unittest.main()
