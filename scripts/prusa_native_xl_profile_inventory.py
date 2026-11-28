"""Read exact pinned Prusa 2.9.7 XL toolhead presets before attempting slicing.

Unlike an MMU's five logical material slots, XL multi-toolheads have
independent physical hotends and require separate hardware/toolchange audits.
"""
from pathlib import Path
import hashlib
import sys

from slicer_worker.prusa_vendor_profiles import (
    parse_prusa_vendor_bundle, flatten_prusa_vendor_preset,
    validate_flat_prusa_preset,
)

def main(source):
    raw = Path(source).read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    names = [key.split(":",1)[1] for key in parse_prusa_vendor_bundle(raw)
             if key.startswith("printer:") and
             "xl" in key.split(":",1)[1].lower() and
             not key.split(":",1)[1].startswith("*")]
    print("Prusa 2.9.7 pinned XL native printer sections",len(names))
    accepted = []
    for name in names:
        try:
            options = validate_flat_prusa_preset(
                flatten_prusa_vendor_preset(raw,kind="printer",name=name,
                                            expected_sha256=checksum),
                kind="printer")
        except ValueError as error:
            print("UNRESOLVED XL",repr(name),str(error))
            continue
        tools = options["nozzle_diameter"].split(",")
        if not 1 <= len(tools) <= 8:
            raise ValueError("Native XL toolhead count outside supported bounds.")
        entry = {"name":name,"logical_nozzles":len(tools),
                 "single_extruder_multi_material":options.get(
                     "single_extruder_multi_material","0"),
                 "gcode_flavor":options.get("gcode_flavor"),
                 "binary_gcode":options.get("binary_gcode","0")}
        accepted.append(entry)
        print("CANDIDATE XL",entry)
    if not names:
        raise ValueError("Pinned Prusa source has no XL printer profile.")
    if not any(p["logical_nozzles"] > 1 and
               p["single_extruder_multi_material"]=="0" for p in accepted):
        print("NOT YET QUALIFIED: independent multi-toolhead profiles may require safe BG-code conversion.")
    print("PASS: read-only exact-version Prusa XL printer topology inventory.")

if __name__=="__main__":
    main(sys.argv[1])
