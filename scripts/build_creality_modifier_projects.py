"""Wrap verified modifier fixtures in Creality Print v7.3.1 native projects.

Diagnostic only. This uses the existing strict MakerVault Creality project
packager with official fully resolved K1 presets. No production slice approval.
"""
import argparse
import io
import zipfile
from copy import deepcopy
import uuid
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


MODEL_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PRODUCTION_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _split_native_mesh_components(project, label):
    """Follow pinned Creality's genuine external-object project convention.

    The official v7.3.1 tests/engine_test/baseline/simple-box.3mf stores an
    object id=2 in the main model with p:path components pointing at meshes in
    3D/Objects/object_1.model, plus 3D/_rels/3dmodel.model.rels. All mesh
    positions are already baked; identity component/build transforms are kept.
    This changes *only* synthetic offline fixtures, never production export.
    """
    with zipfile.ZipFile(io.BytesIO(project)) as src:
        entries = {info.filename: src.read(info) for info in src.infolist()}
    prefix = "{" + MODEL_NS + "}"
    p_uuid = "{" + PRODUCTION_NS + "}UUID"
    p_path = "{" + PRODUCTION_NS + "}path"
    original = SafeET.fromstring(entries["3D/3dmodel.model"])
    resources = original.find(prefix + "resources")
    build = original.find(prefix + "build")
    if resources is None or build is None or len(build) != 1:
        raise ValueError("Expected one executable model for Creality native fixture.")
    models = resources.findall(prefix + "object")
    if not models or models[0].get("id") != "1":
        raise ValueError("Unexpected native Creality source object IDs.")
    parent = models[0]
    existing = parent.find(prefix + "components")
    if existing is None:
        mesh = parent.find(prefix + "mesh")
        if mesh is None or len(models) != 1:
            raise ValueError("Expected direct-mesh native control model.")
        source_objects = [deepcopy(parent)]
        parent.remove(mesh)
        components = ET.SubElement(parent, prefix + "components")
    else:
        ids = [node.get("objectid") for node in existing]
        lookup = {node.get("id"): node for node in models[1:]}
        if len(ids) != len(set(ids)) or any(i not in lookup for i in ids):
            raise ValueError("Invalid native modifier source components.")
        source_objects = [deepcopy(lookup[i]) for i in ids]
        parent.remove(existing)
        components = ET.SubElement(parent, prefix + "components")
    if not 1 <= len(source_objects) <= 13:
        raise ValueError("Invalid Creality native child mesh count.")
    for node in models[1:]:
        resources.remove(node)
    parent.set("id", "2")
    parent.set(p_uuid, str(uuid.uuid5(uuid.NAMESPACE_URL, "creality-native-parent-" + label)))
    build[0].set("objectid", "2")
    build[0].set("printable", "1")
    build.set(p_uuid, str(uuid.uuid5(uuid.NAMESPACE_URL, "creality-build-" + label)))
    original.set("requiredextensions", "p")

    external = ET.Element(prefix + "model", {"unit": "millimeter", "requiredextensions": "p"})
    ext_resources = ET.SubElement(external, prefix + "resources")
    ET.SubElement(external, prefix + "build")
    for index, node in enumerate(source_objects, start=1):
        if node.find(prefix + "mesh") is None:
            raise ValueError("Nested Creality native modifier cannot contain sub-components.")
        node.set("id", str(index))
        node.set(p_uuid, str(uuid.uuid5(uuid.NAMESPACE_URL,
                                       "creality-external-%s-%d" % (label,index))))
        ext_resources.append(node)
        ET.SubElement(components, prefix + "component", {
            "objectid": str(index),
            p_path: "/3D/Objects/object_1.model",
            "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
        })

    config = SafeET.fromstring(entries["Metadata/model_settings.config"])
    objects = config.findall("object")
    if len(objects) != 1 or objects[0].get("id") != "1":
        raise ValueError("Creality metadata must target exactly one built object.")
    objects[0].set("id", "2")
    # Creality's actual simple-box native 3MF explicitly assigns its built
    # object to nozzle/filament 1. Omitting this mapping can pass 3MF import
    # but reach Flow::resolve_flow_nozzle_index with filament_id=0, producing
    # "Filament nozzle mapping is incomplete" even for the plain baseline.
    extruder = objects[0].find("./metadata[@key='extruder']")
    if extruder is None:
        ET.SubElement(objects[0], "metadata", {"key": "extruder", "value": "1"})
    elif extruder.get("value") != "1":
        raise ValueError("Unsafe native Creality object filament assignment.")
    parts = objects[0].findall("part")
    if len(parts) != len(source_objects):
        raise ValueError("Native part-to-geometry mapping is incomplete.")
    for index, part in enumerate(parts, start=1):
        part.set("id", str(index))
        subtype = "normal_part" if index == 1 else "modifier_part"
        if part.get("subtype") != subtype:
            raise ValueError("Unsafe native modifier part subtype.")
    instances = config.findall("./plate/model_instance")
    if len(instances) != 1:
        raise ValueError("Unexpected multi-instance native Creality fixture.")
    ident = instances[0].find("./metadata[@key='object_id']")
    if ident is None or ident.get("value") != "1":
        raise ValueError("Unrecognised native Creality instance mapping.")
    ident.set("value", "2")
    if config.find("assemble") is not None:
        raise ValueError("Creality synthetic assembly must remain absent.")

    rel = ET.Element("{" + REL_NS + "}Relationships")
    ET.SubElement(rel, "{" + REL_NS + "}Relationship", {
        "Target": "/3D/Objects/object_1.model",
        "Id": "rel-1",
        "Type": "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel",
    })
    ET.register_namespace("", MODEL_NS)
    ET.register_namespace("p", PRODUCTION_NS)
    entries["3D/3dmodel.model"] = ET.tostring(original, encoding="utf-8", xml_declaration=True)
    entries["3D/Objects/object_1.model"] = ET.tostring(external, encoding="utf-8", xml_declaration=True)
    entries["Metadata/model_settings.config"] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
    ET.register_namespace("", REL_NS)
    entries["3D/_rels/3dmodel.model.rels"] = ET.tostring(rel, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         allowZip64=False) as dst:
        for name, data in entries.items():
            dst.writestr(name, data)
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
        dest.write_bytes(_split_native_mesh_components(
            _remove_unresolvable_assembly_entries(project), label))
        output.append(dest.name)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    print("Built test-only Creality native modifier projects:", ", ".join(prepare(args.fixtures)))


if __name__ == "__main__":
    main()
