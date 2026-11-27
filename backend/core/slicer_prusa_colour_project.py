"""Bounded Prusa 2.9.7 two-colour project encoder for offline qualification.

The worker independently validates the native 3MF against the selected
MMU/XL/INDX printer topology. Facet painting and object settings share the
native object config rather than inventing a separate painting UI.
"""
import io
import struct
import zipfile
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET

from .slicer_native_support_paint import native_combined_paint_triangles
from .slicer_plate_3mf import _triangles, NS
from .slicer_prusa_3mf import build_prusa_native_3mf
from .slicer_prusa_machine_topology import prusa_machine_topology
from .slicer_profiles import SlicerProfileError


def build_prusa_colour_candidate(item, source, *, printer_ini, colour_tool_indices,
                                 bed_width, bed_depth):
    topology = prusa_machine_topology(printer_ini)
    count = topology["logical_tool_count"]
    # Object-scoped MakerVault process controls already serialize to native
    # Prusa 3MF model.config. Validate the exact requested keys and values,
    # never drop the configuration when adding painted face metadata.
    from .slicer_prusa_3mf import OBJECT_KEYS, BASE
    from .slicer_prusa_process_settings import apply_prusa_process_overrides
    object_settings=item.get("process_overrides") if isinstance(item,dict) else None
    if object_settings is not None:
        if not isinstance(object_settings,dict) or set(object_settings)-OBJECT_KEYS:
            raise SlicerProfileError("Prusa painted model has unsupported Object controls.")
        try:
            apply_prusa_process_overrides(BASE,object_settings)
        except (ValueError,TypeError,OverflowError) as exc:
            raise SlicerProfileError("Invalid native Prusa painted Object setting.") from exc
    from .slicer_modifier_volumes import validate_modifier_volumes
    try:
        typed=validate_modifier_volumes(
            item.get("modifier_volumes") if isinstance(item,dict) else None)
    except (ValueError,TypeError) as exc:
        raise SlicerProfileError("Invalid painted native modifier geometry.") from exc
    if typed and (len(typed)!=1 or typed[0]["kind"]!="modifier" or
                  typed[0]["shape"]!="box" or
                  set(typed[0]["settings"])!={"sparse_infill_density"}):
        raise SlicerProfileError(
            "This Prusa painted/modifier pairing requires one native box infill region.")
    if (not 2 <= count <= 8 or not isinstance(item, dict)
            or not isinstance(source, bytes)
            or not isinstance(colour_tool_indices, dict)
            or not colour_tool_indices
            or any(type(k) is not int or type(v) is not int or not 1 <= v <= 7 or not v < count
                   for k,v in colour_tool_indices.items())
            or any(item.get(k) for k in ("negative_volumes",
                   "variable_layer_profile","support_paint",
                   "seam_paint","fuzzy_skin_paint","material_slot"))):
        raise SlicerProfileError("Unsupported Prusa native colour candidate.")
    paint = item.get("colour_paint")
    if not isinstance(paint,dict) or not paint.get("regions"):
        raise SlicerProfileError("Prusa native colour candidate requires facet regions.")
    painted = native_combined_paint_triangles(
        list(_triangles(source)), colour=paint, colour_tool_indices=colour_tool_indices)
    raw = bytearray(b"MakerVault Prusa native colour facets".ljust(80,b"\0"))
    raw.extend(struct.pack("<I",len(painted)))
    states = []
    for triangle,tags in painted:
        raw.extend(struct.pack("<12fH",0,0,0,
                   *(float(n) for vertex in triangle for n in vertex),0))
        state = tags.get("paint_color")
        accepted = {"4", "8", "0C", "1C", "2C", "3C", "4C", "5C"}
        if state is not None and state not in accepted:
            raise SlicerProfileError("Unqualified Prusa native colour state.")
        states.append(state)
    if not any(state not in (None, "4") for state in states):
        raise SlicerProfileError("Prusa colour candidate needs second-tool facets.")
    row = dict(item)
    row.pop("colour_paint")
    project = build_prusa_native_3mf([(row,bytes(raw))],
                                     bed_width=bed_width,bed_depth=bed_depth)
    m = "{"+NS+"}"
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project)) as src, zipfile.ZipFile(
            result,"w",compression=zipfile.ZIP_DEFLATED,allowZip64=False) as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == "3D/3dmodel.model":
                root = SafeET.fromstring(data)
                root.set("xmlns:slic3rpe","http://schemas.slic3r.org/3mf/2017/06")
                resources = root.find(m+"resources")
                header = ET.Element(m+"metadata",{"name":"slic3rpe:MmPaintingVersion"})
                header.text = "2"
                root.insert(list(root).index(resources),header)
                faces = root.findall("./"+m+"resources/"+m+"object/"+m+"mesh/"+m+"triangles/"+m+"triangle")
                # The printable ModelPart is first; native typed volumes
                # append their own triangles after it. Painted source facet
                # states must never spill onto non-printing modifier meshes.
                config=SafeET.fromstring(
                    src.read("Metadata/Slic3r_PE_model.config"))
                model_part=config.find("./object/volume")
                if (model_part is None or
                        model_part.get("firstid")!="0" or
                        model_part.get("lastid")!=str(len(states)-1) or
                        (len(faces)>len(states))!=bool(typed) or
                        len(faces)<len(states)):
                    raise SlicerProfileError("Prusa painted ModelPart face boundaries changed.")
                for face,state in zip(faces[:len(states)],states):
                    if state is not None:
                        face.set("slic3rpe:mmu_segmentation",state)
                data = ET.tostring(root,encoding="utf-8",xml_declaration=True)
            elif name == "Metadata/Slic3r_PE_model.config":
                root = SafeET.fromstring(data)
                volume = root.find("./object/volume")
                ET.SubElement(volume,"metadata",{"type":"volume","key":"extruder","value":"1"})
                data = ET.tostring(root,encoding="utf-8",xml_declaration=True)
            dst.writestr(name,data)
    output = result.getvalue()
    if len(output)>32*1024*1024:
        raise SlicerProfileError("Prusa colour candidate exceeds project limit.")
    return output
