import unittest

from core.catalogue_enrichment import update_board_enrichment_state


class DummyManufacturer:
    name = "Arduino"


class DummyBoard:
    manufacturer = DummyManufacturer()
    name = "Uno R3"
    family = "AVR"
    mcu = "ATmega328P"
    architecture = "AVR"
    flash_mb = None
    psram_mb = None
    ram_kb = 2
    gpio_count = 14
    wifi = False
    bluetooth = False
    zigbee = False
    thread = False
    usb_connector = "USB-B"
    dimensions_mm = {"length": 68.6, "width": 53.4}
    updated_at = None

    def __init__(self):
        self.specifications = {
            "clock_mhz": 16,
            "cpu_cores": 1,
            "not_applicable_specs": [
                "wifi_standard",
                "bluetooth_generation",
                "ieee_802154",
                "pio_state_machines",
            ],
        }


class EnrichmentStatusTests(unittest.TestCase):
    def test_unknown_fields_remain_on_backlog(self):
        board = DummyBoard()
        changed = update_board_enrichment_state(board, save=False)
        self.assertTrue(changed)
        self.assertEqual(board.specifications["technical_field_status"]["pin_count"], "unknown")
        self.assertIn("pin_count", board.specifications["technical_unresolved_fields"])

    def test_known_unsupported_fields_are_not_applicable(self):
        board = DummyBoard()
        update_board_enrichment_state(board, save=False)
        status = board.specifications["technical_field_status"]
        self.assertEqual(status["wifi_standard"], "not_applicable")
        self.assertEqual(status["bluetooth_generation"], "not_applicable")
        self.assertEqual(status["wireless"], "not_applicable")
        self.assertNotIn("wifi_standard", board.specifications["technical_unresolved_fields"])

    def test_known_values_are_not_backlogged(self):
        board = DummyBoard()
        update_board_enrichment_state(board, save=False)
        status = board.specifications["technical_field_status"]
        self.assertEqual(status["clock_mhz"], "value")
        self.assertEqual(status["gpio"], "value")


if __name__ == "__main__":
    unittest.main()
