import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { buildSectionCapGeometry } from "../src/components/slicerSectionCaps.js";

function sectionArea(geometry) {
  if(!geometry)return 0;
  const p=geometry.getAttribute("position"),index=geometry.getIndex();
  const a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3();
  let sum=0;
  const count=index?index.count:p.count;
  for(let i=0;i<count;i+=3){
    a.fromBufferAttribute(p,index?index.getX(i):i);
    b.fromBufferAttribute(p,index?index.getX(i+1):i+1);
    c.fromBufferAttribute(p,index?index.getX(i+2):i+2);
    sum+=new THREE.Vector3().crossVectors(b.sub(a),c.sub(a)).length()/2;
  }
  return sum;
}
function ringMesh() {
  const outer=new THREE.BoxGeometry(20,20,20).toNonIndexed();
  const inner=new THREE.BoxGeometry(10,10,20).toNonIndexed();
  const op=outer.getAttribute("position"),ip=inner.getAttribute("position");
  const values=[];
  for(let i=0;i<op.count;i++)values.push(op.getX(i),op.getY(i),op.getZ(i));
  // Cavity walls have the inverse winding of the outside surface.
  for(let i=0;i<ip.count;i+=3)for(const j of [2,1,0])
    values.push(ip.getX(i+j),ip.getY(i+j),ip.getZ(i+j));
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute(values,3));
  outer.dispose();inner.dispose();
  return new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());
}
test("section view fills the interior of a solid box along Z",()=>{
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(20,10,30));
  const plane=new THREE.Plane(new THREE.Vector3(0,0,-1),0);
  const cap=buildSectionCapGeometry(mesh,plane);
  assert.ok(cap);
  assert.ok(Math.abs(sectionArea(cap)-200)<0.1);
  cap.dispose();mesh.geometry.dispose();
});
test("section view follows the X axis without distorting area",()=>{
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(20,10,30));
  const plane=new THREE.Plane(new THREE.Vector3(-1,0,0),0);
  const cap=buildSectionCapGeometry(mesh,plane);
  assert.ok(cap);
  assert.ok(Math.abs(sectionArea(cap)-300)<0.1);
  cap.dispose();mesh.geometry.dispose();
});
test("section view respects genuine hollow cavities",()=>{
  const mesh=ringMesh();
  const plane=new THREE.Plane(new THREE.Vector3(0,0,-1),0);
  const cap=buildSectionCapGeometry(mesh,plane);
  assert.ok(cap);
  assert.ok(Math.abs(sectionArea(cap)-300)<0.2,
    "a 10x10 cavity must remain open inside the 20x20 shell");
  cap.dispose();mesh.geometry.dispose();mesh.material.dispose();
});
test("section cap returns null when section misses the model",()=>{
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(10,10,10));
  const plane=new THREE.Plane(new THREE.Vector3(0,0,-1),100);
  assert.equal(buildSectionCapGeometry(mesh,plane),null);
  mesh.geometry.dispose();
});

test("section inspector retains old cap geometry during slider updates",async()=>{
  const {readFileSync}=await import("node:fs");
  const {fileURLToPath}=await import("node:url");
  const {dirname,resolve}=await import("node:path");
  const editor=readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),
    "../src/components/SlicerPlateEditor.jsx"),"utf8");
  assert.match(editor,/const sectionCapsRef = useRef\(new Map\(\)\)/);
  assert.match(editor,/previous\.cap\.geometry=geometry/);
  assert.match(editor,/clearTimeout\(handle\)/);
  assert.doesNotMatch(editor,/const caps=\[\];[\s\S]*?caps\.push\(cap\)/);
});
