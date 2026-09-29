PRINTER_CATALOGUE = [
    {
        "manufacturer": "Creality",
        "website": "https://www.creality.com/",
        "models": [
            {"name": "K1", "build_volume": [220, 220, 250], "nozzle_mm": 0.4, "max_nozzle_temp_c": 300, "enclosed": True, "source_url": "https://www.creality.com/products/creality-k1-speedy-3d-printer"},
            {"name": "K1C", "build_volume": [220, 220, 250], "nozzle_mm": 0.4, "max_nozzle_temp_c": 300, "enclosed": True, "source_url": "https://www.creality.com/products/k1c-carbon-3d-printer"},
            {"name": "K1 Max", "build_volume": [300, 300, 300], "nozzle_mm": 0.4, "max_nozzle_temp_c": 300, "enclosed": True, "source_url": "https://www.creality.com/products/creality-k1-max-3d-printer"},
            {"name": "K2", "build_volume": [260, 260, 260], "nozzle_mm": 0.4, "max_nozzle_temp_c": 300, "max_bed_temp_c": 100, "enclosed": True, "multi_material_system": "creality_cfs", "max_multi_material_units": 4, "features": {"wifi": True, "camera": True, "auto_leveling": True, "cfs": True, "official_image_url": "https://cdn.creality.com/ow/official/49e73ab6-9f1d-4a32-9438-dd4acff6f919.png", "official_image_source_page": "https://www.creality.com/products/k2-series", "official_image_source_provider": "Creality official", "official_image_multi_material_url": "https://cdn.shopify.com/s/files/1/0893/0603/8637/files/K2_Combo-_1.png?v=1762073455", "official_image_multi_material_source_page": "https://store.creality.com/products/creality-k2-combo-3d-printer", "official_image_multi_material_source_provider": "Creality official store"}, "source_url": "https://www.creality.com/campaigns/k2-series-buying-guide"},
            {"name": "K2 Pro", "build_volume": [300, 300, 300], "nozzle_mm": 0.4, "max_nozzle_temp_c": 300, "max_bed_temp_c": 110, "enclosed": False, "multi_material_system": "creality_cfs", "features": {"cfs": True, "auto_leveling": True}, "source_url": "https://www.creality.com/campaigns/k2-series-buying-guide"},
            {"name": "K2 Plus", "build_volume": [350, 350, 350], "nozzle_mm": 0.4, "max_nozzle_temp_c": 350, "max_bed_temp_c": 120, "enclosed": False, "multi_material_system": "creality_cfs", "features": {"cfs": True, "auto_leveling": True}, "source_url": "https://www.creality.com/campaigns/k2-series-buying-guide"},
        ],
    },
    {
        "manufacturer": "Bambu Lab",
        "website": "https://bambulab.com/",
        "models": [
            {"name": "X1 Carbon", "build_volume": [256, 256, 256], "nozzle_mm": 0.4, "max_nozzle_temp_c": 300, "enclosed": True, "multi_material_system": "bambu_ams", "features": {"ams": True, "camera": True, "auto_leveling": True}, "source_url": "https://uk.store.bambulab.com/products/x1-carbon"},
            {"name": "P1S", "build_volume": [256, 256, 256], "nozzle_mm": 0.4, "enclosed": True, "multi_material_system": "bambu_ams", "features": {"ams": True}, "source_url": "https://bambulab.com/en/p1"},
            {"name": "A1", "build_volume": [256, 256, 256], "nozzle_mm": 0.4, "enclosed": False, "multi_material_system": "bambu_ams", "features": {"ams_lite": True}, "source_url": "https://bambulab.com/en/a1"},
        ],
    },
    {
        "manufacturer": "ELEGOO",
        "website": "https://www.elegoo.com/",
        "models": [
            {"name": "Centauri", "build_volume": [256, 256, 256], "nozzle_mm": 0.4, "max_nozzle_temp_c": 320, "max_bed_temp_c": 100, "enclosed": False, "features": {"auto_leveling": True}, "source_url": "https://www.elegoo.com/en-gb/products/centauri"},
            {"name": "Centauri Carbon", "build_volume": [256, 256, 256], "nozzle_mm": 0.4, "max_nozzle_temp_c": 320, "enclosed": True, "features": {"camera": True, "auto_leveling": True, "carbon_fiber_ready": True}, "source_url": "https://www.elegoo.com/products/centauri-carbon"},
        ],
    },
    {
        "manufacturer": "QIDI",
        "website": "https://qidi3d.com/",
        "models": [
            {"name": "Plus4", "build_volume": [305, 305, 280], "nozzle_mm": 0.4, "max_nozzle_temp_c": 370, "max_bed_temp_c": 120, "enclosed": True, "multi_material_system": "qidi", "features": {"qidi_box": True, "heated_chamber": True, "camera": True}, "source_url": "https://qidi3d.com/pages/qidi-plus-4-techspecs"},
            {"name": "Plus5", "build_volume": [320, 320, 300], "nozzle_mm": 0.4, "max_nozzle_temp_c": 370, "enclosed": True, "multi_material_system": "qidi", "features": {"qidi_box": True, "heated_chamber": True}, "source_url": "https://qidi3d.com/"},
        ],
    },
    {
        "manufacturer": "Snapmaker",
        "website": "https://www.snapmaker.com/",
        "models": [
            {"name": "U1", "build_volume": [270, 270, 270], "nozzle_mm": 0.4, "max_nozzle_temp_c": 300, "max_bed_temp_c": 100, "enclosed": False, "multi_material_system": "snapmaker", "features": {"toolheads": 4, "multi_material": True}, "source_url": "https://www.snapmaker.com/en-US/snapmaker-u1/specs"},
        ],
    },
]


COMMON_FILAMENT_MATERIALS = [
    "PLA", "PLA+", "PLA-CF", "PETG", "PETG-CF", "ABS", "ASA", "TPU",
    "TPE", "PA", "PA-CF", "PA-GF", "PC", "PC-ABS", "PCTG", "PET",
    "PVA", "HIPS", "PP", "POM", "PEEK", "PEI", "PPS", "PPS-CF",
]
