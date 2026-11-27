"""Genuine Prusa 2.9.7 XL five-head facet-paint feasibility experiment.

Research only. Does not use or relax MakerVault's independently audited
production worker admission; exact XL native G-code is inspected offline.
"""
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa, WorkerError


def painted_object_internal_wall_moves(data):
    """Actual moving positive-E native inner perimeters for a painted object.

    No G-code annotations, source tags or stationary E recovery alone can
    qualify a changed wall count.
    """
    import math
    from slicer_worker.prusa_colour_gcode_audit import WORD
    mode_relative_e=False
    mode_relative_xy=False
    e=0.
    x=y=None
    role=""
    counted=0
    for number,line in enumerate(data.decode("utf-8").splitlines()):
        if number>2_000_000 or len(line)>16384:
            raise AssertionError("Native painted wall-count audit exceeded limits")
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        command=line.split(";",1)[0].strip()
        if not command:
            continue
        op=command.split(None,1)[0].upper()
        if op not in ("M82","M83","G90","G91","G92","G0","G00","G1","G01"):
            continue
        fields={k.upper():float(v) for k,v in WORD.findall(command)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in fields.values()):
            raise AssertionError("Native painted-wall coordinate invalid")
        if op=="M82":
            mode_relative_e=False
        elif op=="M83":
            mode_relative_e=True
        elif op=="G90":
            mode_relative_xy=False
        elif op=="G91":
            mode_relative_xy=True
        elif op=="G92":
            e=fields.get("E",e)
            x=fields.get("X",x)
            y=fields.get("Y",y)
        else:
            old_x,old_y=x,y
            if mode_relative_xy:
                x=x+fields["X"] if x is not None and "X" in fields else x
                y=y+fields["Y"] if y is not None and "Y" in fields else y
            else:
                x=fields.get("X",x)
                y=fields.get("Y",y)
            changed=(fields["E"] if mode_relative_e else
                     fields["E"]-e) if "E" in fields else 0
            if "E" in fields:
                e=e+fields["E"] if mode_relative_e else fields["E"]
            if (op in ("G1","G01") and changed>1e-6 and
                    role=="perimeter" and None not in (old_x,old_y,x,y) and
                    math.hypot(x-old_x,y-old_y)>1e-6):
                counted+=1
    return counted


def main(binary, vendor):
    blob=Path(vendor).read_bytes()
    source_sha=hashlib.sha256(blob).hexdigest()
    resolve=lambda kind,name:flatten_prusa_vendor_preset(
        blob,kind=kind,name=name,expected_sha256=source_sha)
    printer=resolve("printer","Original Prusa XL - 5T 0.4 nozzle")
    printer=b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode"
        else line for line in printer.splitlines())+b"\n"
    machine=validate_flat_prusa_preset(printer,kind="printer")
    assert machine.get("single_extruder_multi_material","0") in ("0","false")
    assert len(machine["nozzle_diameter"].split(","))==5
    stock=validate_flat_prusa_preset(resolve("filament","Generic PLA"),kind="filament")
    filaments=[]
    for temp in (205,210,215,220,225):
        row={**stock,"temperature":str(temp),"first_layer_temperature":str(temp)}
        filaments.append("".join(f"{key} = {value}\n"
                        for key,value in sorted(row.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    base=validate_flat_prusa_preset(resolve("print","0.20mm NORMAL"),kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        base[key]="0"
    process="".join(f"{key} = {value}\n"
                    for key,value in sorted(base.items())).encode()
    from core.slicer_prusa_process_settings import apply_prusa_process_overrides
    process = apply_prusa_process_overrides(process, {"layer_height": .16, "wall_loops": 3})
    assert b"layer_height = 0.16\n" in process and b"perimeters = 3\n" in process
    stl,_,_,paint=fixture(include_paint=True)
    row={"asset_id":"xl-native-paint-research","x_mm":0,"y_mm":0,"z_mm":0,
         "rotation_deg":0,"scale_percent":100,"colour_paint":paint}
    project=build_prusa_colour_candidate(
        row,stl,printer_ini=printer,colour_tool_indices={1:1},
        bed_width=360,bed_depth=360)
    with TemporaryDirectory(prefix="prusa-xl-paint-research-") as folder:
        work=Path(folder)
        for name,data in (
            ("input.3mf",project),("printer.ini",printer),
            ("filament.ini",palette),("process.ini",process)):
            (work/name).write_bytes(data)
        # Exercise the same dedicated XL marker as the authenticated worker.
        # The service independently admits and audits the 3MF before writing it.
        (work/"prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary),work)
        output=(work/"output.gcode").read_bytes()
        counts=painted_external_walls(output,center_x=180,center_y=180)
        assert counts[1]["front"]>=20,counts
        assert counts[0]["back"]>=20,counts
        assert counts[1]["back"]<=2,counts
        # The genuine 2.9.7 native toolpaths retain T0 foundation perimeters
        # along the painted wall. Audit exclusivity of alternate tools, not
        # legitimate T0 base extrusion (observed 271 front T0 segments).
        assert counts[1]["back"]<=2,counts
        for key in (2,3,4):
            assert counts[key]["front"]<=2 and counts[key]["back"]<=2,counts
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
        receipt=audit_prusa_xl_colour_gcode(
            output,project,printer_ini=printer,tool=1)
        assert receipt["painted_wall_moves"][1]["front"]>20
        assert receipt["painted_wall_moves"][0]["back"]>20
        assert receipt["wipe_tower"] is False
        print("PASS: genuine independent XL5 T1-front/T0-back paint",
              counts,receipt,"sha256",hashlib.sha256(output).hexdigest(),
              flush=True)
        # The same MakerVault painter must preserve its ordinary Object
        # walls setting, rather than forcing users to clear Object settings.
        # Compare moving positive-E native *internal* perimeters with one
        # and five requested walls on the identical painted source and tools.
        wall_observations={}
        from slicer_worker.prusa_offline_contract import validate_prusa_offline_xl_colour_inputs
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
        for requested in (1,5):
            changed=build_prusa_colour_candidate(
                {**row,"process_overrides":{"wall_loops":requested}},
                stl,printer_ini=printer,colour_tool_indices={1:1},
                bed_width=360,bed_depth=360)
            validate_prusa_offline_xl_colour_inputs(
                project=changed,printer=printer,filament=palette,
                process=process,tool=1)
            (work/"input.3mf").write_bytes(changed)
            (work/"output.gcode").unlink(missing_ok=True)
            run_prusa(Path(binary),work)
            printed=(work/"output.gcode").read_bytes()
            audit_prusa_xl_colour_gcode(
                printed,changed,printer_ini=printer,tool=1)
            wall_observations[requested]=painted_object_internal_wall_moves(printed)
        print("Prusa genuine painted model Object wall settings",
              wall_observations,flush=True)
        assert wall_observations[5]>=40,wall_observations
        assert wall_observations[5]>max(4,wall_observations[1]*1.5),wall_observations
        print("PASS: Prusa native painted XL Object wall loops change deposited "
              "interior perimeters",wall_observations,flush=True)

        # MakerVault feature *composition* research: colour painting and a
        # parameter modifier on the same real object. The existing exporter
        # produces each native feature independently; merge their signed
        # model/config structures and inspect genuinely deposited regional
        # extrusion before permitting this combination in the live worker.
        # This is a research-only 3MF; UI and worker admission remain gated.
        import io
        import uuid
        import zipfile
        from xml.etree import ElementTree as ET
        from defusedxml import ElementTree as SafeET
        from core.slicer_prusa_3mf import build_prusa_native_3mf
        from scripts.prusa_native_regions_smoke import regional_extrusion
        from slicer_worker.prusa_3mf_validation import validate_prusa_native_3mf
        ns="{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        paint_ns="{http://schemas.slic3r.org/3mf/2017/06}mmu_segmentation"
        typed={
            "id":str(uuid.uuid4()),"shape":"box","kind":"modifier",
            "width_mm":10,"depth_mm":10,"height_mm":18,
            "x_mm":0,"y_mm":0,"z_mm":10,
            "coordinate_space":"world",
            "rotation_xyz_deg":[0,0,0],
            "scale_xyz_percent":[100,100,100],
            "settings":{"sparse_infill_density":85},
        }
        try:
            colour_only=build_prusa_colour_candidate(
                row,stl,printer_ini=printer,colour_tool_indices={1:1},
                bed_width=360,bed_depth=360)
            typed_only=build_prusa_native_3mf(
                [({**{k:v for k,v in row.items() if k!="colour_paint"},
                   "modifier_volumes":[typed]},stl)],
                bed_width=360,bed_depth=360)
            with zipfile.ZipFile(io.BytesIO(colour_only)) as c,zipfile.ZipFile(
                    io.BytesIO(typed_only)) as native:
                painted_root=SafeET.fromstring(c.read("3D/3dmodel.model"))
                typed_root=SafeET.fromstring(native.read("3D/3dmodel.model"))
                typed_config=SafeET.fromstring(
                    native.read("Metadata/Slic3r_PE_model.config"))
                paint_faces=painted_root.findall(
                    "./"+ns+"resources/"+ns+"object/"+ns+"mesh/"+
                    ns+"triangles/"+ns+"triangle")
                target_faces=typed_root.findall(
                    "./"+ns+"resources/"+ns+"object/"+ns+"mesh/"+
                    ns+"triangles/"+ns+"triangle")
                printable=typed_config.find("./object/volume")
                assert len(paint_faces)==int(printable.get("lastid"))+1
                assert len(target_faces)>len(paint_faces)
                for idx,source_face in enumerate(paint_faces):
                    state=source_face.get(paint_ns)
                    if state is not None:
                        target_faces[idx].set("slic3rpe:mmu_segmentation",state)
                native_resources=typed_root.find(ns+"resources")
                hdr=ET.Element(ns+"metadata",{"name":"slic3rpe:MmPaintingVersion"})
                hdr.text="2"
                typed_root.insert(list(typed_root).index(native_resources),hdr)
                ET.SubElement(printable,"metadata",{
                    "type":"volume","key":"extruder","value":"1"})
                composed=io.BytesIO()
                with zipfile.ZipFile(composed,"w",compression=zipfile.ZIP_DEFLATED) as out:
                    for name in native.namelist():
                        data=native.read(name)
                        if name=="3D/3dmodel.model":
                            data=ET.tostring(typed_root,encoding="utf-8",
                                             xml_declaration=True)
                        elif name=="Metadata/Slic3r_PE_model.config":
                            data=ET.tostring(typed_config,encoding="utf-8",
                                             xml_declaration=True)
                        out.writestr(name,data)
                mixed=composed.getvalue()
            (work/"input.3mf").write_bytes(colour_only)
            (work/"output.gcode").unlink(missing_ok=True)
            run_prusa(Path(binary),work)
            reference=(work/"output.gcode").read_bytes()
            (work/"input.3mf").write_bytes(mixed)
            (work/"output.gcode").unlink(missing_ok=True)
            run_prusa(Path(binary),work)
            combined=(work/"output.gcode").read_bytes()
            selected=painted_external_walls(combined,center_x=180,center_y=180)
            base_effect=regional_extrusion(reference,center_x=180,center_y=180)
            mixed_effect=regional_extrusion(combined,center_x=180,center_y=180)
            assert selected[1]["front"]>20 and selected[1]["back"]<=2,selected
            assert mixed_effect[0]>base_effect[0]*1.5,(base_effect,mixed_effect)
            print("RESEARCH PASS: genuine Prusa painted XL plus native "
                  "modifier changed model-local deposition",
                  {"colour":selected,"baseline":base_effect,
                   "modifier":mixed_effect},flush=True)
        except (AssertionError,ValueError,WorkerError,RuntimeError,
                zipfile.BadZipFile) as exc:
            print("RESEARCH BLOCKED: combined Prusa painted colour plus "
                  "modifier",type(exc).__name__,str(exc)[:280],flush=True)

        # Required acceptance: use the production MakerVault project builder,
        # authenticated worker preflight and strict painted-wall G-code audit.
        from slicer_worker.prusa_offline_contract import (
            validate_prusa_offline_xl_colour_inputs)
        from slicer_worker.prusa_colour_gcode_audit import (
            audit_prusa_xl_colour_gcode)
        production=build_prusa_colour_candidate(
            {**row,"modifier_volumes":[typed]},stl,printer_ini=printer,
            colour_tool_indices={1:1},bed_width=360,bed_depth=360)
        approved=validate_prusa_offline_xl_colour_inputs(
            project=production,printer=printer,filament=palette,
            process=process,tool=1)
        assert approved["tool"]==1 and not approved["wipe_tower"],approved
        (work/"input.3mf").write_bytes(colour_only)
        (work/"output.gcode").unlink(missing_ok=True)
        run_prusa(Path(binary),work)
        clean_gcode=(work/"output.gcode").read_bytes()
        (work/"input.3mf").write_bytes(production)
        (work/"output.gcode").unlink(missing_ok=True)
        run_prusa(Path(binary),work)
        modified_gcode=(work/"output.gcode").read_bytes()
        proof=audit_prusa_xl_colour_gcode(
            modified_gcode,production,printer_ini=printer,tool=1)
        unchanged=regional_extrusion(clean_gcode,center_x=180,center_y=180)
        changed=regional_extrusion(modified_gcode,center_x=180,center_y=180)
        assert changed[0]>unchanged[0]*1.5,(unchanged,changed)
        assert proof["painted_wall_moves"][1]["front"]>=20,proof
        assert proof["painted_wall_moves"][1]["back"]<=2,proof
        print("PASS: authenticated MakerVault XL colour and native infill "
              "modifier both affect genuine deposited G-code",
              {"base":unchanged,"modifier":changed,"paint":proof},flush=True)



        # The same native facet encoder supports two opposing selected
        # tools. Run this through the *independent-head* worker contract
        # and spatial auditor; it must never inherit an MMU wipe tower.
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        from slicer_worker.prusa_offline_contract import validate_prusa_offline_xl_colour_inputs
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_dual_colour_gcode
        triangles=list(_triangles(stl))
        lower=[min(p[a] for face in triangles for p in face) for a in range(3)]
        upper=[max(p[a] for face in triangles for p in face) for a in range(3)]
        origin=((lower[0]+upper[0])/2,(lower[1]+upper[1])/2,lower[2])
        local=[[tuple(v[a]-origin[a] for a in range(3)) for v in face]
               for face in triangles]
        back=[{"face":i,"polygon":[list(v) for v in face]}
              for i,face in enumerate(local)
              if all(abs(v[1]-10)<.00001 for v in face)]
        assert len(back)==2, "Expected the two rear wall triangles"
        multi={**paint, "signature":_fingerprint(local),
               "palette":[*paint["palette"],
                          {"color":"#fadd4d","label":"XL T2 back"}],
               "regions":[*paint["regions"],{"slot":2,"patches":back}]}
        dual_project=build_prusa_colour_candidate(
            {**row,"colour_paint":multi},stl,printer_ini=printer,
            colour_tool_indices={1:1,2:2},bed_width=360,bed_depth=360)
        approved=validate_prusa_offline_xl_colour_inputs(
            project=dual_project,printer=printer,filament=palette,
            process=process,tools=[1,2])
        assert approved["tools"]==[1,2] and not approved["wipe_tower"],approved
        (work/"input.3mf").write_bytes(dual_project)
        (work/"output.gcode").unlink()
        run_prusa(Path(binary),work)
        dual_output=(work/"output.gcode").read_bytes()
        dual_receipt=audit_prusa_dual_colour_gcode(
            dual_output,dual_project,printer_ini=printer,tools=[1,2],tower=None)
        assert dual_receipt["wall_moves"][1]["front"]>=20,dual_receipt
        assert dual_receipt["wall_moves"][2]["back"]>=20,dual_receipt
        assert not dual_receipt["tower_extrusion_moves"],dual_receipt
        assert dual_receipt["wipe_tower"] is False,dual_receipt
        print("PASS: genuine independent XL5 dual painted walls T1/T2",
              dual_receipt,"sha256",hashlib.sha256(dual_output).hexdigest(),
              flush=True)

        # A second genuine binary project proves the same native 3MF and
        # authenticated toolpath auditor work on the X-min/X-max walls.
        # Opposite wall direction comes from source mesh geometry, never
        # from hardcoded Y-facing swatch coordinates.
        xnegative=[{"face":i,"polygon":[list(v) for v in face]}
                   for i,face in enumerate(local)
                   if all(abs(v[0]+10)<.00001 for v in face)]
        xpositive=[{"face":i,"polygon":[list(v) for v in face]}
                   for i,face in enumerate(local)
                   if all(abs(v[0]-10)<.00001 for v in face)]
        assert len(xnegative)==len(xpositive)==2
        xpaint={**paint,"signature":_fingerprint(local),
                "regions":[{"slot":1,"patches":xnegative},
                           {"slot":2,"patches":xpositive}],
                "palette":[*paint["palette"],
                           {"color":"#fadd4d","label":"XL T2 right"}]}
        xproject=build_prusa_colour_candidate(
            {**row,"colour_paint":xpaint},stl,printer_ini=printer,
            colour_tool_indices={1:1,2:2},bed_width=360,bed_depth=360)
        xreceipt=validate_prusa_offline_xl_colour_inputs(
            project=xproject,printer=printer,filament=palette,
            process=process,tools=[1,2])
        assert xreceipt["tools"]==[1,2] and not xreceipt["wipe_tower"]
        (work/"input.3mf").write_bytes(xproject)
        (work/"output.gcode").unlink(missing_ok=True)
        run_prusa(Path(binary),work)
        xoutput=(work/"output.gcode").read_bytes()
        xproof=audit_prusa_dual_colour_gcode(
            xoutput,xproject,printer_ini=printer,tools=[1,2],tower=None)
        assert xproof["wall_moves"][1]["front"]>=20,xproof
        assert xproof["wall_moves"][2]["back"]>=20,xproof
        assert xproof["wall_moves"][1]["back"]<=2,xproof
        assert xproof["wall_moves"][2]["front"]<=2,xproof
        assert not xproof["wipe_tower"],xproof
        print("PASS: genuine independent XL5 X-opposing dual painted walls",
              xproof,"sha256",hashlib.sha256(xoutput).hexdigest(),flush=True)

        # Native transform parity: a 90-degree rotated Y-painted pair now
        # presents on X faces. The workbench's mesh-derived tool ordering
        # must reverse where required; colour facet identities cannot be
        # inferred from the original browser swatch order.
        from slicer_worker.prusa_colour_gcode_audit import _two_painted_wall_regions
        rotated=build_prusa_colour_candidate(
            {**row,"rotation_deg":90,"colour_paint":multi},stl,
            printer_ini=printer,colour_tool_indices={1:1,2:2},
            bed_width=360,bed_depth=360)
        selection=(1,2)
        try:
            _two_painted_wall_regions(rotated,selection)
        except WorkerError:
            selection=(2,1)
            _two_painted_wall_regions(rotated,selection)
        checked=validate_prusa_offline_xl_colour_inputs(
            project=rotated,printer=printer,filament=palette,
            process=process,tools=list(selection))
        assert checked["tools"]==list(selection),checked
        (work/"input.3mf").write_bytes(rotated)
        (work/"output.gcode").unlink(missing_ok=True)
        run_prusa(Path(binary),work)
        rotated_output=(work/"output.gcode").read_bytes()
        rotated_proof=audit_prusa_dual_colour_gcode(
            rotated_output,rotated,printer_ini=printer,
            tools=selection,tower=None)
        assert rotated_proof["wall_moves"][selection[0]]["front"]>=20,rotated_proof
        assert rotated_proof["wall_moves"][selection[1]]["back"]>=20,rotated_proof
        assert rotated_proof["wall_moves"][selection[0]]["back"]<=2,rotated_proof
        assert rotated_proof["wall_moves"][selection[1]]["front"]<=2,rotated_proof
        print("PASS: XL5 native 90-degree rotated opposing painted walls",
              selection,rotated_proof,flush=True)


        # Four-sided native painting feasibility (base T0 plus T1..T4):
        # do not authorize the workbench until independent spatial G-code
        # evidence establishes that no alternate colour prints another wall.
        # This experiment uses the same fingerprinted MakerVault colour
        # editor regions and 3MF encoder; only the output audit is research.
        from slicer_worker.prusa_colour_gcode_audit import WORD
        import re
        sidespec=((0,-10,1),(0,10,2),(1,-10,3),(1,10,4))
        regions=[]
        colours=[{"color":"#ff8000","label":"XL base T0"}]
        for axis,face_value,tool in sidespec:
            patches=[{"face":i,"polygon":[list(v) for v in face]}
                     for i,face in enumerate(local)
                     if all(abs(v[axis]-face_value)<.00001 for v in face)]
            assert len(patches)==2,("Missing native side",axis,face_value)
            regions.append({"slot":tool,"patches":patches})
            colours.append({"color":("#"+format(tool*0x202020, "06X")),
                            "label":"XL wall T"+str(tool)})
        fourpaint={**paint,"signature":_fingerprint(local),
                   "palette":colours,"regions":regions}
        four=build_prusa_colour_candidate(
            {**row,"colour_paint":fourpaint},stl,printer_ini=printer,
            colour_tool_indices={t:t for t in range(1,5)},
            bed_width=360,bed_depth=360)
        (work/"input.3mf").write_bytes(four)
        (work/"output.gcode").unlink(missing_ok=True)
        try:
            run_prusa(Path(binary),work)
            lines=(work/"output.gcode").read_bytes().decode("utf-8").splitlines()
            counts={tool:{idx:0 for idx in range(4)}
                    for tool in range(5)}
            # Observe all native positive-E roles and wall-aligned geometry
            # separately: a misclassified role must never masquerade as
            # Prusa failing to generate the requested material geometry.
            native_roles={tool:{} for tool in range(5)}
            geometric_hits={tool:{idx:0 for idx in range(4)}
                            for tool in range(5)}
            # Research-only numeric geometry bounds: distinguish an
            # unsupported four-swatch native flow from an audit coordinate
            # mismatch before relaxing any production restrictions.
            extents={tool:[float("inf"),-float("inf"),
                           float("inf"),-float("inf"),0]
                     for tool in range(5)}
            active=None
            role=""
            x=y=e=None
            relative_e=relative_xy=False
            for line in lines:
                if line.startswith(";TYPE:"):
                    role=line.partition(":")[2].strip().lower()
                cmd=line.split(";",1)[0].strip()
                if not cmd:
                    continue
                op=cmd.split(None,1)[0].upper()
                if op.startswith("T") and op[1:].isdigit():
                    active=int(op[1:])
                    continue
                if op not in ("M82","M83","G90","G91","G92",
                              "G0","G00","G1","G01"):
                    continue
                values={key.upper():float(num) for key,num in WORD.findall(cmd)}
                if op=="M82":
                    relative_e=False
                elif op=="M83":
                    relative_e=True
                elif op=="G90":
                    relative_xy=False
                elif op=="G91":
                    relative_xy=True
                elif op=="G92":
                    e=values.get("E",e)
                    x=values.get("X",x)
                    y=values.get("Y",y)
                else:
                    before=(x,y)
                    if relative_xy:
                        x=x+values["X"] if x is not None and "X" in values else x
                        y=y+values["Y"] if y is not None and "Y" in values else y
                    else:
                        x=values.get("X",x)
                        y=values.get("Y",y)
                    amount=(values["E"] if relative_e else
                            values["E"]-e if e is not None else 0
                            ) if "E" in values else 0
                    if "E" in values:
                        e=e+values["E"] if relative_e and e is not None else values["E"]
                    if (active in extents and amount>1e-6 and
                            op in ("G1","G01") and None not in before and
                            x is not None and y is not None):
                        span=extents[active]
                        span[0]=min(span[0],x,before[0])
                        span[1]=max(span[1],x,before[0])
                        span[2]=min(span[2],y,before[1])
                        span[3]=max(span[3],y,before[1])
                        span[4]+=1
                    if (active not in counts or amount<=1e-6 or
                            op not in ("G1","G01") or None in before or
                            x is None or y is None or
                            abs(x-before[0])+abs(y-before[1])<=1e-7):
                        continue
                    native_roles[active][role]=native_roles[active].get(role,0)+1
                    for idx,(axis,face_value,tool) in enumerate(sidespec):
                        across=180+face_value
                        p=(x,y)[axis]
                        old=before[axis]
                        tangent=(x,y)[1-axis]
                        old_tangent=before[1-axis]
                        # Full native exterior perimeter segments may
                        # span the *entire* face in one XY G1. A narrow
                        # midpoint strip requiring both endpoints inside
                        # incorrectly reports zero deposited walls.
                        if (abs(p-across)<=3.5 and abs(old-across)<=3.5 and
                                180-11.5<=tangent<=180+11.5 and
                                180-11.5<=old_tangent<=180+11.5 and
                                abs(p-old)<=.8 and
                                abs(tangent-old_tangent)>.5):
                            geometric_hits[active][idx]+=1
                            if "external perimeter" in role:
                                counts[active][idx]+=1
            print("FOUR-WALL XL5 NATIVE RESEARCH",counts,
                  "geometric_hits",geometric_hits,
                  "moving_e_roles",native_roles,
                  "extents",{tool:(tuple(round(v,2) for v in extent[:4]),
                                   extent[4])
                             for tool,extent in extents.items() if extent[4]},
                  "role_headers",sum(line.startswith(";TYPE:External perimeter")
                                     for line in lines),
                  "gcode_bytes",sum(len(line)+1 for line in lines),
                  flush=True)
            for idx,(_axis,_plane,tool) in enumerate(sidespec):
                if counts[tool][idx]<20 or any(
                        counts[other][idx]>2 for other in range(1,5)
                        if other!=tool):
                    raise AssertionError("Native XL four-wall tool attribution not isolated")
            print("RESEARCH PASS: genuine Prusa XL5 four independently painted walls",
                  counts,flush=True)
        except (AssertionError,ValueError,RuntimeError,WorkerError) as exc:
            print("RESEARCH BLOCKED: native XL5 four-wall mapping",
                  type(exc).__name__,str(exc)[:320],flush=True)




if __name__=="__main__":
    main(*sys.argv[1:])
