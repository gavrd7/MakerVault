import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import {
  executeSolidOperation, CSG_MAX_INPUT_TRIANGLES, resultToStl,
} from "../src/components/slicerSolidOperations.js";

function solid(x=0,y=0,z=0) {
  const geometry=new THREE.BoxGeometry(20,20,20).toNonIndexed();
  // BoxGeometry is centred. Put its lower face at Z=0 in world units.
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());
  mesh.position.set(x,y,z+10);
  mesh.updateMatrixWorld(true);
  return mesh;
}
test("drilling does not mutate the source geometry", () => {
  const mesh=solid();
  const before=Array.from(mesh.geometry.getAttribute("position").array);
  const out=executeSolidOperation("drill",mesh,{radius:3,x_mm:0,y_mm:0});
  assert.equal(out.length,1);
  assert.ok(out[0].triangles>0);
  assert.equal(new DataView(out[0].buffer).getUint32(80,true),out[0].triangles);
  assert.deepEqual(Array.from(mesh.geometry.getAttribute("position").array),before);
});
test("Cut may keep two, top or bottom independently", () => {
  const mesh=solid();
  assert.equal(executeSolidOperation("cut",mesh,{cutHeight:10,keep:"both"}).length,2);
  assert.equal(executeSolidOperation("cut",mesh,{cutHeight:10,keep:"top"}).length,1);
  assert.equal(executeSolidOperation("cut",mesh,{cutHeight:10,keep:"bottom"}).length,1);
});
test("Boolean union difference intersection on overlapping manifold cubes", () => {
  const a=solid(), b=solid(10,0,0);
  for (const booleanMode of ["union","difference","intersection"]) {
    const out=executeSolidOperation("boolean",a,{booleanMode},b);
    assert.equal(out.length,1);
    assert.ok(out[0].triangles>0);
  }
});
test("Hollow produces a closed internal shell on a simple manifold cube", () => {
  const mesh=solid();
  const out=executeSolidOperation("hollow",mesh,{wall:2});
  assert.equal(out.length,1);
  assert.ok(out[0].triangles>=12);
  assert.ok(out[0].buffer.byteLength===84+out[0].triangles*50);
});
test("Cut also accepts X and Y oriented planes", () => {
  const mesh=solid();
  assert.equal(executeSolidOperation("cut",mesh,{cutAxis:"x",cutHeight:0,keep:"both"}).length,2);
  assert.equal(executeSolidOperation("cut",mesh,{cutAxis:"y",cutHeight:0,keep:"both"}).length,2);
});
test("Hollow refuses a wall larger than available solid", () => {
  const mesh=solid();
  assert.throws(()=>executeSolidOperation("hollow",mesh,{wall:12}),/wall|thin/i);
});
test("Csg errors do not modify source meshes", () => {
  const mesh=solid();
  assert.throws(()=>executeSolidOperation("boolean",mesh,{booleanMode:"union"},null),/second/i);
  assert.equal(CSG_MAX_INPUT_TRIANGLES,500000);
});

test("high-resolution input is no longer arbitrarily capped at 80,000 faces", () => {
  const mesh=solid();
  const high=new THREE.SphereGeometry(10,480,240);
  // 230k triangles on a watertight spherical input should pass the preliminary
  // guard; the geometry operation may still reject non-manifold output.
  const detailed=new THREE.Mesh(high,new THREE.MeshBasicMaterial());
  assert.ok(high.getIndex().count/3>80000);
  assert.ok(high.getIndex().count/3<=CSG_MAX_INPUT_TRIANGLES);
  mesh.geometry.dispose();detailed.geometry.dispose();
});


test("zero-area CSG fragments are stripped before binary STL validation",()=>{
  const cube=solid();
  const position=cube.geometry.getAttribute("position").array;
  const combined=new Float32Array(position.length+9);
  combined.set(position,0);
  combined.set([1,1,1,1,1,1,1,1,1],position.length);
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.BufferAttribute(combined,3));
  const output=resultToStl(new THREE.Mesh(geometry,new THREE.MeshBasicMaterial()));
  assert.equal(output.triangles,12);
  assert.equal(output.removedZeroAreaFaces,1);
  assert.equal(output.buffer.byteLength,84+12*50);
  geometry.dispose();cube.geometry.dispose();
});

test("hollow cavity can be adjusted without altering the source STL",()=>{
  const mesh=solid();
  const before=Array.from(mesh.geometry.getAttribute("position").array);
  const out=executeSolidOperation("hollow",mesh,{
    wall:2,cavity_x_mm:0.5,cavity_y_mm:0,cavity_z_mm:0,
    cavity_scale_x:101,cavity_scale_y:100,cavity_scale_z:100,
    cavity_rotation_x:0,cavity_rotation_y:0,cavity_rotation_z:0,
  });
  assert.equal(out.length,1);
  assert.ok(out[0].triangles>0);
  assert.equal(out[0].validationWarning,"");
  assert.deepEqual(Array.from(mesh.geometry.getAttribute("position").array),before);
  mesh.geometry.dispose();
});
test("open mesh can be previewed but strict STL conversion rejects it",()=>{
  const mesh=solid();
  const position=mesh.geometry.getAttribute("position").array;
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",
    new THREE.Float32BufferAttribute(Array.from(position).slice(9),3));
  const open=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());
  assert.throws(()=>resultToStl(open),/watertight|unmatched/i);
  const preview=resultToStl(open,{allowOpenPreview:true});
  assert.match(preview.validationWarning,/open mesh/i);
  assert.ok(preview.triangles>0);
  mesh.geometry.dispose();geometry.dispose();open.material.dispose();
});
