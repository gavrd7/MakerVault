"""Native pinned Prusa 2.9.7 eight-tool independent-head qualification.

Offline test only. Extends the reviewed official XL 5T print profile's
nozzle count in an ephemeral INDX-style candidate. No artificial dock/pickup
or printer start commands are created; hardware transfer is not demonstrated.
All eight tool IDs must deposit inside their own spatial model footprint.
"""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import uuid
import subprocess
import io
import zipfile
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_multitool_project import build_prusa_multitool_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.tests.test_slicer_prusa_plate import cube, item
from core.tests.test_slicer_prusa_3mf import volume
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.service import _decode_payload
from slicer_worker.runner import run_prusa, prusa_command, WorkerError
from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode, _bounds, WORD


def _settings(raw):
    return validate_flat_prusa_preset(raw, kind="printer")


def candidate_printer(source):
    # Official XL 5T defaults to binary G-code; text-only MakerVault worker
    # requires its resolved temporary profile to select ASCII *before* parse.
    source = b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode"
        else line for line in source.splitlines()) + b"\n"
    settings = _settings(source)
    if len(settings["nozzle_diameter"].split(",")) != 5:
        raise ValueError("INDX research expects native 5T baseline profile.")
    settings["nozzle_diameter"] = ",".join(["0.4"] * 8)
    settings["binary_gcode"] = "0"
    settings["single_extruder_multi_material"] = "0"
    # The base is an upstream native independent-head profile. All profile
    # fields are inherited; no physical pickup/docking G-code is fabricated.
    return "".join(f"{k} = {v}\n" for k, v in sorted(settings.items())).encode()


def main(binary, vendor, official=None):
    bundle = Path(vendor).read_bytes()
    digest = hashlib.sha256(bundle).hexdigest()
    xl = flatten_prusa_vendor_preset(
        bundle, kind="printer", name="Original Prusa XL - 5T 0.4 nozzle",
        expected_sha256=digest)
    printer = candidate_printer(xl)
    basic = flatten_prusa_vendor_preset(
        bundle, kind="filament", name="Generic PLA",
        expected_sha256=digest)
    filament_options = validate_flat_prusa_preset(basic,kind="filament")
    profiles = []
    for index in range(8):
        settings = dict(filament_options)
        settings["temperature"] = str(200 + index * 5)
        settings["first_layer_temperature"] = str(205 + index * 5)
        profiles.append("".join(
            f"{k} = {v}\n" for k, v in sorted(settings.items())).encode())
    palette = compile_prusa_filament_palette(printer,profiles)
    process = flatten_prusa_vendor_preset(
        bundle,kind="print",name="0.20mm NORMAL",expected_sha256=digest)
    options = validate_flat_prusa_preset(process,kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        options[key] = "0"
    process = "".join(
        f"{k} = {v}\n" for k,v in sorted(options.items())).encode()
    positions = (-115,-82,-49,-16,17,50,83,116)
    rows = []
    for index,x in enumerate(positions):
        obj=item(x_mm=x)
        obj["asset_id"]="indx-eight-"+str(index)
        rows.append((obj,cube(size=8)))
    tools=list(range(1,9))
    project,topology=build_prusa_multitool_candidate(
        rows,printer_ini=printer,tools=tools,bed_width=360,bed_depth=360)
    assert topology["kind"]=="indx" and topology["logical_tool_count"]==8
    encode=lambda data:base64.b64encode(data).decode()
    payload = {
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":encode(project),"printer_profile":encode(printer),
        "filament_profile":encode(palette),"process_profile":encode(process),
        "prusa_offline_xl":{"tools":tools}}
    receipt=_decode_payload(payload)
    assert receipt["prusa_offline_xl"]["tools"]==tools
    with tempfile.TemporaryDirectory(prefix="prusa-indx-eight-") as root:
        folder=Path(root)
        for name,raw in (
            ("input.3mf",project),("printer.ini",printer),
            ("filament.ini",palette),("process.ini",process)):
            (folder/name).write_bytes(raw)
        (folder/"prusa-offline-xl.marker").write_text("v1")
        run_prusa(Path(binary),folder)
        gcode=(folder/"output.gcode").read_bytes()
        observed=audit_prusa_material_model_gcode(
            gcode,project,printer_ini=printer,tools=tools)
        if (len(observed["correct_extrusion_moves"])!=8
                or min(observed["correct_extrusion_moves"])<20
                or observed["incorrect_extrusion_moves"]!=[0]*8
                or observed["selected_tools"]!=tuple(range(8))):
            raise AssertionError("Native eight-tool deposition did not match all eight models.")
        print("PASS: pinned Prusa 2.9.7 independently deposited T0-T7 on eight models",
              observed,"sha256",hashlib.sha256(gcode).hexdigest(),flush=True)

        # Genuine independent eight-head brim/skirt acceptance. Use the
        # common native numeric process adapter and confirm the requested
        # first-layer role has positive moving extrusion; model attribution
        # must remain exact for all eight independent heads.
        from core.slicer_prusa_process_settings import apply_prusa_process_overrides
        adhesion_process=apply_prusa_process_overrides(
            process,{"brim_width":3,"skirt_loops":2})
        (folder/"process.ini").write_bytes(adhesion_process)
        (folder/"output.gcode").unlink(missing_ok=True)
        run_prusa(Path(binary),folder)
        adhesion_gcode=(folder/"output.gcode").read_bytes()
        adhesion_audit=audit_prusa_material_model_gcode(
            adhesion_gcode,project,printer_ini=printer,tools=tools,
            process_ini=adhesion_process)
        assert adhesion_audit["incorrect_extrusion_moves"]==[0]*8,adhesion_audit
        assert min(adhesion_audit["correct_extrusion_moves"])>=20,adhesion_audit
        assert sum(adhesion_audit["native_first_layer_adhesion_moves"].values())>=10
        print("PASS: genuine eight-head Prusa independent native brim/skirt "
              "with strict model/tool attribution",adhesion_audit,flush=True)
        (folder/"process.ini").write_bytes(process)
        (folder/"output.gcode").unlink(missing_ok=True)

        # Validate modifier/infill and negative-volume combinations through
        # the actual eight-tool worker, not just 3MF metadata acceptance.
        modifier=volume("modifier",{"sparse_infill_density":80})
        modifier.update(width_mm=3,depth_mm=3,height_mm=5,
                        x_mm=positions[0],y_mm=0,z_mm=4)
        cavity=volume("negative",{})
        cavity.update(width_mm=3,depth_mm=3,height_mm=5,
                      x_mm=positions[1],y_mm=0,z_mm=4)
        extended=[]
        for index,(obj,mesh) in enumerate(rows):
            updated=dict(obj)
            if index==0:
                updated["modifier_volumes"]=[modifier]
            if index==1:
                updated["modifier_volumes"]=[cavity]
            if index==2:
                updated["variable_layer_profile"]={
                    "version":1,"bands":[
                        {"from_mm":2,"to_mm":6,"layer_mm":.12}]}
            extended.append((updated,mesh))
        extended_project,_=build_prusa_multitool_candidate(
            extended,printer_ini=printer,tools=tools,bed_width=360,bed_depth=360)
        from slicer_worker.prusa_material_validation import _qualified_topology
        with zipfile.ZipFile(io.BytesIO(extended_project)) as archive:
            config=SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        assert sum(len(obj.findall("volume"))-1 for obj in config.findall("object"))==2
        assert "Metadata/Prusa_Slicer_layer_config_ranges.xml" in zipfile.ZipFile(io.BytesIO(extended_project)).namelist()
        assert _qualified_topology(printer)==(8,False)
        assert validate_prusa_material_candidate(
            extended_project,printer_ini=printer,tools=tools)["objects"]==8
        payload["model"]=encode(extended_project)
        _decode_payload(payload)
        (folder/"input.3mf").write_bytes(extended_project)
        (folder/"output.gcode").unlink()
        run_prusa(Path(binary),folder)
        changed=(folder/"output.gcode").read_bytes()
        changed_audit=audit_prusa_material_model_gcode(
            changed,extended_project,printer_ini=printer,tools=tools)
        assert changed_audit["selected_tools"]==tuple(range(8))
        assert changed_audit["incorrect_extrusion_moves"]==[0]*8
        assert min(changed_audit["correct_extrusion_moves"])>=20
        assert hashlib.sha256(changed).digest()!=hashlib.sha256(gcode).digest()
        print("PASS: eight-tool INDX typed native modifier and negative",
              changed_audit,"sha256",hashlib.sha256(changed).hexdigest(),flush=True)

        if official is not None:
            # A second real-binary slice must accept the actual Prusa-
            # distributed INDX machine profile and its exact toolchange
            # settings, not only the expanded XL independent-head control.
            source=Path(official).read_bytes()
            from slicer_worker.prusa_vendor_profiles import KEY
            outliers=[]
            for raw_line in source.decode("utf-8-sig").splitlines():
                line=raw_line.strip()
                if not line or line.startswith(("#",";","[")) or "=" not in line:
                    continue
                key,_,value=line.partition("=")
                key,value=key.strip(),value.strip()
                if not KEY.fullmatch(key) or len(value)>65536:
                    outliers.append((key[:64],len(value),bool(KEY.fullmatch(key))))
            print("Official INDX vendor extended literals",outliers[:12],
                  "total",len(outliers),flush=True)
            selected=flatten_prusa_vendor_preset(
                source,kind="printer",
                name="Prusa CORE One INDX 8T HF0.4 nozzle",
                expected_sha256=hashlib.sha256(source).hexdigest())
            selected=b"\n".join(
                b"binary_gcode = 0"
                if line.split(b"=",1)[0].strip()==b"binary_gcode"
                else line for line in selected.splitlines())+b"\n"
            # Official 2.5.16 INDX profile references a 3.0-only filament-
            # scoped placeholder. 2.9.7 has retract_length_toolchange for
            # this exact per-tool native G-code parameter. Keep the full
            # upstream toolchange script, changing only the symbol.
            original_token=b"filament_retract_length_toolchange"
            if original_token not in selected:
                raise AssertionError("Expected pinned official INDX placeholder missing.")
            selected=selected.replace(original_token,b"retract_length_toolchange")
            print("INDX 2.9.7 compatibility: replaced official toolchange "
                  "retraction placeholder, kept machine pickup script",flush=True)
            settings=validate_flat_prusa_preset(selected,kind="printer")
            if (len(settings["nozzle_diameter"].split(","))!=8 or
                    settings.get("single_extruder_multi_material","0") not in
                    ("0","false")):
                raise AssertionError("Official INDX eight-tool profile has incompatible topology.")
            actual_positions=(-100,-72,-44,-16,12,40,68,96)
            actual_rows=[]
            for index,x in enumerate(actual_positions):
                native=item(x_mm=x)
                native["asset_id"]="official-indx-"+str(index)
                actual_rows.append((native,cube(size=8)))
            official_project,_=build_prusa_multitool_candidate(
                actual_rows,printer_ini=selected,tools=tools,
                bed_width=250,bed_depth=210)
            payload["printer_profile"]=encode(selected)
            payload["model"]=encode(official_project)
            _decode_payload(payload)
            (folder/"input.3mf").write_bytes(official_project)
            (folder/"printer.ini").write_bytes(selected)
            (folder/"output.gcode").unlink()
            try:
                run_prusa(Path(binary),folder)
            except WorkerError:
                # Controlled upstream CLI fixture only: expose bounded native
                # stderr to diagnose official INDX preset compatibility.
                (folder/"output.gcode").unlink(missing_ok=True)
                proc=subprocess.run(
                    prusa_command(Path(binary),folder),cwd=folder,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    text=True,timeout=150,check=False)
                print("Official INDX CLI exit",proc.returncode,
                      "stdout",proc.stdout[-1400:],
                      "stderr",proc.stderr[-2800:],flush=True)
                raise
            official_gcode=(folder/"output.gcode").read_bytes()
            try:
                observed_official=audit_prusa_material_model_gcode(
                    official_gcode,official_project,
                    printer_ini=selected,tools=tools)
            except WorkerError:
                # Research-only: report synthetic model/tool positive-E
                # attribution without relaxing the production validator.
                boxes=_bounds(official_project,len(tools))
                matrix=[[0]*8 for _ in range(8)]
                picked=set()
                active=None
                x=y=None
                prev_e=0.
                relative=relative_xy=False
                stationary=0
                examples=[]
                for raw_line in official_gcode.decode("utf-8").splitlines():
                    cmd=raw_line.split(";",1)[0].strip()
                    if not cmd: continue
                    op=cmd.split(None,1)[0].upper()
                    if op.startswith("T") and op[1:].isdigit():
                        active=int(op[1:]); picked.add(active)
                        continue
                    if op not in ("M82","M83","G90","G91","G92",
                                  "G0","G00","G1","G01"): continue
                    params={k.upper():float(v) for k,v in WORD.findall(cmd)}
                    if op=="M82": relative=False
                    elif op=="M83": relative=True
                    elif op=="G90": relative_xy=False
                    elif op=="G91": relative_xy=True
                    elif op=="G92":
                        prev_e=params.get("E",prev_e)
                        x=params.get("X",x);y=params.get("Y",y)
                    else:
                        old_x,old_y=x,y
                        if relative_xy:
                            x=x+params["X"] if x is not None and "X" in params else (
                                None if "X" in params else x)
                            y=y+params["Y"] if y is not None and "Y" in params else (
                                None if "Y" in params else y)
                        else:
                            x=params.get("X",x);y=params.get("Y",y)
                        if "E" not in params: continue
                        delta=params["E"] if relative else params["E"]-prev_e
                        prev_e=prev_e+params["E"] if relative else params["E"]
                        if delta<=1e-6 or active not in range(8):
                            continue
                        if (old_x is None or old_y is None or x is None or y is None
                                or abs(x-old_x)+abs(y-old_y)<=1e-7):
                            stationary+=1
                            continue
                        if op not in ("G1","G01"): continue
                        for i,(xmin,xmax,ymin,ymax) in enumerate(boxes):
                            if (xmin-.15<=x<=xmax+.15 and ymin-.15<=y<=ymax+.15 and
                                    xmin-.15<=old_x<=xmax+.15 and
                                    ymin-.15<=old_y<=ymax+.15):
                                matrix[i][active]+=1
                                if active!=i and len(examples)<12:
                                    examples.append({
                                        "model":i,"active":active,
                                        "old":(round(old_x,3),round(old_y,3)),
                                        "new":(round(x,3),round(y,3)),
                                        "e":round(delta,4),"command":cmd[:100]})
                print("Official INDX moving deposited toolpaths: selected tools",
                      sorted(picked),"stationary positive E excluded",stationary,
                      "model/tool matrix",matrix,
                      "wrong-tool segment examples",examples,flush=True)
                raise
            if (observed_official["selected_tools"]!=tuple(range(8)) or
                    observed_official["incorrect_extrusion_moves"]!=[0]*8 or
                    min(observed_official["correct_extrusion_moves"])<20):
                raise AssertionError("Actual official INDX 8T native material attribution failed.")
            print("PASS: actual official Prusa CORE One INDX 8T profile "
                  "slices all eight tool identities",observed_official,flush=True)
            # Same eight-head official printer/palette, no invented printer
            # scripts: apply MakerVault's existing native facet encoder and
            # independent worker colour audits to T1 (and T1/T2). Higher
            # heads still remain available for whole-model tool assignment.
            from scripts.prusa_generate_mmu_paint import fixture as painted_fixture
            from core.slicer_prusa_colour_project import build_prusa_colour_candidate
            from slicer_worker.prusa_offline_contract import validate_prusa_offline_xl_colour_inputs
            from slicer_worker.prusa_colour_gcode_audit import (
                audit_prusa_xl_colour_gcode, audit_prusa_dual_colour_gcode)
            stl,_mesh,_states,paint=painted_fixture(include_paint=True)
            row={"asset_id":"official-indx-paint","x_mm":0,"y_mm":0,
                 "z_mm":0,"rotation_deg":0,"scale_percent":100,
                 "colour_paint":paint}
            (folder/"prusa-offline-xl.marker").unlink(missing_ok=True)
            (folder/"prusa-offline-xl-colour.marker").write_text("v1")
            coloured=build_prusa_colour_candidate(
                row,stl,printer_ini=selected,colour_tool_indices={1:1},
                bed_width=250,bed_depth=210)
            validate_prusa_offline_xl_colour_inputs(
                project=coloured,printer=selected,filament=palette,
                process=process,tool=1)
            payload.pop("prusa_offline_xl")
            payload["prusa_offline_xl_colour"]={"tool":1}
            payload["model"]=encode(coloured)
            _decode_payload(payload)
            (folder/"input.3mf").write_bytes(coloured)
            (folder/"output.gcode").unlink(missing_ok=True)
            run_prusa(Path(binary),folder)
            face_gcode=(folder/"output.gcode").read_bytes()
            face_receipt=audit_prusa_xl_colour_gcode(
                face_gcode,coloured,printer_ini=selected,tool=1)
            assert face_receipt["painted_wall_moves"][1]["front"]>=20,face_receipt
            assert face_receipt["painted_wall_moves"][0]["back"]>=20,face_receipt
            assert not face_receipt["wipe_tower"],face_receipt
            print("PASS: actual official eight-head INDX native T1 face paint",
                  face_receipt,flush=True)

            from core.slicer_plate_3mf import _triangles
            from core.slicer_native_support_paint import _fingerprint
            triangles=list(_triangles(stl))
            lo=[min(p[a] for tri in triangles for p in tri) for a in range(3)]
            hi=[max(p[a] for tri in triangles for p in tri) for a in range(3)]
            origin=((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2])
            local=[[tuple(p[a]-origin[a] for a in range(3)) for p in tri]
                   for tri in triangles]
            back=[{"face":i,"polygon":[list(p) for p in tri]}
                  for i,tri in enumerate(local)
                  if all(abs(p[1]-10)<.00001 for p in tri)]
            assert len(back)==2, "INDX native rear wall is incomplete"
            dual={**paint,"signature":_fingerprint(local),
                  "palette":[*paint["palette"],
                             {"color":"#fadd4d","label":"INDX T2"}],
                  "regions":[*paint["regions"],{"slot":2,"patches":back}]}
            two=build_prusa_colour_candidate(
                {**row,"colour_paint":dual},stl,printer_ini=selected,
                colour_tool_indices={1:1,2:2},bed_width=250,bed_depth=210)
            validate_prusa_offline_xl_colour_inputs(
                project=two,printer=selected,filament=palette,
                process=process,tools=[1,2])
            payload["prusa_offline_xl_colour"]={"tools":[1,2]}
            payload["model"]=encode(two)
            _decode_payload(payload)
            (folder/"input.3mf").write_bytes(two)
            (folder/"output.gcode").unlink(missing_ok=True)
            run_prusa(Path(binary),folder)
            dual_gcode=(folder/"output.gcode").read_bytes()
            try:
                dual_receipt=audit_prusa_dual_colour_gcode(
                    dual_gcode,two,printer_ini=selected,tools=(1,2),tower=None)
            except WorkerError:
                from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
                counts=painted_external_walls(
                    dual_gcode,center_x=125,center_y=105)
                # Synthetic pinned-vendor fixture only: numeric counts,
                # no private native G-code or toolchange scripts in logs.
                print("OFFICIAL INDX dual native wall counts",counts,flush=True)
                raise
            assert dual_receipt["wall_moves"][1]["front"]>=20,dual_receipt
            assert dual_receipt["wall_moves"][2]["back"]>=20,dual_receipt
            assert not dual_receipt["wipe_tower"],dual_receipt
            print("PASS: actual official eight-head INDX native opposing T1/T2 paint",
                  dual_receipt,flush=True)





if __name__=="__main__":
    main(*sys.argv[1:])
