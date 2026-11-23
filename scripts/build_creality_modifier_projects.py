"""Wrap verified modifier fixtures in Creality Print v7.3.1 native projects.

Diagnostic only. This uses the existing strict MakerVault Creality project
packager with official fully resolved K1 presets. No production slice approval.
"""
import argparse
import io
import zipfile
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from core.slicer_creality_project import build_creality_project_candidate


def _remove_unresolvable_assembly_entries(project):
    """Diagnostic variant for component-parent 3MFs only.

    Pinned Creality v7.3.1 bbs_3mf.cpp reports 'can not find object
    for assemble item' before it can load the nested modifier when
    the native packager adds standard assemble_item records. The
    synthetic reference is not a desktop-saved assembly. Test its
    loader behaviour without this optional section, without modifying
    the actual 3D model, plate mapping, or modifier part records.
    """
    with zipfile.ZipFile(io.BytesIO(project)) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    key = "Metadata/model_settings.config"
    root = SafeET.fromstring(members[key])
    assembly = root.find("assemble")
    if assembly is None or len(assembly) != 1:
        raise ValueError("Expected one native synthetic assembly entry.")
    root.remove(assembly)
    members[key] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         allowZip64=False) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return output.getvalue()


def prepare(fixtures):
    directory = Path(fixtures)
    printer = (directory / "printer.json").read_bytes()
    process = (directory / "process.json").read_bytes()
    filament = (directory / "filament.json").read_bytes()
    output = []
    for label in ("baseline", "modified", "lower", "both"):
        src = directory / (label + ".3mf")
        dest = directory / ("native-" + label + ".3mf")
        if src.is_symlink() or not src.is_file() or dest.exists() or dest.is_symlink():
            raise ValueError("Invalid Creality modifier project fixture source or output.")
        project = build_creality_project_candidate(
            src.read_bytes(), printer=printer, process=process,
            filaments=[filament, filament], version="7.3.1",
            bed_width=220, bed_depth=220,
            # The generic tower collision helper examines direct meshes;
            # nested 3MF modifiers use a component parent. Use a fixed, valid
            # test-only rear corner, with the actual CLI as acceptance gate.
            prime_tower={"x": 170, "y": 170},
        )
        # Keep this strictly in the disposable Creality trial; production
        # native project packaging is not changed or approved.
        dest.write_bytes(_remove_unresolvable_assembly_entries(project))
        output.append(dest.name)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    print("Built test-only Creality native modifier projects:", ", ".join(prepare(args.fixtures)))


if __name__ == "__main__":
    main()
