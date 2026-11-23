"""Controlled Creality 7.3.1 import matrix for public generated 3MF fixtures.

Runs the pinned CLI against four separate inputs and reports the first
failing stage. Diagnostic only: no user models, device access or uploads.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
import io

LABELS = ("baseline", "modified", "lower", "both")


def inspect_archive(path):
    blob = path.read_bytes()
    if not 0 < len(blob) <= 32 * 1024 * 1024:
        raise ValueError("Invalid native fixture size.")
    with zipfile.ZipFile(io.BytesIO(blob)) as project:
        names = project.namelist()
        if len(names) != len(set(names)) or len(names) > 8:
            raise ValueError("Unexpected archive member count or duplicates.")
        required = {"3D/3dmodel.model", "Metadata/model_settings.config"}
        if not required.issubset(names):
            raise ValueError("Missing native 3MF model metadata.")
        from defusedxml import ElementTree as ET
        model = ET.fromstring(project.read("3D/3dmodel.model"))
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        build = model.find(ns + "build")
        objects = model.find(ns + "resources")
        if build is None or objects is None or len(build) != 1:
            raise ValueError("Not a one-build-item test project.")
        settings = ET.fromstring(project.read("Metadata/model_settings.config"))
        return {
            "members": len(names),
            "objects": len(objects),
            "components": sum(len(obj.find(ns + "components"))
                              for obj in objects if obj.find(ns + "components") is not None),
            "parts": len(settings.findall("./object/part")),
            "assembly_items": len(settings.findall("./assemble/assemble_item")),
            "creality_sidecar": "Metadata/creality.config" in names,
        }


def run(binary, fixtures):
    root = Path(fixtures)
    results = []
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    for label in LABELS:
        for mode in ("generic", "native"):
            source = root / ((("native-" if mode == "native" else "") + label) + ".3mf")
            if source.is_symlink() or not source.is_file():
                raise ValueError("Creality import candidate missing: " + source.name)
            details = inspect_archive(source)
            with tempfile.TemporaryDirectory(prefix="creality-native-import-") as temp:
                output = Path(temp) / "output"
                command = [str(binary), "--cli", "--slice", "0",
                           "--outputdir", str(output), "--need-gcode-file", str(source)]
                try:
                    result = subprocess.run(command, cwd=temp, env=env,
                                            capture_output=True, text=True,
                                            timeout=150, check=False)
                    exit_code = result.returncode
                    lines = (result.stderr + "\n" + result.stdout).splitlines()
                    # Retain only fixed, public-fixture failure categories.
                    diagnostic = [
                        line[-220:] for line in lines
                        if any(term in line.lower() for term in
                               ("cannot", "can not", "error", "invalid", "failed",
                                "missing", "version", "read model"))]
                    diagnostic = diagnostic[-9:]
                except subprocess.TimeoutExpired:
                    exit_code, diagnostic = -999, ["CLI timed out"]
                print(label, mode, "exit", exit_code, "structure", details, flush=True)
                for line in diagnostic:
                    print("  detail:", line, flush=True)
                results.append((label, mode, exit_code, details))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    rows = run(args.binary, args.fixtures)
    generic = next(code for label, mode, code, _ in rows if label == "baseline" and mode == "generic")
    native = next(code for label, mode, code, _ in rows if label == "baseline" and mode == "native")
    print("Creality positive-control baseline generic exit:", generic, flush=True)
    print("Creality positive-control baseline native exit:", native, flush=True)
    if native != 0:
        print("BLOCKER: Native-project baseline fails even without modifier parts; "
              "investigate project packaging before assuming a modifier incompatibility.", flush=True)
    else:
        print("Native baseline parsed: compare modified native return code to isolate "
              "modifier-specific model/part import.", flush=True)


if __name__ == "__main__":
    main()
