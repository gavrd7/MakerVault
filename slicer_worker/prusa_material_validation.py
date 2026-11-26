"""Offline validation for candidate Prusa material projects, NOT worker admission.

Strip only an explicit, understood native MMU annotation and then run the
unmodified strict single-material validator on the remaining archive.
The authenticated worker does not call this module until material selection,
purge and output audits are independently integrated and approved.
"""
import io
import math
import zipfile
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from .prusa_3mf_validation import validate_prusa_native_3mf, CONFIG, PARTS, LAYER_RANGES, NS
from .runner import WorkerError
from .prusa_vendor_profiles import validate_flat_prusa_preset

MODEL = "3D/3dmodel.model"
PAINT = "{http://schemas.slic3r.org/3mf/2017/06}mmu_segmentation"
TOWER = "Metadata/Prusa_Slicer_wipe_tower_information.xml"


def _refuse():
    raise WorkerError("Unsupported native Prusa multi-material candidate.")


def _qualified_topology(printer_ini):
    try:
        settings = validate_flat_prusa_preset(printer_ini, kind="printer")
    except (TypeError, ValueError):
        _refuse()
    try:
        nozzles = [float(part.strip()) for part in settings["nozzle_diameter"].split(",")]
    except (TypeError, ValueError):
        _refuse()
    if (not 1 <= len(nozzles) <= 8 or
            any(not math.isfinite(d) or not .1 <= d <= 1.2 for d in nozzles)):
        _refuse()
    changer = settings.get("single_extruder_multi_material", "0").strip().lower()
    if changer not in ("0", "1", "false", "true"):
        _refuse()
    same_nozzle = changer in ("1", "true")
    if same_nozzle and len(nozzles) < 2:
        _refuse()
    return len(nozzles), same_nozzle


def validate_prusa_material_candidate(data, *, printer_ini, tools=None, colour=False, tower=None):
    if not isinstance(data, bytes) or not 0 < len(data) <= 32*1024*1024:
        _refuse()
    logical_count, changer = _qualified_topology(printer_ini)
    if tower is not None:
        if (not changer or not isinstance(tower, (tuple, list)) or len(tower) != 5
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in tower)):
            _refuse()
        x, y, rotation, width, depth = tower
        if (not 70 <= width <= 1000 or not 60 <= depth <= 1000
                or not 5 <= x <= width - 65 or not 5 <= y <= depth - 45
                or not -360 <= rotation <= 360):
            _refuse()
    if colour:
        if tools is not None or not changer or logical_count < 2:
            _refuse()
    elif (not isinstance(tools,(tuple,list)) or not 2 <= len(tools) <= 12
          or len(set(tools)) < 2 or any(type(t) is not int or
                                        not 1 <= t <= logical_count for t in tools)):
        _refuse()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos=z.infolist()
            indx=logical_count>5 and not changer
            allowed=PARTS | ({TOWER} if tower is not None else set())
            if indx and any(i.filename==LAYER_RANGES for i in infos):
                allowed=allowed|{LAYER_RANGES}
            if (len(infos)!=len(allowed) or {i.filename for i in infos}!=allowed
                or any(i.is_dir() or i.file_size < 1 or i.file_size >
                       (80*1024*1024 if i.filename==MODEL else 65536)
                       for i in infos)):
                _refuse()
            parts={i.filename:z.read(i.filename) for i in infos}
        if tower is not None:
            tower_xml=parts.pop(TOWER)
            if b"<!" in tower_xml or b"\x00" in tower_xml:
                _refuse()
            info=SafeET.fromstring(tower_xml)
            if info.tag!="wipe_tower_information" or len(info) or set(info.attrib)!={
                    "bed_idx","position_x","position_y","rotation_deg"} or info.get("bed_idx")!="0":
                _refuse()
            if any(info.get(key)!=format(float(value),".3f")
                   for key,value in zip(("position_x","position_y","rotation_deg"),tower[:3])):
                _refuse()
        for xml_part in (MODEL,CONFIG):
            if b"<!" in parts[xml_part] or b"\x00" in parts[xml_part]:
                _refuse()
        model=SafeET.fromstring(parts[MODEL])
        cfg=SafeET.fromstring(parts[CONFIG])
        objects=cfg.findall("object")
        if (cfg.tag!="config" or cfg.attrib or len(objects)!=len(cfg)
            or (colour and len(objects)!=1)
            or (not colour and len(objects)!=len(tools))):
            _refuse()
        if colour:
            metadata=[n for n in model.findall(NS+"metadata")
                      if n.get("name")=="slic3rpe:MmPaintingVersion"]
            if len(metadata)!=1 or metadata[0].attrib!={"name":"slic3rpe:MmPaintingVersion"} or metadata[0].text!="2":
                _refuse()
            model.remove(metadata[0])
            facets=model.findall("./"+NS+"resources/"+NS+"object/"+NS+"mesh/"+NS+"triangles/"+NS+"triangle")
            marked=0
            selected={1}
            # Verified fixed Prusa TriangleSelector leaf-state encoding.
            # No caller-controlled recursive/split nibble streams are trusted:
            # those require a separate bounds and extrusion audit.
            states={"4":1, "8":2, "0C":3, "1C":4, "2C":5}
            for face in facets:
                if PAINT in face.attrib:
                    value=face.attrib.pop(PAINT)
                    tool=states.get(value)
                    if tool is None or tool>logical_count:
                        _refuse()
                    selected.add(tool)
                    marked+=1
            if marked<1 or len(selected)<2:
                _refuse()
            volumes=objects[0].findall("volume")
            if len(volumes)!=1:
                _refuse()
            extras=[n for n in volumes[0] if n.tag=="metadata" and n.get("key")=="extruder"]
            if len(extras)!=1 or extras[0].attrib!={"type":"volume","key":"extruder","value":"1"}:
                _refuse()
            volumes[0].remove(extras[0])
        else:
            for index,(obj,tool) in enumerate(zip(objects,tools),1):
                if obj.attrib!={"id":str(index),"instances_count":"1"}:
                    _refuse()
                extras=[n for n in obj if n.tag=="metadata" and n.get("key")=="extruder"]
                if len(extras)!=1 or extras[0].attrib!={"type":"object","key":"extruder","value":str(tool)}:
                    _refuse()
                obj.remove(extras[0])
        parts[MODEL]=ET.tostring(model,encoding="utf-8",xml_declaration=True)
        parts[CONFIG]=ET.tostring(cfg,encoding="utf-8",xml_declaration=True)
        out=io.BytesIO()
        with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED,
                             allowZip64=False) as dest:
            for part in sorted(parts):
                dest.writestr(part,parts[part])
        receipt=validate_prusa_native_3mf(out.getvalue())
        if colour and (receipt["objects"]!=1 or receipt["regions"]!=0
                       or receipt["paint_channels"] or receipt["layer_ranges"]):
            _refuse()
        # Native INDX modifier/negative volumes retain their exact typed,
        # independently validated 3MF mesh and per-model tool metadata.
        # Other architectures still require unmodified model meshes.
        indx = logical_count > 5 and not changer
        if not colour and (receipt["objects"]!=len(tools) or
                           receipt["paint_channels"] or
                           (receipt["regions"] and not indx) or
                           (receipt["layer_ranges"] and not indx)):
            _refuse()
        return {"objects":receipt["objects"],"colour_facets":marked if colour else 0,
                "tools":tuple(tools) if not colour else tuple(sorted(selected)),
                "wipe_tower":tower is not None}
    except WorkerError:
        raise
    except (TypeError,ValueError,KeyError,AttributeError,ET.ParseError,
            zipfile.BadZipFile,RuntimeError,OSError,OverflowError):
        _refuse()
