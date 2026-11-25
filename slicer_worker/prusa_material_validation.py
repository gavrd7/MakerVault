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

from .prusa_3mf_validation import validate_prusa_native_3mf, CONFIG, PARTS, NS
from .runner import WorkerError
from .prusa_vendor_profiles import validate_flat_prusa_preset

MODEL = "3D/3dmodel.model"
PAINT = "{http://schemas.slic3r.org/3mf/2017/06}mmu_segmentation"


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
    if (not 1 <= len(nozzles) <= 5 or
            any(not math.isfinite(d) or not .1 <= d <= 1.2 for d in nozzles)):
        _refuse()
    changer = settings.get("single_extruder_multi_material", "0").strip().lower()
    if changer not in ("0", "1", "false", "true"):
        _refuse()
    same_nozzle = changer in ("1", "true")
    if same_nozzle and len(nozzles) < 2:
        _refuse()
    return len(nozzles), same_nozzle


def validate_prusa_material_candidate(data, *, printer_ini, tools=None, colour=False):
    if not isinstance(data, bytes) or not 0 < len(data) <= 32*1024*1024:
        _refuse()
    logical_count, changer = _qualified_topology(printer_ini)
    if colour:
        if tools is not None or not changer or logical_count < 2:
            _refuse()
    elif (not isinstance(tools,(tuple,list)) or not 2 <= len(tools) <= 5
          or len(set(tools)) < 2 or any(type(t) is not int or
                                        not 1 <= t <= logical_count for t in tools)):
        _refuse()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos=z.infolist()
            if (len(infos)!=len(PARTS) or {i.filename for i in infos}!=PARTS
                or any(i.is_dir() or i.file_size < 1 or i.file_size >
                       (80*1024*1024 if i.filename==MODEL else 65536)
                       for i in infos)):
                _refuse()
            parts={i.filename:z.read(i.filename) for i in infos}
        for xml_part in (MODEL,CONFIG):
            if b"<!" in parts[xml_part] or b"\x00" in parts[xml_part]:
                _refuse()
        model=ET.fromstring(parts[MODEL])
        cfg=ET.fromstring(parts[CONFIG])
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
            for face in facets:
                if PAINT in face.attrib:
                    if face.attrib.pop(PAINT)!="8":
                        _refuse()
                    marked+=1
            if marked<1:
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
        if not colour and (receipt["objects"]!=len(tools) or
                           receipt["paint_channels"] or receipt["regions"] or
                           receipt["layer_ranges"]):
            _refuse()
        return {"objects":receipt["objects"],"colour_facets":marked if colour else 0,
                "tools":tuple(tools) if not colour else (1,2)}
    except WorkerError:
        raise
    except (TypeError,ValueError,KeyError,AttributeError,ET.ParseError,
            zipfile.BadZipFile,RuntimeError,OSError,OverflowError):
        _refuse()
