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
    ("Raspberry Pi", "Raspberry Pi Pico"): {
        "flash_mb": 2,
        "gpio_count": 26,
        "dimensions_mm": {"length": 51, "width": 21},
        "specifications": {
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
            "adc_channels": 4,
            "input_voltage": "1.8–5.5 V DC",
            "pio_state_machines": 12,
            "reference_url": "https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html",
        },
    },
    ("Arduino", "Uno R3"): {
        "gpio_count": 14,
        "dimensions_mm": {"length": 68.6, "width": 53.4},
        "specifications": {
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
            "adc_channels": 16,
            "pwm_channels": 15,
            "uart_count": 4,
            "spi_count": 1,
            "i2c_count": 1,
            "input_voltage": "7–12 V recommended",
            "reference_url": "https://docs.arduino.cc/hardware/mega-2560/",
        },
    },
    ("Arduino", "Nano Every"): {
        "gpio_count": 20,
        "dimensions_mm": {"length": 45, "width": 18},
        "specifications": {
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
        "dimensions_mm": {"length": 68.6, "width": 53.3},
        "specifications": {
            "adc_channels": 12,
            "pwm_channels": 7,
            "uart_count": 1,
            "spi_count": 1,
            "i2c_count": 1,
            "reference_provider": "Arduino",
            "reference_url": "https://docs.arduino.cc/retired/boards/arduino-leonardo/",
        },
    },
    ("Arduino", "Micro"): {
        "ram_kb": 2.5,
        "gpio_count": 20,
        "dimensions_mm": {"length": 48, "width": 18},
        "specifications": {
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
}


COMPONENT_PART_PROFILES = {
    "BME280": {"i2c_addresses": ["0x76", "0x77"], "function": "Temperature, humidity and pressure sensor"},
    "BMP280": {"i2c_addresses": ["0x76", "0x77"], "function": "Temperature and barometric pressure sensor"},
    "SHT31": {"i2c_addresses": ["0x44", "0x45"], "function": "Digital temperature and humidity sensor"},
    "SHT40": {"i2c_addresses": ["0x44"], "function": "Digital temperature and humidity sensor"},
    "MPU6050": {"i2c_addresses": ["0x68", "0x69"], "function": "6-axis accelerometer and gyroscope"},
    "ADXL345": {"i2c_addresses": ["0x53", "0x1D"], "function": "3-axis digital accelerometer"},
    "VL53L0X": {"i2c_addresses": ["0x29"], "function": "Time-of-flight distance sensor"},
    "VL53L1X": {"i2c_addresses": ["0x29"], "function": "Long-range time-of-flight distance sensor"},
    "INA219": {"function": "High-side current, voltage and power monitor", "interface": "I2C"},
    "INA226": {"function": "Current, voltage and power monitor", "interface": "I2C"},
    "ADS1115": {"function": "4-channel 16-bit ADC", "resolution": "16-bit", "channels": 4},
    "W5500": {"function": "10/100 Ethernet controller with hardware TCP/IP", "interface": "SPI"},
    "MCP2515": {"function": "Standalone CAN controller", "interface": "SPI"},
    "MFRC522": {"function": "13.56 MHz RFID reader/writer", "frequency": "13.56 MHz"},
    "PN532": {"function": "13.56 MHz NFC controller", "frequency": "13.56 MHz"},
    "nRF24L01+": {"function": "2.4 GHz ISM-band transceiver", "frequency": "2.4 GHz"},
    "INMP441": {"function": "Digital MEMS microphone", "interface": "I2S"},
    "MAX98357A": {"function": "Mono Class-D I2S audio amplifier", "interface": "I2S"},
    "DS3231": {"function": "Temperature-compensated real-time clock", "interface": "I2C"},
    "PCA9685": {"function": "16-channel 12-bit PWM controller", "channels": 16, "resolution": "12-bit"},
    "TMC2209": {"function": "Silent stepper motor driver", "interface": "Step/Dir/UART"},
    "A4988": {"function": "Bipolar stepper motor driver", "interface": "Step/Dir"},
    "TP4056": {"function": "Single-cell Li-ion/LiPo linear charger", "charge_voltage": "4.2 V"},
    "WS2812B": {"function": "Individually addressable RGB LED", "protocol": "single-wire", "voltage": "5 V"},
    "GC9A01": {"function": "Round TFT LCD controller", "interface": "SPI", "resolution": "240x240"},
    "SSD1306": {"function": "Monochrome OLED display controller", "interface": "I2C/SPI"},
    "ILI9341": {"function": "TFT LCD display controller", "interface": "SPI/parallel"},
    "HC-SR04": {"function": "Ultrasonic ranging module", "typical_range": "2–400 cm"},
    "HC-SR501": {"function": "PIR motion detector module"},
    "LD2410B": {"function": "24 GHz mmWave presence sensor", "frequency": "24 GHz"},
}


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
        enriched = _merge_missing(enriched, {"specifications": COMPONENT_PART_PROFILES[part]})
    return enriched
