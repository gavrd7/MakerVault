"""Exact-binary, offline native two-model region and negative-volume acceptance.

Uses only disposable fixtures and the production worker validators. Does not
send to a printer, deploy, or grant production permission.
"""
import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import shutil
import tempfile
import zipfile
from xml.etree import ElementTree as ET
from unittest.mock import patch

from .modifier_acceptance_probe import _COMMAND, _WORDS
from .orca_runner import run_orca
from .bambu_runner import run_bambu
from .creality_runner import run_creality
from .runner import WorkerError
from .three_mf_validation import validate_worker_3mf
from .creality_modifier_validation import validate_creality_modifier_project


def two_model_region_extrusion(gcode, *, shift_x=0.0, shift_y=0.0):
    x = y = z = e = 0.0
    relative_xyz = relative_e = False
    totals = {"left":0.0,"right":0.0}
    counts = {"left":0,"right":0}
    features = {"left": {}, "right": {}}
    feature = "unlabelled"
    for raw in gcode.decode("utf-8", "replace").splitlines():
        comment = raw.strip()
        if comment.startswith(("; FEATURE:", ";TYPE:", "; TYPE:")):
            feature = comment.split(":", 1)[1].strip()[:100]
        cmd = _COMMAND.match(raw.partition(";")[0].strip().upper())
        if not cmd:
            continue
        line=raw.partition(";")[0].strip().upper()
        op=cmd.group(1)
        if op in ("M82","M83"):
            relative_e=op=="M83"
            continue
        if op in ("G90","G91"):
            relative_xyz=op=="G91"
            continue
        words={axis:float(value) for axis,value in _WORDS.findall(line)}
        if op=="G92":
            x,y,z,e=(words.get("X",x),words.get("Y",y),words.get("Z",z),words.get("E",e))
            continue
        nx=x+words["X"] if relative_xyz and "X" in words else words.get("X",x)
        ny=y+words["Y"] if relative_xyz and "Y" in words else words.get("Y",y)
        nz=z+words["Z"] if relative_xyz and "Z" in words else words.get("Z",z)
        ex=0
        if "E" in words:
            ex=words["E"] if relative_e else words["E"]-e
            if not relative_e:
                e=words["E"]
        if op in ("G1","G01") and ex>0 and (nx!=x or ny!=y):
            cx=(nx+x)/2
            cy=(ny+y)/2
            # The negative fixture cuts Y=100..120. Real native slicing
            # legitimately deposits new perimeter walls at Y=100 and Y=120;
            # those are cavity boundaries, NOT unremoved material. Measure
            # a conservative 2 mm inset so only filled cavity interiors count.
            # Keep this same interior sample for baseline and changed fixtures.
            if 12<=nz<=18 and 102+shift_y<cy<118+shift_y:
                label=("left" if 78+shift_x<=cx<=102+shift_x
                       else "right" if 118+shift_x<=cx<=142+shift_x else None)
                if label:
                    totals[label]+=ex
                    counts[label]+=1
                    features[label][feature] = features[label].get(feature, 0.0) + ex
        x,y,z=nx,ny,nz
    return {"totals":totals,"counts":counts,"features":features}


def bambu_output_placement_shift(sliced_project):
    """Read only the bounded placement translation from Bambu's own output.

    MakerVault's disposable *composite* fixture has an identity build item.
    Bambu Studio may recenter the entire assembly onto its native printer bed
    while retaining all part roles. Comparing G-code against the original
    220-mm fixture coordinates would measure material *outside* the cutter.
    Do not alter the actual 3MF or allow arbitrary transforms as a workaround.
    """
    namespace = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    with zipfile.ZipFile(sliced_project) as archive:
        info = archive.getinfo("3D/3dmodel.model")
        if not 0 < info.file_size <= 1024 * 1024:
            raise WorkerError("Bambu output placement XML is too large.")
        payload = archive.read(info)
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise WorkerError("Unsafe Bambu output placement XML.")
    root = ET.fromstring(payload)
    items = root.findall("./" + namespace + "build/" + namespace + "item")
    if len(items) != 1:
        raise WorkerError("Bambu output must keep one native composite build item.")
    try:
        values = [float(value) for value in items[0].attrib["transform"].split()]
    except (KeyError, ValueError):
        raise WorkerError("Bambu output has no usable native placement.") from None
    if (len(values) != 12 or any(not math.isfinite(v) for v in values)
            or any(abs(values[i] - (1.0 if i in (0, 4, 8) else 0.0)) > 0.0001
                   for i in range(9))
            or not all(-256 <= values[i] <= 256 for i in (9, 10))
            or abs(values[11]) > 0.001):
        raise WorkerError("Bambu output applied an unexpected native geometry transform.")
    return values[9], values[10]


def probe(fixtures,binary,engine,creality_native=False):
    runners={"orcaslicer":run_orca,"bambustudio":run_bambu,"crealityprint":run_creality}
    if engine not in runners:
        raise WorkerError("Unknown native region engine.")
    if (engine=="crealityprint")!=creality_native:
        raise WorkerError("Creality requires its reviewed native project wrapper.")
    fixtures=Path(fixtures)
    results={}
    for name in ("baseline","region","negative"):
        source=(fixtures/(name+".3mf")).read_bytes()
        validate_worker_3mf(source,allow_native_modifier_fixture=True)
        with tempfile.TemporaryDirectory(prefix="composite-native-proof-") as temp:
            root=Path(temp)
            for profile in ("printer.json","filament.json","process.json"):
                shutil.copyfile(fixtures/profile,root/profile)
            if creality_native:
                project=(fixtures/("native-"+name+".3mf")).read_bytes()
                validate_creality_modifier_project(project)
            else:
                project=source
            (root/"input.3mf").write_bytes(project)
            (root/"native-modifier-project.marker").write_text("v1")
            results[name]=runners[engine](Path(binary),root,timeout_seconds=180)
            if results[name].get("status")!="completed":
                raise WorkerError("Native composite CLI did not complete "+name)
            gcode_path=Path(results[name]["gcode_path"])
            if gcode_path.resolve().parent != root.resolve() or not gcode_path.is_file():
                raise WorkerError("Native CLI returned unsafe composite G-code output.")
            shift = (0.0, 0.0)
            if engine == "bambustudio":
                shift = bambu_output_placement_shift(root / "bambu-sliced.3mf")
            if engine == "bambustudio":
                # Exercise the exact production geometry audit against the
                # pinned binary's real G-code and native output placement.
                # A passing comparative regional check must not mask
                # interior extrusion inside a negative-part mesh.
                from .bambu_runner import verified_bambu_modifier_shift
                from .modifier_gcode_audit import audit_modifier_positive_e
                verified_shift = verified_bambu_modifier_shift(
                    project, root / "bambu-sliced.3mf")
                if any(abs(a - b) > 0.0001
                       for a, b in zip(shift, verified_shift)):
                    raise WorkerError("Bambu native fixture placement is inconsistent.")
                audit_modifier_positive_e(
                    gcode_path.read_bytes(), project, engine,
                    translation_xy=verified_shift)
            results[name]=two_model_region_extrusion(
                gcode_path.read_bytes(), shift_x=shift[0], shift_y=shift[1])
            if engine == "bambustudio":
                results[name]["native_output_shift_xy"] = [
                    round(shift[0], 4), round(shift[1], 4)]
            # Inspect only part roles from the disposable native output, not
            # arbitrary archive contents. This separates importer loss from
            # subsequent slicing or measurement errors.
            if engine == "bambustudio":
                with zipfile.ZipFile(root / "bambu-sliced.3mf") as archive:
                    member = "Metadata/model_settings.config"
                    if member in archive.namelist() and archive.getinfo(member).file_size <= 1024 * 1024:
                        payload = archive.read(member)
                        if b"<!DOCTYPE" not in payload.upper() and b"<!ENTITY" not in payload.upper():
                            config = ET.fromstring(payload)
                            results[name]["output_part_roles"] = [p.get("subtype") for p in config.findall("./object/part")]
            print("Native composite evidence:", name, json.dumps(results[name], sort_keys=True), flush=True)
    for region in ("left","right"):
        base=results["baseline"]["totals"][region]
        added=results["region"]["totals"][region]
        cut=results["negative"]["totals"][region]
        # A successful negative volume may remove EVERY path in the region.
        # Requiring deposition in the negative case would reject the strongest
        # possible subtraction evidence (zero positive-E paths).
        if (results["baseline"]["counts"][region] < 5 or
                results["region"]["counts"][region] < 5):
            raise WorkerError("Insufficient printable baseline or modifier paths in "+region)
        if base<=0 or added<=base*1.08:
            raise WorkerError(
                "Independent modifier has no proven regional effect in %s "
                "(baseline=%.3f changed=%.3f)" % (region,base,added))
        if cut>=base*.9:
            raise WorkerError(
                "Native negative volume did not remove material in %s "
                "(baseline=%.3f with_negative=%.3f, threshold=%.3f)" %
                (region,base,cut,base*.9))
    return {"status":"passed","engine":engine,"evidence":results}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures",type=Path,required=True)
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--engine",choices=("orcaslicer","bambustudio","crealityprint"),required=True)
    parser.add_argument("--creality-native-project",action="store_true")
    args=parser.parse_args()
    try:
        print(json.dumps(probe(args.fixtures,args.binary,args.engine,args.creality_native_project),indent=2))
    except (WorkerError,OSError,ValueError) as exc:
        parser.exit(1,"Composite native real-binary acceptance failed: "+str(exc)+"\n")


if __name__=="__main__":
    main()
