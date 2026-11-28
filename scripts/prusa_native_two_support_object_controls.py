"""Research PrusaSlicer 2.9.7 native per-object support-off controls.

Known two-object support case leaks support into unpainted right neighbour.
Test whether an upstream native per-object support disable can isolate it.
Research-only: no production 3MF acceptance or printer submission changes.
"""
import hashlib
import io
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import zipfile
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from scripts.prusa_native_multi_support_smoke import count_native_support

CONFIG="Metadata/Slic3r_PE_model.config"
MODEL="3D/3dmodel.model"
NS="{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
SUPPORT="{http://schemas.slic3r.org/3mf/2017/06}custom_supports"


def block_unpainted_object(project):
    """Research explicit native blocker facets, preserving the painted mesh."""
    with zipfile.ZipFile(io.BytesIO(project)) as original:
        parts={name:original.read(name) for name in original.namelist()}
    root=SafeET.fromstring(parts[MODEL])
    meshes=[obj.findall(".//"+NS+"triangle") for obj in root.findall(".//"+NS+"object")]
    meshes=[mesh for mesh in meshes if mesh]
    painted=[mesh for mesh in meshes if any(t.get(SUPPORT)=="4" for t in mesh)]
    plain=[mesh for mesh in meshes if all(t.get(SUPPORT) is None for t in mesh)]
    if len(meshes)!=2 or len(painted)!=1 or len(plain)!=1:
        raise AssertionError("Expected one enforced mesh and one unpainted mesh.")
    for triangle in plain[0]:
        triangle.set(SUPPORT,"8")
    ET.register_namespace("",NS[1:-1])
    ET.register_namespace("slic3rpe",SUPPORT[1:].split("}")[0])
    parts[MODEL]=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as target:
        for name,body in parts.items():
            target.writestr(name,body)
    return output.getvalue()



def block_unpainted_with_native_volume(project):
    """Research a separate Prusa SupportBlocker volume around the neighbour.

    Painted blockers on model facets and per-object support overrides do not
    necessarily suppress supports projected into an adjacent object's volume.
    Keep this completely outside production admission until actual native
    2.9.7 G-code independently proves spatial isolation.
    """
    with zipfile.ZipFile(io.BytesIO(project)) as original:
        parts = {name: original.read(name) for name in original.namelist()}
    model = SafeET.fromstring(parts[MODEL])
    config = SafeET.fromstring(parts[CONFIG])
    objects = model.findall("./" + NS + "resources/" + NS + "object")
    entries = config.findall("./object")
    if len(objects) != 2 or len(entries) != 2:
        raise AssertionError("Native blocker research requires two separate objects.")
    mesh = objects[1].find(NS + "mesh")
    vertices = mesh.find(NS + "vertices") if mesh is not None else None
    triangles = mesh.find(NS + "triangles") if mesh is not None else None
    if vertices is None or triangles is None or len(triangles) == 0:
        raise AssertionError("Unpainted Prusa model has no printable mesh.")
    if len(entries[1].findall("./volume")) != 1:
        raise AssertionError("Native blocker research requires one printable volume.")
    position = [(float(v.get("x")), float(v.get("y")), float(v.get("z")))
                for v in vertices]
    if not position:
        raise AssertionError("Unpainted Prusa mesh has no vertices.")
    xlo, xhi = min(p[0] for p in position)-3, max(p[0] for p in position)+3
    ylo, yhi = min(p[1] for p in position)-3, max(p[1] for p in position)+3
    zlo, zhi = 0, max(p[2] for p in position)+3
    # Deliberately cover all support below the entire neighbouring object,
    # not just its printed walls or painted triangular facets.
    corners = [
        (xlo,ylo,zlo), (xhi,ylo,zlo), (xhi,yhi,zlo), (xlo,yhi,zlo),
        (xlo,ylo,zhi), (xhi,ylo,zhi), (xhi,yhi,zhi), (xlo,yhi,zhi),
    ]
    start_vertex = len(vertices)
    start_face = len(triangles)
    for x,y,z in corners:
        ET.SubElement(vertices, NS+"vertex", {
            "x": format(x, ".5f"), "y": format(y, ".5f"),
            "z": format(z, ".5f")})
    faces = (
        (0,2,1),(0,3,2), (4,5,6),(4,6,7),
        (0,1,5),(0,5,4), (1,2,6),(1,6,5),
        (2,3,7),(2,7,6), (3,0,4),(3,4,7),
    )
    for a,b,c in faces:
        ET.SubElement(triangles, NS+"triangle", {
            "v1": str(start_vertex+a),
            "v2": str(start_vertex+b), "v3": str(start_vertex+c)})
    volume = ET.SubElement(entries[1], "volume", {
        "firstid": str(start_face), "lastid": str(len(triangles)-1)})
    ET.SubElement(volume, "metadata", {
        "type": "volume", "key": "volume_type", "value": "SupportBlocker"})
    ET.register_namespace("", NS[1:-1])
    parts[MODEL] = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    parts[CONFIG] = ET.tostring(config, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, body in parts.items():
            target.writestr(name, body)
    return output.getvalue()


def disable_unpainted_object(project, keys):
    with zipfile.ZipFile(io.BytesIO(project)) as original:
        parts={name:original.read(name) for name in original.namelist()}
    root=SafeET.fromstring(parts[CONFIG])
    rows=root.findall("./object")
    if len(rows)!=2:
        raise AssertionError("Expected exactly two Prusa project objects.")
    other=rows[1]
    for key,value in keys.items():
        ET.SubElement(other,"metadata",{
            "type":"object","key":key,"value":str(value),
        })
    parts[CONFIG]=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as target:
        for name,body in parts.items():
            target.writestr(name,body)
    return output.getvalue()


def main(binary,vendor,directory):
    source=Path(vendor).read_bytes()
    digest=hashlib.sha256(source).hexdigest()
    project=(Path(directory)/"left.3mf").read_bytes()
    with TemporaryDirectory(prefix="prusa-support-object-controls-") as temp:
        work=Path(temp)
        args=[]
        for kind,name in (("printer","Original Prusa i3 MK2S"),
                          ("filament","Generic PLA"),
                          ("print","0.20mm NORMAL")):
            preset=flatten_prusa_vendor_preset(
                source,kind=kind,name=name,expected_sha256=digest)
            if kind=="print":
                preset=b"\n".join(line for line in preset.splitlines()
                    if line.split(b"=",1)[0].strip() not in (
                        b"support_material",b"support_material_auto"))+b"\n"
                preset+=b"support_material = 1\nsupport_material_auto = 0\n"
            file=work/(kind+".ini")
            file.write_bytes(preset)
            args.extend(["--load",str(file)])
        variants={
            "baseline":project,
            "right-off":disable_unpainted_object(project,{
                "support_material":0,
            }),
            "right-off-auto":disable_unpainted_object(project,{
                "support_material":0,"support_material_auto":0,
            }),
        }
        variants["right-blocker-volume"]=block_unpainted_with_native_volume(project)
        variants["right-blocker-volume-off"]=disable_unpainted_object(
            variants["right-blocker-volume"], {"support_material":0,"support_material_auto":0})
        variants["right-blocked-facets"]=block_unpainted_object(project)
        variants["right-blocked-facets-off"]=disable_unpainted_object(
            variants["right-blocked-facets"], {"support_material":0,"support_material_auto":0})
        for name,archive in variants.items():
            infile=work/(name+".3mf")
            outfile=work/(name+".gcode")
            infile.write_bytes(archive)
            subprocess.run([binary,*args,"--export-gcode","--dont-arrange",
                            "--output",str(outfile),str(infile)],
                           cwd=work,check=True,timeout=300)
            counters=count_native_support(outfile.read_bytes())
            print("Research Prusa per-object native support override",
                  name,counters,flush=True)
            if name=="baseline" and counters["left"]>50 and counters["right"]<=2:
                print("PASS: moving-support classifier excludes stationary E recovery; "
                      "no neighbour support deposition to block.", flush=True)
                return
            if name=="baseline" and not counters["right"]>5:
                raise AssertionError("Baseline lacks painted support or isolation evidence.")
            if name!="baseline" and counters["left"]>50 and counters["right"]<5:
                print("PASS: Prusa per-object support-off isolates right neighbour",
                      name,flush=True)
                return
        raise AssertionError("Prusa object-local support-off and explicit blocker facets did not isolate neighbour.")


if __name__=="__main__":
    main(*sys.argv[1:])
