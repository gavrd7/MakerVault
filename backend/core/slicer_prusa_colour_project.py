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
                                 bed_width, bed_depth,
                                 research_compound=False):
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
    if typed and not research_compound and (len(typed)!=1 or typed[0]["kind"]!="modifier" or
                  typed[0]["shape"]!="box" or
                  set(typed[0]["settings"])!={"sparse_infill_density"}):
        raise SlicerProfileError(
            "This Prusa painted/modifier pairing requires one native box infill region.")
    if type(research_compound) is not bool:
        raise SlicerProfileError("Invalid Prusa native research mode.")
    channels = tuple(k for k in ("support_paint", "seam_paint", "fuzzy_skin_paint")
                     if isinstance(item, dict) and
                     isinstance(item.get(k), dict) and item[k].get("regions"))
    if channels and not research_compound:
        raise SlicerProfileError("Prusa compound colour painting needs genuine native qualification.")
    if (not 2 <= count <= 8 or not isinstance(item, dict)
            or not isinstance(source, bytes)
            or not isinstance(colour_tool_indices, dict)
            or not colour_tool_indices
            or any(type(k) is not int or type(v) is not int or not 1 <= v <= 7 or not v < count
                   for k,v in colour_tool_indices.items())
            or any(item.get(k) for k in ("negative_volumes",
                   "variable_layer_profile", "material_slot")) or
            any(item.get(k) for k in ("support_paint","seam_paint","fuzzy_skin_paint")
                if k not in channels)):
        raise SlicerProfileError("Unsupported Prusa native colour candidate.")
    paint = item.get("colour_paint")
    if not isinstance(paint,dict) or not paint.get("regions"):
        raise SlicerProfileError("Prusa native colour candidate requires facet regions.")
    painted = native_combined_paint_triangles(
        list(_triangles(source)),
        support=item.get("support_paint") if research_compound else None,
        seam=item.get("seam_paint") if research_compound else None,
        fuzzy=item.get("fuzzy_skin_paint") if research_compound else None,
        colour=paint, colour_tool_indices=colour_tool_indices)
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
        states.append(dict(tags))
    if not any(tags.get("paint_color") not in (None, "4") for tags in states):
        raise SlicerProfileError("Prusa colour candidate needs second-tool facets.")
    row = dict(item)
    row.pop("colour_paint")
    if research_compound:
        for channel in channels:
            # Already split and encoded in the same ModelPart as mmu paint.
            # Never run the independent source-fingerprint splitter twice.
            row.pop(channel)
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
                if channels:
                    from .slicer_prusa_paint import HEADERS
                    for channel in sorted(channels):
                        metadata = ET.Element(m+"metadata", {"name":HEADERS[channel]})
                        metadata.text = "2"
                        root.insert(list(root).index(resources), metadata)
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
                from .slicer_prusa_paint import NATIVE_ATTRIBUTES
                expected = set()
                for face,tags in zip(faces[:len(states)],states):
                    if "paint_color" in tags:
                        face.set("slic3rpe:mmu_segmentation",tags["paint_color"])
                    for key, native_key in NATIVE_ATTRIBUTES.items():
                        if key in tags:
                            face.set(native_key, tags[key])
                            expected.add(key)
                requested = {name for name, field in (
                    ("paint_supports", "support_paint"),
                    ("paint_seam", "seam_paint"),
                    ("paint_fuzzy_skin", "fuzzy_skin_paint"))
                    if field in channels}
                if expected != requested:
                    raise SlicerProfileError("Prusa compound colour exporter dropped a painted channel.")
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


def build_prusa_multi_colour_candidate(rows, *, printer_ini,
                                       colour_tool_indices,
                                       bed_width, bed_depth):
    """Build independently painted native Prusa ModelParts on one shared bed.

    Every object's paint is first encoded by the existing single-object
    fingerprint-checked exporter. Merge *only* those five known 3MF parts,
    rebind object identities and require isolated resource/volume ownership.
    This exporter alone does not authorize slicing or printer submission:
    the separate worker must verify every model/tool region in real G-code.
    """
    import copy
    if (not isinstance(rows,(list,tuple)) or not 2<=len(rows)<=200 or
            not isinstance(colour_tool_indices,dict) or
            not 1<=len(colour_tool_indices)<=7):
        raise SlicerProfileError("Prusa multiple painted models need two to 200 signed sources.")
    for item, raw in rows:
        if (not isinstance(item,dict) or not isinstance(raw,bytes) or
                not (item.get("colour_paint") or {}).get("regions") or
                any(item.get(key) for key in (
                    "modifier_volumes","negative_volumes","support_paint",
                    "seam_paint","fuzzy_skin_paint","variable_layer_profile",
                    "material_slot"))):
            raise SlicerProfileError(
                "Prusa independent colour models require native colour-only source facets.")
    projects=[build_prusa_colour_candidate(
        item,raw,printer_ini=printer_ini,
        colour_tool_indices=colour_tool_indices,
        bed_width=bed_width,bed_depth=bed_depth) for item,raw in rows]
    with zipfile.ZipFile(io.BytesIO(projects[0])) as source:
        parts={name:source.read(name) for name in source.namelist()}
    model=SafeET.fromstring(parts["3D/3dmodel.model"])
    config=SafeET.fromstring(parts["Metadata/Slic3r_PE_model.config"])
    ns="{"+NS+"}"
    resources=model.find(ns+"resources")
    build=model.find(ns+"build")
    objects=config.findall("./object")
    if (resources is None or build is None or len(objects)!=1 or
            len(resources)!=1 or len(build)!=1):
        raise SlicerProfileError("Unexpected native Prusa coloured parent structure.")
    resources[0].set("id","1")
    build[0].set("objectid","1")
    objects[0].set("id","1")
    for index,project in enumerate(projects[1:],2):
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            other_model=SafeET.fromstring(archive.read("3D/3dmodel.model"))
            other_config=SafeET.fromstring(
                archive.read("Metadata/Slic3r_PE_model.config"))
        other_resources=other_model.find(ns+"resources")
        other_build=other_model.find(ns+"build")
        other_objects=other_config.findall("./object")
        if (other_resources is None or other_build is None or
                len(other_resources)!=1 or len(other_build)!=1 or
                len(other_objects)!=1 or
                other_build[0].get("objectid")!=other_resources[0].get("id")):
            raise SlicerProfileError("Prusa coloured source lost independent ModelPart.")
        resource=copy.deepcopy(other_resources[0])
        resource.set("id",str(index))
        resources.append(resource)
        instance=copy.deepcopy(other_build[0])
        instance.set("objectid",str(index))
        build.append(instance)
        setting=copy.deepcopy(other_objects[0])
        setting.set("id",str(index))
        config.append(setting)
    if (len(resources)!=len(rows) or len(objects)!=1 or
            len(config)!=len(rows) or len(build)!=len(rows)):
        raise SlicerProfileError("Prusa painted model identity mismatch.")
    # Genuine Prusa 2.9.7 silently ignores nn:mmu_segmentation
    # when the original slic3rpe prefix is rewritten by ElementTree.
    # Normalize only this *exported* XML's prefix; ET.register_namespace
    # mutates global process state and can corrupt unrelated validation.
    import re
    native_xml=ET.tostring(model,encoding="utf-8",xml_declaration=True)
    url=b"http://schemas.slic3r.org/3mf/2017/06"
    names=re.findall(rb'xmlns:(ns[0-9]+)="'+url+b'"',native_xml)
    if len(names)!=1:
        raise SlicerProfileError("Prusa multi-object paint namespace is ambiguous.")
    namespace=names[0]
    native_xml=native_xml.replace(
        b'xmlns:'+namespace+b'="'+url+b'"',
        b'xmlns:slic3rpe="'+url+b'"')
    native_xml=native_xml.replace(
        b' '+namespace+b':mmu_segmentation=',
        b' slic3rpe:mmu_segmentation=')
    if native_xml.count(b'slic3rpe:mmu_segmentation=')<len(rows):
        raise SlicerProfileError("Prusa source paint metadata lost during merge.")
    parts["3D/3dmodel.model"]=native_xml
    parts["Metadata/Slic3r_PE_model.config"]=ET.tostring(
        config,encoding="utf-8",xml_declaration=True)
    merged=io.BytesIO()
    with zipfile.ZipFile(merged,"w",compression=zipfile.ZIP_DEFLATED,
                         allowZip64=False) as archive:
        for name,payload in parts.items():
            archive.writestr(name,payload)
    candidate=merged.getvalue()
    if len(candidate)>32*1024*1024:
        raise SlicerProfileError("Prusa multiple colour source exceeds project limit.")
    return candidate
