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

    def test_esp32_c3_devkit_profile_exposes_wiring_pin_metadata(self):
        item = apply_board_profile({
            "manufacturer": "Espressif",
            "name": "ESP32-C3-DevKitM-1",
            "mcu": "ESP32-C3",
            "specifications": {},
        })
        pins = {pin["name"]: pin for pin in item["pinout"]["pins"]}
        self.assertEqual(pins["GND"]["role"], "ground")
        self.assertEqual(pins["3V3"]["role"], "power_output")
        self.assertEqual(pins["TX"]["role"], "uart_tx")
        self.assertEqual(pins["RX"]["role"], "uart_rx")
        self.assertEqual(
            item["specifications"]["reference_provider"],
            "Espressif",
        )

    def test_adafruit_and_arduino_profiles_fill_common_catalogue_gaps(self):
        feather = apply_board_profile({
            "manufacturer": "Adafruit",
            "name": "Feather RP2040",
            "mcu": "RP2040",
            "specifications": {},
        })
        self.assertEqual(feather["flash_mb"], 8)
        self.assertEqual(feather["gpio_count"], 21)
        self.assertEqual(feather["dimensions_mm"], {"length": 50.8, "width": 22.8})
        self.assertIn("psram", feather["specifications"]["not_applicable_specs"])

        qtpy = apply_board_profile({
            "manufacturer": "Adafruit",
            "name": "QT Py ESP32-C3",
            "mcu": "ESP32-C3",
            "specifications": {},
        })
        self.assertEqual(qtpy["flash_mb"], 4)
        self.assertEqual(qtpy["gpio_count"], 13)
        self.assertFalse(qtpy["specifications"]["native_usb"])

        leonardo = apply_board_profile({
            "manufacturer": "Arduino",
            "name": "Leonardo",
            "mcu": "ATmega32U4",
            "specifications": {},
        })
        self.assertEqual(leonardo["specifications"]["pin_count"], 20)
        self.assertEqual(leonardo["specifications"]["usb_capability"], "Native USB HID / CDC")
        self.assertIn("psram", leonardo["specifications"]["not_applicable_specs"])

    def test_feather_esp32_s3_profile_keeps_memory_variant_agnostic(self):
        result = apply_board_profile({
            "manufacturer": "Adafruit",
            "name": "Feather ESP32-S3",
            "mcu": "ESP32-S3",
            "flash_mb": None,
            "psram_mb": None,
            "specifications": {},
        })
        self.assertEqual(result["usb_connector"], "USB-C")
        self.assertEqual(result["dimensions_mm"], {"length": 50.8, "width": 22.86})
        self.assertIsNone(result.get("flash_mb"))
        self.assertIsNone(result.get("psram_mb"))
        self.assertTrue(result["specifications"]["native_usb"])
        self.assertIn("multiple flash/PSRAM variants", result["specifications"]["variant_note"])

    def test_common_component_profiles_add_authoritative_metadata(self):
        cases = {
            "MCP23017": "Microchip",
            "DS18B20": "Analog Devices",
            "NE555": "Texas Instruments",
            "BNO055": "Bosch Sensortec",
            "PCA9685": "NXP",
        }
        for part, provider in cases.items():
            with self.subTest(part=part):
                result = apply_component_profile({
                    "name": part,
                    "part_number": part,
                    "description": "",
                    "specifications": {},
                })
                self.assertTrue(result["description"])
                self.assertEqual(result["specifications"]["reference_provider"], provider)
                self.assertTrue(result["specifications"]["reference_url"].startswith("https://"))

    def test_generic_component_description_uses_structured_specs_without_fake_source(self):
        result = apply_component_profile({
            "category": "Controls",
            "name": "100k potentiometer",
            "part_number": "",
            "description": "",
            "specifications": {
                "type": "potentiometer",
                "value": "100 kΩ",
                "interface": "analog",
            },
        })
        self.assertEqual(
            result["description"],
            "Variable resistor control with 100 kΩ, analog interface.",
        )
        self.assertNotIn("reference_url", result["specifications"])
        self.assertNotIn("reference_provider", result["specifications"])

    def test_named_component_prefers_profile_function_over_generic_description(self):
        result = apply_component_profile({
            "category": "Sensors",
            "name": "BME280 temperature/humidity/pressure sensor",
            "part_number": "BME280",
            "description": "",
            "specifications": {"type": "environment", "interface": "I2C/SPI"},
        })
        self.assertEqual(
            result["description"],
            "Temperature, humidity and pressure sensor.",
        )
        self.assertEqual(result["specifications"]["reference_provider"], "Bosch Sensortec")


    def test_orange_pi_sbc_profile_fills_computer_specs(self):
        enriched = apply_board_profile({
            "manufacturer": "Orange Pi", "name": "Orange Pi 5 Plus", "family": "Orange Pi 5",
            "mcu": "Rockchip RK3588", "specifications": {"board_type": "sbc"},
        })
        self.assertEqual(enriched["specifications"]["board_type"], "sbc")
        self.assertEqual(enriched["specifications"]["cpu_cores"], 8)
        self.assertEqual(enriched["specifications"]["npu_tops"], 6)
        self.assertEqual(enriched["gpio_count"], 28)
        self.assertEqual(enriched["dimensions_mm"], {"length": 100, "width": 75})

    def test_component_profile_adds_official_reference_and_description(self):
        result = apply_component_profile({
            "name": "BME280 temperature/humidity/pressure sensor",
            "part_number": "BME280",
            "description": "",
            "specifications": {},
        })
        self.assertEqual(
            result["description"],
            "Temperature, humidity and pressure sensor.",
        )
        self.assertEqual(
            result["specifications"]["reference_provider"],
            "Bosch Sensortec",
        )
        self.assertTrue(
            result["specifications"]["reference_url"].startswith("https://www.bosch-sensortec.com/")
        )

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
