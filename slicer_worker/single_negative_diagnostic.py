"""Diagnostic only: compare Bambu single-model negative subtraction against a plain cube.

No production feature approvals, image publishing, deployment, or printer I/O.
The independent two-model composite test remains the required acceptance gate.
"""
import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from .bambu_runner import run_bambu
from .composite_acceptance_probe import two_model_region_extrusion
from .runner import WorkerError
from .three_mf_validation import validate_worker_3mf
from .modifier_acceptance_probe import _COMMAND, _WORDS
import zipfile
from xml.etree import ElementTree as ET



def _native_part_bounds(sliced_3mf):
    """Inspect Bambu's external object meshes and component transforms.

    Bambu's sliced 3MF can store actual geometry in 3D/Objects/*.model,
    leaving 3D/3dmodel.model with only references. Inspect all bounded native
    model members rather than mistakenly reporting that no meshes exist.
    """
    namespace = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    summary = []
    with zipfile.ZipFile(sliced_3mf) as archive:
        names = [name for name in archive.namelist()
                 if name.startswith("3D/") and name.endswith(".model")]
        for name in names[:24]:
            info = archive.getinfo(name)
            if not 0 < info.file_size <= 16 * 1024 * 1024:
                summary.append({"member": name, "note": "Model member exceeds diagnostic limit"})
                continue
            payload = archive.read(info)
            if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
                raise ValueError("Diagnostic mesh XML may not contain custom entities.")
            root = ET.fromstring(payload)
            for obj in root.findall("./" + namespace + "resources/" + namespace + "object"):
                vertices = obj.findall("./" + namespace + "mesh/" + namespace + "vertices/" + namespace + "vertex")
                parts = obj.findall("./" + namespace + "components/" + namespace + "component")
                desc = {"member": name, "id": obj.get("id")}
                if vertices:
                    points = [[float(v.get(key)) for key in ("x", "y", "z")] for v in vertices]
                    desc["mesh_bounds"] = [
                        [round(min(v[axis] for v in points), 3),
                         round(max(v[axis] for v in points), 3)] for axis in range(3)]
                if parts:
                    desc["components"] = [dict(part.attrib) for part in parts[:16]]
                summary.append(desc)
            if name == "3D/3dmodel.model":
                summary.append({"member": name, "build": [
                    dict(item.attrib) for item in root.findall(
                        "./" + namespace + "build/" + namespace + "item")[:16]]})
    return summary[:40]


def _cavity_y_bands(gcode):
    """Diagnostic extrusion histogram through the middle of the true cut.

    Tracks valid positive-E moves with X midpoints 122..138 and Z 12..18;
    2-mm Y bands distinguish cavity walls from actual interior deposition.
    Does NOT grant native execution approval.
    """
    x = y = z = e = 0.
    relative_xyz = relative_e = False
    results = {}
    feature = "unknown"
    for raw in gcode.decode("utf-8", "replace").splitlines():
        text = raw.strip()
        if text.startswith(("; FEATURE:", ";TYPE:", "; TYPE:")):
            feature = text.split(":", 1)[1].strip()[:40]
        line = raw.partition(";")[0].strip().upper()
        command = _COMMAND.match(line)
        if not command:
            continue
        op = command.group(1)
        if op in ("M82", "M83"):
            relative_e = op == "M83"
            continue
        if op in ("G90", "G91"):
            relative_xyz = op == "G91"
            continue
        words = {axis: float(value) for axis, value in _WORDS.findall(line)}
        if op == "G92":
            x, y, z, e = (words.get("X", x), words.get("Y", y),
                          words.get("Z", z), words.get("E", e))
            continue
        nx = x + words["X"] if relative_xyz and "X" in words else words.get("X", x)
        ny = y + words["Y"] if relative_xyz and "Y" in words else words.get("Y", y)
        nz = z + words["Z"] if relative_xyz and "Z" in words else words.get("Z", z)
        deposited = 0.
        if "E" in words:
            deposited = words["E"] if relative_e else words["E"] - e
            if not relative_e:
                e = words["E"]
        if (op in ("G1", "G01") and deposited > 0 and
                122 < (x + nx) / 2 < 138 and 12 <= nz <= 18):
            cy = (y + ny) / 2
            if 94 <= cy < 126:
                band = "%03d" % (94 + 2 * int((cy - 94) // 2))
                item = results.setdefault(band, {"E": 0., "count": 0, "features": {}})
                item["E"] += deposited
                item["count"] += 1
                item["features"][feature] = item["features"].get(feature, 0.) + deposited
        x, y, z = nx, ny, nz
    return {key: {"E": round(value["E"], 3),
                  "count": value["count"],
                  "features": {name: round(v, 3) for name, v in value["features"].items()}}
            for key, value in sorted(results.items())}


def diagnose(fixtures, binary):
    fixtures = Path(fixtures)
    output = {}
    for name in ("single-baseline", "single-negative"):
        model = (fixtures / (name + ".3mf")).read_bytes()
        # An ordinary baseline 3MF has no nested non-printing parts and
        # must pass the normal worker validator; only the negative fixture
        # is eligible for the strictly bounded composite-fixture validator.
        validate_worker_3mf(model, allow_native_modifier_fixture=(name == "single-negative"))
        with TemporaryDirectory(prefix="single-negative-proof-") as temp:
            root = Path(temp)
            for profile in ("printer.json", "process.json", "filament.json"):
                shutil.copyfile(fixtures / profile, root / profile)
            (root / "input.3mf").write_bytes(model)
            if name == "single-negative":
                (root / "native-modifier-project.marker").write_text("v1")
            result = run_bambu(Path(binary), root, timeout_seconds=180)
            if result.get("status") != "completed":
                raise WorkerError("Bambu single negative diagnostic failed to complete.")
            gcode = Path(result["gcode_path"]).read_bytes()
            output[name] = two_model_region_extrusion(gcode)
            print("Single model native negative diagnostic:", name,
                  json.dumps(output[name], sort_keys=True), flush=True)
            print("Single model Bambu native mesh bounds:", name,
                  json.dumps(_native_part_bounds(root / "bambu-sliced.3mf")), flush=True)
            print("Single model cavity Y-band deposition:", name,
                  json.dumps(_cavity_y_bands(gcode), sort_keys=True), flush=True)
    # The pinned Bambu CLI repositions a single imported model into the
    # right-hand sample. Choose the populated region rather than wrongly
    # reporting the zero-extrusion left-hand sample as the test result.
    region = max(("left", "right"),
                 key=lambda side: output["single-baseline"]["totals"][side])
    base = output["single-baseline"]["totals"][region]
    cut = output["single-negative"]["totals"][region]
    result = {"engine": "bambustudio", "sample_region": region, "baseline_e_mm": round(base, 4),
              "negative_e_mm": round(cut, 4),
              "subtraction_indicated": base > 0 and cut < base * 0.9,
              "note": "Diagnostic only; production gate remains closed."}
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    diagnose(args.fixtures, args.binary)


if __name__ == "__main__":
    main()
