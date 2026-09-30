"""Curated technical profiles used to enrich starter catalogue records.

Profiles only fill missing fields/specifications. They never replace populated user
values. References are retained as provenance but the catalogue remains editable.
"""

from __future__ import annotations

from copy import deepcopy


MCU_PROFILES = {
    "ESP8266": {
        "specifications": {
            "clock_mhz": 80,
            "cpu_cores": 1,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n",
            "reference_provider": "Espressif",
        },
    },
    "ESP32": {
        "ram_kb": 520,
        "specifications": {
            "clock_mhz": 240,
            "cpu_cores": 2,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n",
            "bluetooth_generation": "Bluetooth 4.2 / BLE",
            "reference_provider": "Espressif",
            "reference_url": "https://documentation.espressif.com/esp32_datasheet_en.html",
        },
    },
    "ESP32-S2": {
        "ram_kb": 320,
        "specifications": {
            "clock_mhz": 240,
            "cpu_cores": 1,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n",
            "usb_otg": True,
            "reference_provider": "Espressif",
            "reference_url": "https://documentation.espressif.com/esp32-s2_datasheet_en.html",
        },
    },
    "ESP32-S3": {
        "ram_kb": 512,
        "specifications": {
            "clock_mhz": 240,
            "cpu_cores": 2,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n",
            "bluetooth_generation": "Bluetooth 5 LE",
            "usb_otg": True,
            "reference_provider": "Espressif",
            "reference_url": "https://documentation.espressif.com/esp32-s3_datasheet_en.html",
        },
    },
    "ESP32-C3": {
        "ram_kb": 400,
        "specifications": {
            "clock_mhz": 160,
            "cpu_cores": 1,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n",
            "bluetooth_generation": "Bluetooth 5 LE",
            "usb_serial_jtag": True,
            "reference_provider": "Espressif",
            "reference_url": "https://documentation.espressif.com/esp32-c3_datasheet_en.html",
        },
    },
    "ESP32-C6": {
        "ram_kb": 512,
        "specifications": {
            "clock_mhz": 160,
            "cpu_cores": 1,
            "lp_sram_kb": 16,
            "operating_voltage": "3.3 V",
            "wifi_standard": "Wi-Fi 6 / 802.11 b/g/n",
            "bluetooth_generation": "Bluetooth 5.3 LE",
            "ieee_802154": True,
            "usb_serial_jtag": True,
            "reference_provider": "Espressif",
            "reference_url": "https://documentation.espressif.com/esp32-c6_datasheet_en.html",
        },
    },
    "RP2040": {
        "ram_kb": 264,
        "specifications": {
            "clock_mhz": 133,
            "cpu_cores": 2,
            "uart_count": 2,
            "spi_count": 2,
            "i2c_count": 2,
            "adc_channels": 4,
            "pwm_channels": 16,
            "native_usb": True,
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://www.raspberrypi.com/documentation/microcontrollers/rp2040.html",
        },
    },
    "RP2350": {
        "ram_kb": 520,
        "specifications": {
            "clock_mhz": 150,
            "cpu_cores": 2,
            "uart_count": 2,
            "spi_count": 2,
            "i2c_count": 2,
            "adc_channels": 4,
            "pwm_channels": 24,
            "native_usb": True,
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://www.raspberrypi.com/documentation/microcontrollers/silicon.html",
        },
    },
    "ATmega328P": {
        "ram_kb": 2,
        "specifications": {
            "native_usb": False,
            "dac_channels": 0,
            "flash_kb": 32,
            "clock_mhz": 16,
            "cpu_cores": 1,
            "operating_voltage": "5 V",
            "eeprom_kb": 1,
            "reference_provider": "Microchip / Arduino",
        },
    },
    "ATmega2560": {
        "flash_mb": 0.25,
        "ram_kb": 8,
        "specifications": {
            "native_usb": False,
            "dac_channels": 0,
            "clock_mhz": 16,
            "cpu_cores": 1,
            "operating_voltage": "5 V",
            "eeprom_kb": 4,
            "reference_provider": "Microchip / Arduino",
        },
    },
    "ATmega32U4": {
        "ram_kb": 2.5,
        "specifications": {
            "dac_channels": 0,
            "flash_kb": 32,
            "clock_mhz": 16,
            "cpu_cores": 1,
            "operating_voltage": "5 V",
            "eeprom_kb": 1,
            "native_usb": True,
            "reference_provider": "Microchip / Arduino",
        },
    },
    "ATmega4809": {
        "ram_kb": 6,
        "specifications": {
            "native_usb": False,
            "dac_channels": 0,
            "flash_kb": 48,
            "clock_mhz": 20,
            "cpu_cores": 1,
            "operating_voltage": "5 V",
            "eeprom_kb": 0.25,
            "reference_provider": "Microchip / Arduino",
        },
    },
    "SAMD21": {
        "flash_mb": 0.25,
        "ram_kb": 32,
        "specifications": {
            "clock_mhz": 48,
            "cpu_cores": 1,
            "native_usb": True,
            "reference_provider": "Microchip",
        },
    },
    "RA4M1": {
        "flash_mb": 0.25,
        "ram_kb": 32,
        "specifications": {
            "clock_mhz": 48,
            "cpu_cores": 1,
            "dac_channels": 1,
            "operating_voltage": "5 V board I/O",
            "native_usb": True,
            "reference_provider": "Renesas / Arduino",
        },
    },
}


BOARD_PROFILES = {
    ("Generic", "ESP32 C3 Super Mini"): {
        "flash_mb": 4,
        "ram_kb": 400,
        "gpio_count": 13,
        "dimensions_mm": {"length": 22.5, "width": 18},
        "specifications": {
            "adc_channels": 6,
            "uart_count": 2,
            "i2c_count": 1,
            "spi_count": 1,
            "pwm_channels": 6,
            "pin_count": 16,
            "reference_provider": "ESPBoards.dev",
            "reference_url": "https://www.espboards.dev/esp32/esp32-c3-super-mini/",
        },
    },
    ("Generic", "ESP32-S3 Super Mini"): {
        "flash_mb": 4,
        "gpio_count": 32,
        "dimensions_mm": {"length": 22.52, "width": 18},
        "specifications": {
            "adc_channels": 16,
            "uart_count": 3,
            "i2c_count": 2,
            "spi_count": 2,
            "pwm_channels": 8,
            "pin_count": 37,
            "reference_provider": "ESPBoards.dev",
            "reference_url": "https://www.espboards.dev/esp32/esp32-s3-super-mini/",
        },
    },
    ("Generic", "ESP32-C6 Super Mini"): {
        "flash_mb": 4,
        "gpio_count": 20,
        "dimensions_mm": {"length": 22.5, "width": 18},
        "specifications": {
            "adc_channels": 7,
            "uart_count": 2,
            "i2c_count": 1,
            "spi_count": 1,
            "pwm_channels": 6,
            "pin_count": 25,
            "reference_provider": "ESPBoards.dev",
            "reference_url": "https://www.espboards.dev/esp32/esp32-c6-super-mini/",
        },
    },
    ("Adafruit", "Feather ESP32-S3"): {
        "usb_connector": "USB-C",
        "dimensions_mm": {"length": 50.8, "width": 22.86},
        "specifications": {
            "adc_channels": 6,
            "native_usb": True,
            "usb_capability": "Native USB HID / CDC / MIDI / mass storage",
            "operating_voltage": "3.3 V",
            "not_applicable_specs": ["dac_channels", "ieee_802154", "pio_state_machines"],
            "reference_provider": "Adafruit",
            "reference_url": "https://learn.adafruit.com/adafruit-esp32-s3-feather",
            "variant_note": "Feather ESP32-S3 exists in multiple flash/PSRAM variants; memory remains unresolved unless the exact variant is known.",
        },
    },
    ("Adafruit", "Feather RP2040"): {
        "flash_mb": 8,
        "ram_kb": 264,
        "gpio_count": 21,
        "usb_connector": "USB-C",
        "dimensions_mm": {"length": 50.8, "width": 22.8},
        "specifications": {
            "adc_channels": 4,
            "uart_count": 2,
            "spi_count": 2,
            "i2c_count": 2,
            "pwm_channels": 16,
            "operating_voltage": "3.3 V",
            "not_applicable_specs": ["psram", "wifi_standard", "bluetooth_generation", "ieee_802154"],
            "reference_provider": "Adafruit",
            "reference_url": "https://www.adafruit.com/product/4884",
        },
    },
    ("Adafruit", "QT Py ESP32-C3"): {
        "flash_mb": 4,
        "ram_kb": 400,
        "gpio_count": 13,
        "usb_connector": "USB-C",
        "dimensions_mm": {"length": 22.0, "width": 17.8},
        "specifications": {
            "adc_channels": 5,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "native_usb": False,
            "operating_voltage": "3.3 V",
            "not_applicable_specs": ["psram", "dac_channels", "ieee_802154", "pio_state_machines"],
            "reference_provider": "Adafruit",
            "reference_url": "https://www.adafruit.com/product/5405",
        },
    },
    ("Seeed Studio", "XIAO RP2040"): {
        "flash_mb": 2,
        "ram_kb": 264,
        "gpio_count": 11,
        "dimensions_mm": {"length": 21, "width": 17.8},
        "specifications": {
            "adc_channels": 4,
            "uart_count": 1,
            "i2c_count": 1,
            "spi_count": 1,
            "pwm_channels": 11,
            "pin_count": 14,
            "operating_voltage": "3.3 V GPIO",
            "not_applicable_specs": ["wifi_standard", "bluetooth_generation", "ieee_802154"],
            "reference_provider": "Seeed Studio",
            "reference_url": "https://wiki.seeedstudio.com/XIAO-RP2040/",
        },
    },
    ("Seeed Studio", "XIAO RP2350"): {
        "flash_mb": 2,
        "ram_kb": 520,
        "gpio_count": 19,
        "dimensions_mm": {"length": 21, "width": 17.8},
        "specifications": {
            "adc_channels": 3,
            "uart_count": 2,
            "i2c_count": 2,
            "spi_count": 2,
            "pwm_channels": 19,
            "operating_voltage": "3.3 V GPIO",
            "not_applicable_specs": ["wifi_standard", "bluetooth_generation", "ieee_802154"],
            "reference_provider": "Seeed Studio",
            "reference_url": "https://wiki.seeedstudio.com/xiao_rp2350_arduino/",
        },
    },
    ("Seeed Studio", "XIAO ESP32C3"): {
        "flash_mb": 4,
        "ram_kb": 400,
        "gpio_count": 11,
        "dimensions_mm": {"length": 21, "width": 17.8},
        "specifications": {
            "adc_channels": 4,
            "uart_count": 2,
            "i2c_count": 1,
            "spi_count": 1,
            "pwm_channels": 6,
            "pin_count": 14,
            "input_voltage": "5 V USB-C / 3.7 V LiPo",
            "reference_provider": "ESPBoards.dev / Seeed Studio",
            "reference_url": "https://www.espboards.dev/esp32/xiao-esp32c3/",
        },
    },
    ("Seeed Studio", "XIAO ESP32C6"): {
        "flash_mb": 4,
        "ram_kb": 512,
        "gpio_count": 11,
        "dimensions_mm": {"length": 21, "width": 17.8},
        "specifications": {
            "adc_channels": 3,
            "uart_count": 2,
            "i2c_count": 1,
            "spi_count": 1,
            "pwm_channels": 6,
            "pin_count": 14,
            "input_voltage": "5 V USB-C / 3.7 V LiPo",
            "reference_provider": "ESPBoards.dev / Seeed Studio",
            "reference_url": "https://www.espboards.dev/esp32/xiao-esp32c6/",
        },
    },
    ("Seeed Studio", "XIAO ESP32S3"): {
        "flash_mb": 8,
        "psram_mb": 8,
        "ram_kb": 512,
        "gpio_count": 11,
        "dimensions_mm": {"length": 21, "width": 17.8},
        "specifications": {
            "adc_channels": 9,
            "uart_count": 3,
            "i2c_count": 2,
            "spi_count": 2,
            "pwm_channels": 8,
            "pin_count": 14,
            "input_voltage": "5 V USB-C / 3.7 V LiPo",
            "reference_provider": "ESPBoards.dev / Seeed Studio",
            "reference_url": "https://www.espboards.dev/esp32/xiao-esp32s3/",
        },
    },
    ("Waveshare", "ESP32-S3-Zero"): {
        "flash_mb": 4,
        "psram_mb": 2,
        "ram_kb": 512,
        "gpio_count": 24,
        "dimensions_mm": {"length": 23.5, "width": 18},
        "specifications": {
            "adc_channels": 18,
            "uart_count": 3,
            "i2c_count": 2,
            "spi_count": 2,
            "pwm_channels": 8,
            "pin_count": 27,
            "reference_provider": "ESPBoards.dev / Waveshare",
            "reference_url": "https://www.espboards.dev/esp32/esp32-s3-zero/",
        },
    },
    ("Waveshare", "ESP32-C6-Zero"): {
        "flash_mb": 4,
        "ram_kb": 512,
        "gpio_count": 20,
        "dimensions_mm": {"length": 23.5, "width": 18},
        "specifications": {
            "adc_channels": 7,
            "uart_count": 2,
            "i2c_count": 1,
            "spi_count": 1,
            "pwm_channels": 6,
            "pin_count": 25,
            "reference_provider": "ESPBoards.dev / Waveshare",
            "reference_url": "https://www.espboards.dev/esp32/esp32-c6-zero-mini/",
        },
    },
    ("Raspberry Pi", "Raspberry Pi Zero"): {
        "ram_kb": 512 * 1024,
        "gpio_count": 28,
        "usb_connector": "Micro-USB",
        "dimensions_mm": {"length": 65, "width": 30},
        "architecture": "ARM11",
        "specifications": {
            "clock_mhz": 1000,
            "cpu_cores": 1,
            "pin_count": 40,
            "operating_voltage": "3.3 V GPIO",
            "not_applicable_specs": ["wifi_standard", "bluetooth_generation", "ieee_802154", "pio_state_machines"],
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://www.raspberrypi.com/news/raspberry-pi-zero/",
        },
    },
    ("Raspberry Pi", "Raspberry Pi Zero W"): {
        "ram_kb": 512 * 1024,
        "gpio_count": 28,
        "usb_connector": "Micro-USB",
        "dimensions_mm": {"length": 65, "width": 30},
        "architecture": "ARM11",
        "specifications": {
            "clock_mhz": 1000,
            "cpu_cores": 1,
            "pin_count": 40,
            "operating_voltage": "3.3 V GPIO",
            "wifi_standard": "802.11 b/g/n 2.4 GHz",
            "bluetooth_generation": "Bluetooth 4.1 / BLE",
            "not_applicable_specs": ["ieee_802154", "pio_state_machines"],
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://www.raspberrypi.com/news/raspberry-pi-zero/",
        },
    },
    ("Raspberry Pi", "Raspberry Pi Zero 2 W"): {
        "ram_kb": 512 * 1024,
        "gpio_count": 28,
        "usb_connector": "Micro-USB",
        "dimensions_mm": {"length": 65, "width": 30},
        "architecture": "ARM Cortex-A53",
        "specifications": {
            "clock_mhz": 1000,
            "cpu_cores": 4,
            "pin_count": 40,
            "operating_voltage": "3.3 V GPIO",
            "wifi_standard": "802.11 b/g/n 2.4 GHz",
            "bluetooth_generation": "Bluetooth 4.2 / BLE",
            "not_applicable_specs": ["ieee_802154", "pio_state_machines"],
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://datasheets.raspberrypi.com/rpizero2/raspberry-pi-zero-2-w-product-brief.pdf",
        },
    },
    ("Raspberry Pi", "Raspberry Pi 3 Model B+"): {
        "ram_kb": 1024 * 1024,
        "gpio_count": 28,
        "usb_connector": "Micro-USB",
        "dimensions_mm": {"length": 85, "width": 56},
        "architecture": "ARM Cortex-A53",
        "specifications": {
            "clock_mhz": 1400,
            "cpu_cores": 4,
            "pin_count": 40,
            "operating_voltage": "3.3 V GPIO",
            "wifi_standard": "802.11 b/g/n/ac 2.4/5 GHz",
            "bluetooth_generation": "Bluetooth 4.2 / BLE",
            "not_applicable_specs": ["ieee_802154", "pio_state_machines"],
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/",
        },
    },
    ("Raspberry Pi", "Raspberry Pi 4 Model B"): {
        "gpio_count": 28,
        "usb_connector": "USB-C",
        "dimensions_mm": {"length": 85, "width": 56},
        "architecture": "ARM Cortex-A72",
        "specifications": {
            "clock_mhz": 1800,
            "cpu_cores": 4,
            "pin_count": 40,
            "operating_voltage": "3.3 V GPIO",
            "wifi_standard": "802.11 b/g/n/ac 2.4/5 GHz",
            "bluetooth_generation": "Bluetooth 5 / BLE",
            "not_applicable_specs": ["ieee_802154", "pio_state_machines"],
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-datasheet.pdf",
        },
    },
    ("Raspberry Pi", "Raspberry Pi 5"): {
        "gpio_count": 28,
        "usb_connector": "USB-C",
        "dimensions_mm": {"length": 85, "width": 56},
        "architecture": "ARM Cortex-A76",
        "specifications": {
            "clock_mhz": 2400,
            "cpu_cores": 4,
            "pin_count": 40,
            "operating_voltage": "3.3 V GPIO",
            "uart_count": 5,
            "spi_count": 6,
            "i2c_count": 4,
            "pwm_channels": 4,
            "wifi_standard": "802.11ac dual-band",
            "bluetooth_generation": "Bluetooth 5 / BLE",
            "not_applicable_specs": ["ieee_802154", "pio_state_machines"],
            "reference_provider": "Raspberry Pi",
            "reference_url": "https://www.raspberrypi.com/products/raspberry-pi-5/",
        },
    },
    ("Raspberry Pi", "Raspberry Pi Pico"): {
        "flash_mb": 2,
        "gpio_count": 26,
        "dimensions_mm": {"length": 51, "width": 21},
        "specifications": {
            "not_applicable_specs": ["wifi_standard","bluetooth_generation","ieee_802154"],
            "adc_channels": 3,
            "input_voltage": "1.8–5.5 V DC",
            "pio_state_machines": 8,
            "reference_url": "https://www.raspberrypi.com/products/raspberry-pi-pico/",
        },
    },
    ("Raspberry Pi", "Raspberry Pi Pico W"): {
        "flash_mb": 2,
        "gpio_count": 26,
        "dimensions_mm": {"length": 51, "width": 21},
        "specifications": {
            "not_applicable_specs": ["ieee_802154"],
            "adc_channels": 3,
            "input_voltage": "1.8–5.5 V DC",
            "pio_state_machines": 8,
            "reference_url": "https://www.raspberrypi.com/products/raspberry-pi-pico/",
        },
    },
    ("Raspberry Pi", "Raspberry Pi Pico 2"): {
        "flash_mb": 4,
        "gpio_count": 26,
        "dimensions_mm": {"length": 51, "width": 21},
        "specifications": {
            "not_applicable_specs": ["wifi_standard","bluetooth_generation","ieee_802154"],
            "adc_channels": 4,
            "input_voltage": "1.8–5.5 V DC",
            "pio_state_machines": 12,
            "reference_url": "https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html",
        },
    },
    ("Raspberry Pi", "Raspberry Pi Pico 2 W"): {
        "flash_mb": 4,
        "gpio_count": 26,
        "dimensions_mm": {"length": 51, "width": 21},
        "specifications": {
            "not_applicable_specs": ["ieee_802154"],
            "adc_channels": 4,
            "input_voltage": "1.8–5.5 V DC",
            "pio_state_machines": 12,
            "reference_url": "https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html",
        },
    },
    ("Arduino", "Nano 33 IoT"): {
        "ram_kb": 32,
        "gpio_count": 22,
        "dimensions_mm": {"length": 43.16, "width": 17.77},
        "specifications": {
            "clock_mhz": 48,
            "cpu_cores": 1,
            "pin_count": 30,
            "native_usb": True,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n 2.4 GHz",
            "bluetooth_generation": "Bluetooth LE",
            "imu": "LSM6DS3",
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/hardware/nano-33-iot",
        },
    },
    ("Arduino", "Nano RP2040 Connect"): {
        "flash_mb": 16,
        "ram_kb": 264,
        "gpio_count": 22,
        "dimensions_mm": {"length": 43.18, "width": 17.77},
        "specifications": {
            "clock_mhz": 133,
            "cpu_cores": 2,
            "pin_count": 30,
            "adc_channels": 4,
            "pio_state_machines": 8,
            "native_usb": True,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n 2.4 GHz",
            "bluetooth_generation": "Bluetooth 4.2",
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/resources/datasheets/ABX00053-datasheet.pdf",
        },
    },
    ("Arduino", "Nano ESP32"): {
        "flash_mb": 16,
        "ram_kb": 512,
        "gpio_count": 22,
        "dimensions_mm": {"length": 45, "width": 18},
        "specifications": {
            "clock_mhz": 240,
            "cpu_cores": 2,
            "pin_count": 30,
            "adc_channels": 8,
            "native_usb": True,
            "operating_voltage": "3.3 V",
            "wifi_standard": "802.11 b/g/n 2.4 GHz",
            "bluetooth_generation": "Bluetooth 5 LE",
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/hardware/nano-esp32",
        },
    },
    ("Arduino", "Uno R3"): {
        "gpio_count": 14,
        "dimensions_mm": {"length": 68.6, "width": 53.4},
        "specifications": {
            "not_applicable_specs": ["wifi_standard","bluetooth_generation","ieee_802154","pio_state_machines"],
            "adc_channels": 6,
            "pwm_channels": 6,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "input_voltage": "7–12 V recommended",
            "reference_url": "https://docs.arduino.cc/hardware/uno-rev3/",
        },
    },
    ("Arduino", "Mega 2560 Rev3"): {
        "gpio_count": 54,
        "dimensions_mm": {"length": 101.52, "width": 53.3},
        "specifications": {
            "not_applicable_specs": ["psram","wifi_standard","bluetooth_generation","ieee_802154","pio_state_machines"],
            "adc_channels": 16,
            "pwm_channels": 15,
            "uart_count": 4,
            "spi_count": 1,
            "i2c_count": 1,
            "pin_count": 54,
            "native_usb": False,
            "usb_capability": "USB serial via secondary USB interface",
            "input_voltage": "7–12 V recommended",
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/hardware/mega-2560/",
        },
    },
    ("Arduino", "Nano Every"): {
        "gpio_count": 20,
        "dimensions_mm": {"length": 45, "width": 18},
        "specifications": {
            "not_applicable_specs": ["wifi_standard","bluetooth_generation","ieee_802154","pio_state_machines"],
            "adc_channels": 8,
            "pwm_channels": 5,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "reference_url": "https://docs.arduino.cc/hardware/nano-every/",
        },
    },
    ("Arduino", "Nano"): {
        "ram_kb": 2,
        "gpio_count": 22,
        "dimensions_mm": {"length": 45, "width": 18},
        "specifications": {
            "not_applicable_specs": ["wifi_standard","bluetooth_generation","ieee_802154","pio_state_machines"],
            "adc_channels": 8,
            "pwm_channels": 6,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/hardware/nano/",
        },
    },
    ("Arduino", "Leonardo"): {
        "ram_kb": 2.5,
        "gpio_count": 20,
        "usb_connector": "Micro-USB",
        "dimensions_mm": {"length": 68.6, "width": 53.3},
        "specifications": {
            "not_applicable_specs": ["psram","wifi_standard","bluetooth_generation","ieee_802154","pio_state_machines"],
            "adc_channels": 12,
            "pwm_channels": 7,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "pin_count": 20,
            "native_usb": True,
            "usb_capability": "Native USB HID / CDC",
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/hardware/leonardo",
        },
    },
    ("Arduino", "Micro"): {
        "ram_kb": 2.5,
        "gpio_count": 20,
        "dimensions_mm": {"length": 48, "width": 18},
        "specifications": {
            "not_applicable_specs": ["wifi_standard","bluetooth_generation","ieee_802154","pio_state_machines"],
            "adc_channels": 12,
            "pwm_channels": 7,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/retired/boards/arduino-micro/",
        },
    },
    ("Arduino", "Uno R4 Minima"): {
        "flash_mb": 0.25,
        "ram_kb": 32,
        "gpio_count": 14,
        "specifications": {
            "not_applicable_specs": ["wifi_standard","bluetooth_generation","ieee_802154","pio_state_machines"],
            "adc_channels": 6,
            "pwm_channels": 6,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "can": True,
            "reference_url": "https://docs.arduino.cc/hardware/uno-r4-minima/",
        },
    },
    ("Arduino", "Uno R4 WiFi"): {
        "flash_mb": 0.25,
        "ram_kb": 32,
        "gpio_count": 14,
        "specifications": {
            "not_applicable_specs": ["ieee_802154","pio_state_machines"],
            "adc_channels": 6,
            "pwm_channels": 6,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "can": True,
            "led_matrix": "12×8",
            "reference_url": "https://docs.arduino.cc/hardware/uno-r4-wifi/",
        },
    },
    ("PJRC", "Teensy 4.0"): {
        "flash_mb": 2,
        "ram_kb": 1024,
        "gpio_count": 40,
        "specifications": {
            "clock_mhz": 600,
            "adc_channels": 14,
            "pwm_channels": 31,
            "native_usb": True,
            "reference_url": "https://www.pjrc.com/store/teensy40.html",
        },
    },
    ("PJRC", "Teensy 4.1"): {
        "flash_mb": 8,
        "ram_kb": 1024,
        "gpio_count": 55,
        "specifications": {
            "clock_mhz": 600,
            "adc_channels": 18,
            "pwm_channels": 35,
            "native_usb": True,
            "reference_url": "https://www.pjrc.com/store/teensy41.html",
        },
    },
    ("Orange Pi", "Orange Pi 5 Plus"): {
        "gpio_count": 28, "dimensions_mm": {"length": 100, "width": 75},
        "specifications": {"clock_mhz": 2400, "cpu_cores": 8, "ram_options": ["4 GB", "8 GB", "16 GB", "32 GB"], "storage": ["microSD", "eMMC module", "M.2 2280 NVMe"], "ethernet": "2× 2.5GbE", "gpio_header": "40-pin · 28 GPIO · 3.3 V", "uart_count": 6, "i2c_count": 4, "npu_tops": 6, "power_input": "USB-C 5 V / 4 A", "os_support": ["Orange Pi OS", "Ubuntu", "Debian", "OpenWrt", "Android"], "reference_provider": "Orange Pi", "reference_url": "https://www.orangepi.org/orangepiwiki/index.php/Orange_Pi_5_Plus"},
    },
    ("Orange Pi", "Orange Pi 5 Pro"): {
        "dimensions_mm": {"length": 89, "width": 56}, "wifi": True, "bluetooth": True,
        "specifications": {"clock_mhz": 2400, "cpu_cores": 8, "ram_options": ["4 GB", "8 GB", "16 GB"], "storage": ["microSD", "eMMC module", "M.2 NVMe/SATA"], "ethernet": "Gigabit Ethernet", "gpio_header": "40-pin", "npu_tops": 6, "power_input": "USB-C 5 V / 5 A", "os_support": ["Orange Pi OS", "Ubuntu", "Debian", "Android"], "reference_provider": "Orange Pi"},
    },
    ("Orange Pi", "Orange Pi Zero 3"): {
        "dimensions_mm": {"length": 55, "width": 50}, "gpio_count": 16, "wifi": True, "bluetooth": True,
        "specifications": {"clock_mhz": 1500, "cpu_cores": 4, "ram_options": ["1 GB", "1.5 GB", "2 GB", "4 GB"], "storage": ["microSD", "16 MB SPI flash"], "ethernet": "Gigabit Ethernet", "gpio_header": "26-pin plus 13-pin function header", "uart_count": 1, "i2c_count": 1, "spi_count": 1, "power_input": "USB-C 5 V", "wifi_standard": "802.11 a/b/g/n/ac", "bluetooth_generation": "Bluetooth 5.0", "os_support": ["Orange Pi OS", "Ubuntu", "Debian", "Android"], "reference_provider": "Orange Pi", "reference_url": "https://www.orangepi.org/orangepiwiki/index.php/Orange_Pi_Zero_3"},
    },
}


COMPONENT_PART_PROFILES = {
    "BME280": {
        "i2c_addresses": ["0x76", "0x77"],
        "function": "Temperature, humidity and pressure sensor",
        "interface": "I2C/SPI",
        "supply_voltage": "1.71–3.6 V",
        "package": "8-pin LGA, 2.5 × 2.5 × 0.93 mm",
        "reference_provider": "Bosch Sensortec",
        "reference_url": "https://www.bosch-sensortec.com/products/environmental-sensors/humidity-sensors-bme280/",
    },
    "BMP280": {
        "i2c_addresses": ["0x76", "0x77"],
        "function": "Temperature and barometric pressure sensor",
        "interface": "I2C/SPI",
        "supply_voltage": "1.71–3.6 V",
        "reference_provider": "Bosch Sensortec",
        "reference_url": "https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/bmp280/",
    },
    "SHT31": {
        "i2c_addresses": ["0x44", "0x45"],
        "function": "Digital temperature and humidity sensor",
        "interface": "I2C",
        "reference_provider": "Sensirion",
        "reference_url": "https://sensirion.com/products/catalog/SHT31-DIS",
    },
    "SHT40": {
        "i2c_addresses": ["0x44"],
        "function": "Digital temperature and humidity sensor",
        "interface": "I2C",
        "reference_provider": "Sensirion",
        "reference_url": "https://sensirion.com/products/catalog/SHT40",
    },
    "MPU6050": {"i2c_addresses": ["0x68", "0x69"], "function": "6-axis accelerometer and gyroscope"},
    "ADXL345": {
        "i2c_addresses": ["0x53", "0x1D"],
        "function": "3-axis digital accelerometer",
        "interface": "I2C/SPI",
        "resolution": "up to 13-bit",
        "supply_voltage": "2.0–3.6 V",
        "reference_provider": "Analog Devices",
        "reference_url": "https://www.analog.com/en/products/adxl345.html",
    },
    "VL53L0X": {
        "i2c_addresses": ["0x29"],
        "function": "Time-of-flight distance sensor",
        "interface": "I2C",
        "typical_range": "up to 2 m",
        "reference_provider": "STMicroelectronics",
        "reference_url": "https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html",
    },
    "VL53L1X": {
        "i2c_addresses": ["0x29"],
        "function": "Long-range time-of-flight distance sensor",
        "interface": "I2C",
        "typical_range": "up to 4 m",
        "reference_provider": "STMicroelectronics",
        "reference_url": "https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x.html",
    },
    "INA219": {
        "function": "High-side current, voltage and power monitor",
        "interface": "I2C/SMBus",
        "resolution": "12-bit",
        "bus_voltage": "0–26 V",
        "supply_voltage": "3–5.5 V",
        "reference_provider": "Texas Instruments",
        "reference_url": "https://www.ti.com/product/INA219",
    },
    "INA226": {
        "function": "Current, voltage and power monitor",
        "interface": "I2C/SMBus",
        "resolution": "16-bit",
        "bus_voltage": "0–36 V",
        "reference_provider": "Texas Instruments",
        "reference_url": "https://www.ti.com/product/INA226",
    },
    "ADS1115": {
        "function": "4-channel 16-bit delta-sigma ADC",
        "resolution": "16-bit",
        "channels": 4,
        "interface": "I2C",
        "sample_rate": "up to 860 SPS",
        "supply_voltage": "2–5.5 V",
        "reference_provider": "Texas Instruments",
        "reference_url": "https://www.ti.com/product/ADS1115",
    },
    "W5500": {
        "function": "10/100 Ethernet controller with hardware TCP/IP",
        "interface": "SPI",
        "reference_provider": "WIZnet",
        "reference_url": "https://docs.wiznet.io/Product/iEthernet/W5500/overview",
    },
    "MCP2515": {
        "function": "Standalone CAN controller",
        "interface": "SPI",
        "reference_provider": "Microchip",
        "reference_url": "https://www.microchip.com/en-us/product/MCP2515",
    },
    "MFRC522": {"function": "13.56 MHz RFID reader/writer", "frequency": "13.56 MHz"},
    "PN532": {"function": "13.56 MHz NFC controller", "frequency": "13.56 MHz"},
    "nRF24L01+": {"function": "2.4 GHz ISM-band transceiver", "frequency": "2.4 GHz"},
    "INMP441": {"function": "Digital MEMS microphone", "interface": "I2S"},
    "MAX98357A": {
        "function": "Mono Class-D I2S audio amplifier",
        "interface": "I2S",
        "reference_provider": "Analog Devices",
        "reference_url": "https://www.analog.com/en/products/max98357a.html",
    },
    "DS3231": {
        "function": "Temperature-compensated real-time clock",
        "interface": "I2C",
        "reference_provider": "Analog Devices",
        "reference_url": "https://www.analog.com/en/products/ds3231.html",
    },
    "PCA9685": {
        "function": "16-channel 12-bit PWM controller",
        "channels": 16,
        "resolution": "12-bit",
        "interface": "I2C",
        "reference_provider": "NXP",
        "reference_url": "https://www.nxp.com/products/power-management/lighting-driver-and-controller-ics/led-drivers/16-channel-12-bit-pwm-fm-plus-ic-bus-led-driver%3APCA9685",
    },
    "TMC2209": {
        "function": "Silent stepper motor driver",
        "interface": "Step/Dir/UART",
        "reference_provider": "Analog Devices / Trinamic",
        "reference_url": "https://www.analog.com/en/products/tmc2209.html",
    },
    "A4988": {"function": "Bipolar stepper motor driver", "interface": "Step/Dir"},
    "TP4056": {"function": "Single-cell Li-ion/LiPo linear charger", "charge_voltage": "4.2 V"},
    "WS2812B": {"function": "Individually addressable RGB LED", "protocol": "single-wire", "voltage": "5 V"},
    "GC9A01": {"function": "Round TFT LCD controller", "interface": "SPI", "resolution": "240x240"},
    "SSD1306": {"function": "Monochrome OLED display controller", "interface": "I2C/SPI"},
    "ILI9341": {"function": "TFT LCD display controller", "interface": "SPI/parallel"},
    "HC-SR04": {"function": "Ultrasonic ranging module", "typical_range": "2–400 cm"},
    "HC-SR501": {"function": "PIR motion detector module"},
    "LD2410B": {"function": "24 GHz mmWave presence sensor", "frequency": "24 GHz"},
    "BME680": {
        "function": "Temperature, humidity, pressure and gas sensor",
        "interface": "I2C/SPI",
        "reference_provider": "Bosch Sensortec",
        "reference_url": "https://www.bosch-sensortec.com/en/products/environmental-sensors/gas-sensors/bme680",
    },
    "BME688": {
        "function": "Temperature, humidity, pressure and AI-capable gas sensor",
        "interface": "I2C/SPI",
        "reference_provider": "Bosch Sensortec",
        "reference_url": "https://www.bosch-sensortec.com/products/environmental-sensors/gas-sensors/bme688/",
    },
    "BMP388": {
        "function": "Precision absolute barometric pressure sensor",
        "interface": "I2C/SPI",
        "reference_provider": "Bosch Sensortec",
        "reference_url": "https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/bmp388/",
    },
    "BNO055": {
        "function": "9-axis absolute-orientation sensor with integrated sensor fusion",
        "interface": "I2C/UART",
        "reference_provider": "Bosch Sensortec",
        "reference_url": "https://www.bosch-sensortec.com/products/smart-sensors/bno055/",
    },
    "MCP23017": {
        "function": "16-bit general-purpose I/O expander",
        "interface": "I2C",
        "channels": 16,
        "supply_voltage": "1.8–5.5 V",
        "reference_provider": "Microchip",
        "reference_url": "https://www.microchip.com/en-us/product/mcp23017",
    },
    "DS18B20": {
        "function": "Programmable-resolution digital temperature sensor",
        "interface": "1-Wire",
        "temperature_range": "-55–125 °C",
        "resolution": "9–12 bit",
        "reference_provider": "Analog Devices",
        "reference_url": "https://www.analog.com/en/products/ds18b20.html",
    },
    "NE555": {
        "function": "Single precision timer",
        "reference_provider": "Texas Instruments",
        "reference_url": "https://www.ti.com/product/NE555",
    },
    "LM358": {
        "function": "Dual operational amplifier",
        "channels": 2,
        "reference_provider": "Texas Instruments",
        "reference_url": "https://www.ti.com/product/LM358",
    },
    "LM393": {
        "function": "Dual differential comparator",
        "channels": 2,
        "reference_provider": "Texas Instruments",
        "reference_url": "https://www.ti.com/product/LM393",
    },
}


GENERIC_COMPONENT_TYPE_DESCRIPTIONS = {
    "resistor": "General-purpose resistor",
    "capacitor": "General-purpose capacitor",
    "diode": "Semiconductor diode",
    "transistor": "Discrete transistor",
    "mosfet": "MOSFET transistor",
    "optocoupler": "Optically isolated signal coupler",
    "regulator": "Voltage regulator",
    "led": "Light-emitting diode",
    "rgb-led": "RGB light-emitting diode",
    "addressable-led": "Individually addressable LED",
    "led-ring": "Addressable LED ring",
    "led-matrix": "LED matrix display",
    "led-strip": "Addressable LED strip",
    "oled": "OLED display module",
    "tft": "TFT display module",
    "round-tft": "Round TFT display module",
    "character-lcd": "Character LCD module",
    "e-paper": "E-paper display module",
    "environment": "Environmental sensor module",
    "temperature": "Temperature sensor",
    "light": "Light sensor",
    "imu": "Inertial measurement sensor",
    "accelerometer": "Accelerometer sensor",
    "distance": "Distance sensor",
    "motion": "Motion sensor",
    "presence": "Presence sensor",
    "magnetic": "Magnetic sensor",
    "current": "Current-sensing module",
    "adc": "Analog-to-digital converter module",
    "bluetooth": "Bluetooth communication module",
    "2.4ghz-radio": "2.4 GHz radio module",
    "lora": "LoRa radio module",
    "ethernet": "Ethernet communication module",
    "can": "CAN bus controller module",
    "can-transceiver": "CAN bus transceiver module",
    "rs485": "RS-485 transceiver module",
    "rfid": "RFID reader module",
    "nfc": "NFC/RFID interface module",
    "usb-serial": "USB-to-serial interface module",
    "microphone": "Microphone module",
    "amplifier": "Audio amplifier module",
    "audio-player": "Embedded audio playback module",
    "buzzer": "Electronic buzzer",
    "speaker": "Compact loudspeaker",
    "rotary-encoder": "Rotary encoder input control",
    "button": "Momentary push-button control",
    "switch": "Mechanical switch",
    "microswitch": "Mechanical microswitch",
    "limit-switch": "Mechanical limit switch",
    "dip-switch": "DIP switch bank",
    "potentiometer": "Variable resistor control",
    "trimmer": "Trimmer potentiometer",
    "joystick": "Analog joystick input module",
    "keypad": "Matrix keypad",
    "touch": "Capacitive touch input module",
    "buck": "DC-DC step-down converter module",
    "boost": "DC-DC step-up converter module",
    "battery-charger": "Battery charging module",
    "bms": "Battery protection / management module",
    "usb-pd": "USB Power Delivery trigger module",
    "power-connector": "Power connector",
    "relay": "Electromechanical relay module",
    "solid-state-relay": "Solid-state relay",
    "mosfet-switch": "MOSFET switching module",
    "level-shifter": "Logic-level shifting module",
    "shift-register": "Digital shift register",
    "gpio-expander": "GPIO expansion device",
    "breadboard": "Solderless prototyping breadboard",
    "perfboard": "Solderable prototyping board",
    "header": "Pin header connector",
    "jumper-wire": "Dupont-style jumper wire set",
    "connector": "Electrical connector",
    "terminal-block": "Screw terminal connector",
    "flash-storage": "Removable flash-storage interface module",
    "eeprom": "Non-volatile EEPROM memory module",
    "fram": "Non-volatile FRAM memory module",
    "rtc": "Real-time clock module",
    "servo": "RC servo motor",
    "stepper": "Stepper motor",
    "motor-driver": "Motor driver module",
    "stepper-driver": "Stepper motor driver module",
    "dc-motor-driver": "DC motor driver module",
    "pwm-driver": "PWM output driver module",
    "camera": "Camera module",
    "fan": "Cooling fan",
    "heat-set-insert": "Heat-set threaded insert assortment",
    "fastener": "Mechanical fastener assortment",
    "magnet": "Permanent magnet assortment",
    "power-meter": "Voltage/current measurement tool",
}


def _generic_component_description(definition: dict) -> str:
    specs = definition.get("specifications") or {}
    item_type = str(specs.get("type") or "").strip().lower()
    base = GENERIC_COMPONENT_TYPE_DESCRIPTIONS.get(item_type)
    if not base:
        category = str(definition.get("category") or "").strip()
        return f"General-purpose {category.lower()} component." if category else ""

    qualifiers = []
    for key in ("value", "resolution", "interface", "voltage", "output", "power", "channels", "capacity", "size"):
        value = specs.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "interface":
            qualifiers.append(f"{value} interface")
        elif key == "channels":
            qualifiers.append(f"{value} channels")
        else:
            qualifiers.append(str(value))

    if qualifiers:
        return f"{base} with {', '.join(qualifiers[:3])}."
    return base + "."


def _merge_missing(target: dict, incoming: dict) -> dict:
    out = deepcopy(target)
    for key, value in incoming.items():
        if key == "specifications":
            specs = dict(out.get("specifications") or {})
            for spec_key, spec_value in (value or {}).items():
                if specs.get(spec_key) in (None, "", [], {}):
                    specs[spec_key] = deepcopy(spec_value)
            out["specifications"] = specs
        elif out.get(key) in (None, "", [], {}):
            out[key] = deepcopy(value)
    return out


def _profile_key(definition: dict) -> str:
    family = str(definition.get("family") or "").strip()
    mcu = str(definition.get("mcu") or "").strip()
    for candidate in (family, mcu):
        if candidate in MCU_PROFILES:
            return candidate
    for candidate in (family, mcu):
        upper = candidate.upper()
        for key in sorted(MCU_PROFILES, key=len, reverse=True):
            if key.upper() in upper:
                return key
    return ""


def apply_board_profile(definition: dict) -> dict:
    enriched = deepcopy(definition)
    # Exact board facts are more specific than MCU capabilities, so apply them
    # first. The generic MCU profile only fills fields still missing afterwards.
    key = (enriched.get("manufacturer", ""), enriched.get("name", ""))
    if key in BOARD_PROFILES:
        enriched = _merge_missing(enriched, BOARD_PROFILES[key])
    profile_key = _profile_key(enriched)
    if profile_key:
        enriched = _merge_missing(enriched, MCU_PROFILES[profile_key])
    return enriched


def apply_component_profile(definition: dict) -> dict:
    enriched = deepcopy(definition)
    part = str(enriched.get("part_number") or "").strip()
    if part and part in COMPONENT_PART_PROFILES:
        profile = COMPONENT_PART_PROFILES[part]
        enriched = _merge_missing(enriched, {"specifications": profile})
        if not str(enriched.get("description") or "").strip() and profile.get("function"):
            enriched["description"] = str(profile["function"]).strip().rstrip(".") + "."
    if not str(enriched.get("description") or "").strip():
        enriched["description"] = _generic_component_description(enriched)
    return enriched
