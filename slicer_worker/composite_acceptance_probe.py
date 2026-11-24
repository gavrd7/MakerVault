"""Exact-binary, offline native two-model region and negative-volume acceptance.

Uses only disposable fixtures and the production worker validators. Does not
send to a printer, deploy, or grant production permission.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from .modifier_acceptance_probe import _COMMAND, _WORDS
from .orca_runner import run_orca
from .bambu_runner import run_bambu
from .creality_runner import run_creality
from .runner import WorkerError
from .three_mf_validation import validate_worker_3mf
from .creality_modifier_validation import validate_creality_modifier_project


def two_model_region_extrusion(gcode):
    x = y = z = e = 0.0
    relative_xyz = relative_e = False
    totals = {"left":0.0,"right":0.0}
    counts = {"left":0,"right":0}
    for raw in gcode.decode("utf-8", "replace").splitlines():
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
            if 12<=nz<=18 and 100<=cy<=120:
                label="left" if 78<=cx<=102 else "right" if 118<=cx<=142 else None
                if label:
                    totals[label]+=ex
                    counts[label]+=1
        x,y,z=nx,ny,nz
    return {"totals":totals,"counts":counts}


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
            results[name]=two_model_region_extrusion(gcode_path.read_bytes())
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
