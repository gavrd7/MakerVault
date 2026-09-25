from django.core.management.base import BaseCommand
from django.utils.text import slugify

from core.models import (
    BoardCompatibility,
    BoardModel,
    CatalogSource,
    ComponentCategory,
    ComponentModel,
    Manufacturer,
)


BOARDS = [
    {"manufacturer":"Espressif","name":"ESP32-DevKitC","family":"ESP32","mcu":"ESP32","architecture":"Xtensa","flash_mb":4,"ram_kb":520,"wifi":True,"bluetooth":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Espressif","name":"ESP32-S2-DevKitC-1","family":"ESP32-S2","mcu":"ESP32-S2","architecture":"Xtensa","wifi":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Espressif","name":"ESP32-S3-DevKitC-1","family":"ESP32-S3","mcu":"ESP32-S3","architecture":"Xtensa","wifi":True,"bluetooth":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Espressif","name":"ESP32-C3-DevKitM-1","family":"ESP32-C3","mcu":"ESP32-C3","architecture":"RISC-V","wifi":True,"bluetooth":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Espressif","name":"ESP32-C6-DevKitC-1","family":"ESP32-C6","mcu":"ESP32-C6","architecture":"RISC-V","wifi":True,"bluetooth":True,"zigbee":True,"thread":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Espressif","name":"ESP32-H2-DevKitM-1","family":"ESP32-H2","mcu":"ESP32-H2","architecture":"RISC-V","bluetooth":True,"zigbee":True,"thread":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Espressif","name":"ESP32-P4-Function-EV-Board","family":"ESP32-P4","mcu":"ESP32-P4","architecture":"RISC-V","usb_connector":"USB-C","compat":["ESP-IDF"]},
    {"manufacturer":"Generic","name":"ESP8266 NodeMCU","family":"ESP8266","mcu":"ESP8266","architecture":"Xtensa","wifi":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Generic","name":"Wemos D1 Mini (ESP8266)","family":"ESP8266","mcu":"ESP8266","architecture":"Xtensa","wifi":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Generic","name":"ESP32-CAM AI-Thinker style","family":"ESP32","mcu":"ESP32","architecture":"Xtensa","wifi":True,"bluetooth":True,"compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Generic","name":"ESP32 C3 Super Mini","family":"ESP32-C3","mcu":"ESP32-C3","architecture":"RISC-V","flash_mb":4,"ram_kb":400,"gpio_count":13,"wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Generic","name":"ESP32-S3 Super Mini","family":"ESP32-S3","mcu":"ESP32-S3","architecture":"Xtensa","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Generic","name":"ESP32-C6 Super Mini","family":"ESP32-C6","mcu":"ESP32-C6","architecture":"RISC-V","wifi":True,"bluetooth":True,"zigbee":True,"thread":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Generic","name":"ESP32-H2 Super Mini","family":"ESP32-H2","mcu":"ESP32-H2","architecture":"RISC-V","bluetooth":True,"zigbee":True,"thread":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi Zero","family":"Raspberry Pi Zero","mcu":"BCM2835"},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi Zero W","family":"Raspberry Pi Zero","mcu":"BCM2835","wifi":True,"bluetooth":True},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi Zero 2 W","family":"Raspberry Pi Zero","mcu":"BCM2710A1","wifi":True,"bluetooth":True},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi 3 Model B+","family":"Raspberry Pi","mcu":"BCM2837B0","wifi":True,"bluetooth":True},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi 4 Model B","family":"Raspberry Pi","mcu":"BCM2711","wifi":True,"bluetooth":True,"usb_connector":"USB-C"},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi 5","family":"Raspberry Pi","mcu":"BCM2712","wifi":True,"bluetooth":True,"usb_connector":"USB-C"},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi Pico","family":"RP2040","mcu":"RP2040","architecture":"ARM Cortex-M0+","usb_connector":"Micro-USB","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi Pico W","family":"RP2040","mcu":"RP2040","architecture":"ARM Cortex-M0+","wifi":True,"bluetooth":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi Pico 2","family":"RP2350","mcu":"RP2350","architecture":"ARM Cortex-M33 / RISC-V","usb_connector":"Micro-USB","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Raspberry Pi","name":"Raspberry Pi Pico 2 W","family":"RP2350","mcu":"RP2350","architecture":"ARM Cortex-M33 / RISC-V","wifi":True,"bluetooth":True,"usb_connector":"Micro-USB","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Arduino","name":"Uno R3","family":"AVR","mcu":"ATmega328P","architecture":"AVR","usb_connector":"USB-B","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Arduino","name":"Uno R4 Minima","family":"Renesas RA4M1","mcu":"RA4M1","architecture":"ARM Cortex-M4","usb_connector":"USB-C","compat":["Arduino"]},
    {"manufacturer":"Arduino","name":"Uno R4 WiFi","family":"Renesas RA4M1","mcu":"RA4M1 + ESP32-S3","architecture":"ARM Cortex-M4","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino"]},
    {"manufacturer":"Arduino","name":"Nano","family":"AVR","mcu":"ATmega328P","architecture":"AVR","usb_connector":"Mini-USB","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Arduino","name":"Nano Every","family":"AVR","mcu":"ATmega4809","architecture":"AVR","usb_connector":"Micro-USB","compat":["Arduino"]},
    {"manufacturer":"Arduino","name":"Nano 33 IoT","family":"SAMD21","mcu":"SAMD21","architecture":"ARM Cortex-M0+","wifi":True,"bluetooth":True,"usb_connector":"Micro-USB","compat":["Arduino"]},
    {"manufacturer":"Arduino","name":"Nano RP2040 Connect","family":"RP2040","mcu":"RP2040","architecture":"ARM Cortex-M0+","wifi":True,"bluetooth":True,"usb_connector":"Micro-USB","compat":["Arduino"]},
    {"manufacturer":"Arduino","name":"Nano ESP32","family":"ESP32-S3","mcu":"ESP32-S3","architecture":"Xtensa","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","ESPHome"]},
    {"manufacturer":"Arduino","name":"Mega 2560 Rev3","family":"AVR","mcu":"ATmega2560","architecture":"AVR","usb_connector":"USB-B","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Arduino","name":"Leonardo","family":"AVR","mcu":"ATmega32U4","architecture":"AVR","usb_connector":"Micro-USB","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Arduino","name":"Micro","family":"AVR","mcu":"ATmega32U4","architecture":"AVR","usb_connector":"Micro-USB","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Seeed Studio","name":"XIAO ESP32C3","family":"ESP32-C3","mcu":"ESP32-C3","architecture":"RISC-V","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Seeed Studio","name":"XIAO ESP32C6","family":"ESP32-C6","mcu":"ESP32-C6","architecture":"RISC-V","wifi":True,"bluetooth":True,"zigbee":True,"thread":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Seeed Studio","name":"XIAO ESP32S3","family":"ESP32-S3","mcu":"ESP32-S3","architecture":"Xtensa","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Seeed Studio","name":"XIAO RP2040","family":"RP2040","mcu":"RP2040","architecture":"ARM Cortex-M0+","usb_connector":"USB-C","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"Seeed Studio","name":"XIAO RP2350","family":"RP2350","mcu":"RP2350","architecture":"ARM Cortex-M33 / RISC-V","usb_connector":"USB-C","compat":["Arduino"]},
    {"manufacturer":"M5Stack","name":"Atom Lite","family":"ESP32","mcu":"ESP32-PICO-D4","architecture":"Xtensa","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"M5Stack","name":"Core2","family":"ESP32","mcu":"ESP32-D0WDQ6-V3","architecture":"Xtensa","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"M5Stack","name":"Stamp C3","family":"ESP32-C3","mcu":"ESP32-C3","architecture":"RISC-V","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Adafruit","name":"Feather ESP32-S3","family":"ESP32-S3","mcu":"ESP32-S3","architecture":"Xtensa","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Adafruit","name":"QT Py ESP32-C3","family":"ESP32-C3","mcu":"ESP32-C3","architecture":"RISC-V","wifi":True,"bluetooth":True,"usb_connector":"USB-C","compat":["Arduino","PlatformIO","ESPHome"]},
    {"manufacturer":"Adafruit","name":"Feather RP2040","family":"RP2040","mcu":"RP2040","architecture":"ARM Cortex-M0+","usb_connector":"USB-C","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"SparkFun","name":"Pro Micro RP2040","family":"RP2040","mcu":"RP2040","architecture":"ARM Cortex-M0+","usb_connector":"USB-C","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"PJRC","name":"Teensy 4.0","family":"Teensy","mcu":"i.MX RT1062","architecture":"ARM Cortex-M7","usb_connector":"Micro-USB","compat":["Arduino","PlatformIO"]},
    {"manufacturer":"PJRC","name":"Teensy 4.1","family":"Teensy","mcu":"i.MX RT1062","architecture":"ARM Cortex-M7","usb_connector":"Micro-USB","compat":["Arduino","PlatformIO"]},
]

COMPONENTS = [
    ("Passives", "Generic", "1/4W resistor assortment", "", {"type":"resistor"}),
    ("Passives", "Generic", "Ceramic capacitor assortment", "", {"type":"capacitor"}),
    ("LEDs & Lighting", "Generic", "5mm LED", "", {"package":"5mm through-hole"}),
    ("LEDs & Lighting", "Generic", "WS2812B addressable RGB LED", "WS2812B", {"protocol":"single-wire addressable"}),
    ("Displays", "Generic", "SSD1306 0.96in OLED 128x64 I2C", "SSD1306", {"interface":"I2C","resolution":"128x64"}),
    ("Displays", "Generic", "GC9A01 1.28in round TFT 240x240", "GC9A01", {"interface":"SPI","resolution":"240x240"}),
    ("Displays", "Generic", "ILI9341 2.4in TFT 320x240", "ILI9341", {"interface":"SPI","resolution":"320x240"}),
    ("Sensors", "Bosch", "BME280 temperature/humidity/pressure sensor", "BME280", {"interface":"I2C/SPI"}),
    ("Sensors", "Aosong", "DHT22 temperature/humidity sensor", "DHT22", {"interface":"single-wire"}),
    ("Sensors", "Generic", "HC-SR04 ultrasonic distance sensor", "HC-SR04", {}),
    ("Sensors", "Generic", "HC-SR501 PIR motion sensor", "HC-SR501", {}),
    ("Sensors", "STMicroelectronics", "VL53L0X time-of-flight distance sensor", "VL53L0X", {"interface":"I2C"}),
    ("Audio", "Generic", "INMP441 I2S MEMS microphone module", "INMP441", {"interface":"I2S"}),
    ("Audio", "Generic", "NS4168 I2S amplifier module", "NS4168", {"interface":"I2S"}),
    ("Audio", "Analog Devices", "MAX98357A I2S amplifier module", "MAX98357A", {"interface":"I2S"}),
    ("Controls", "Generic", "EC11 rotary encoder", "EC11", {}),
    ("Controls", "Generic", "Momentary push button", "", {}),
    ("Controls", "Generic", "10k potentiometer", "", {"resistance":"10k"}),
    ("Power", "Generic", "LM2596 adjustable buck converter module", "LM2596", {}),
    ("Power", "Generic", "Logic-level MOSFET module", "", {}),
    ("Relays", "Generic", "5V single-channel relay module", "", {}),
    ("Prototyping", "Generic", "830-point solderless breadboard", "", {}),
    ("Connectors", "Generic", "Dupont jumper wire set", "", {}),
    ("Connectors", "Generic", "JST-XH connector kit", "JST-XH", {}),
    ("Storage", "Generic", "MicroSD SPI module", "", {"interface":"SPI"}),
    ("Timing", "Maxim / Analog Devices", "DS3231 RTC module", "DS3231", {"interface":"I2C"}),
    ("Motors & Drivers", "Generic", "SG90 9g micro servo", "SG90", {}),
    ("Motors & Drivers", "Allegro", "A4988 stepper motor driver module", "A4988", {}),
]


class Command(BaseCommand):
    help = "Seed MakerVault's idempotent starter board/component catalogue."

    def handle(self, *args, **options):
        source, _ = CatalogSource.objects.get_or_create(
            name="MakerVault starter catalogue",
            source_type="manual",
            defaults={"raw_metadata": {"managed_by": "seed_catalogue"}},
        )

        board_created = 0
        compatibility_created = 0
        for definition in BOARDS:
            maker, _ = Manufacturer.objects.get_or_create(name=definition["manufacturer"])
            defaults = {
                key: value
                for key, value in definition.items()
                if key not in {"manufacturer", "name", "compat"}
            }
            defaults["source"] = source
            defaults.setdefault("specifications", {})
            defaults["specifications"] = {**defaults["specifications"], "starter_catalogue": True}
            board, created = BoardModel.objects.get_or_create(
                manufacturer=maker,
                name=definition["name"],
                variant="",
                defaults=defaults,
            )
            board_created += int(created)
            for platform in definition.get("compat", []):
                _, compat_created = BoardCompatibility.objects.get_or_create(
                    board=board,
                    platform=platform,
                    defaults={"support_level": "full"},
                )
                compatibility_created += int(compat_created)

        categories = {}
        for category_name, *_ in COMPONENTS:
            category, _ = ComponentCategory.objects.get_or_create(
                slug=slugify(category_name),
                defaults={"name": category_name},
            )
            categories[category_name] = category

        component_created = 0
        for category_name, manufacturer_name, name, part_number, specs in COMPONENTS:
            maker, _ = Manufacturer.objects.get_or_create(name=manufacturer_name)
            _, created = ComponentModel.objects.get_or_create(
                manufacturer=maker,
                name=name,
                part_number=part_number,
                defaults={
                    "category": categories[category_name],
                    "source": source,
                    "specifications": {**specs, "starter_catalogue": True},
                },
            )
            component_created += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Starter catalogue ready: {board_created} boards, "
                f"{component_created} components, {compatibility_created} compatibility records added."
            )
        )
