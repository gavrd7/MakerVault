"""Safe draft storage for variable-layer height bands (not native G-code).
Native Orca layer_height_profile data is different and needs a verified adapter.
"""
import math


def validate_variable_layer_profile(value):
    if not isinstance(value, dict) or set(value) != {"version", "bands"} or (
        type(value.get("version")) is not int or value["version"] != 1
    ):
        raise ValueError("Invalid variable layer profile.")
    bands = value["bands"]
    if not isinstance(bands, list) or len(bands)>80:
        raise ValueError("Too many variable layer ranges.")
    result = []
    for band in bands:
        if not isinstance(band, dict) or set(band)!={"from_mm", "to_mm", "layer_mm"}:
            raise ValueError("Invalid variable layer band.")
        if any(type(band[k]) not in (int,float) or not math.isfinite(band[k])
               for k in ("from_mm","to_mm","layer_mm")):
            raise ValueError("Invalid layer dimensions.")
        start,end,thickness = (band[k] for k in ("from_mm","to_mm","layer_mm"))
        if not 0<=start<end<=1000 or not .05<=thickness<=.5:
            raise ValueError("Variable layer band outside supported range.")
        result.append({"from_mm":round(float(start),3),
                       "to_mm":round(float(end),3),
                       "layer_mm":round(float(thickness),3)})
    result.sort(key=lambda row:row["from_mm"])
    if any(b["from_mm"] < a["to_mm"] for a,b in zip(result,result[1:])):
        raise ValueError("Variable layer ranges overlap.")
    return {"version":1,"bands":result}
