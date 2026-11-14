import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { meshesProjectivelyOverlapXY } from "../src/components/slicerMeshFootprints.js";

function meshAt(x,y,z=0){
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(10,10,10));
  mesh.position.set(x,y,z);return mesh;
}
function multipartMesh() {
  const parts=[meshAt(-20,0),meshAt(20,0)];
  const vertices=[];
  for(const mesh of parts){
    mesh.updateMatrixWorld(true);
    const geometry=mesh.geometry.toNonIndexed();
    const attr=geometry.getAttribute("position");
    const point=new THREE.Vector3();
    for(let i=0;i<attr.count;i++){
      point.fromBufferAttribute(attr,i).applyMatrix4(mesh.matrixWorld);
      vertices.push(point.x,point.y,point.z);
    }
    geometry.dispose();mesh.geometry.dispose();
  }
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute(vertices,3));
  return new THREE.Mesh(geometry);
}
test("does not report an empty gap inside a multipart mesh as overlap",()=>{
  const assembly=multipartMesh();
  const gap=meshAt(0,0);
  assert.equal(meshesProjectivelyOverlapXY(assembly,gap),false);
  assembly.geometry.dispose();gap.geometry.dispose();
});
test("detects genuine projected occupied-area collisions",()=>{
  const assembly=multipartMesh();
  const overlap=meshAt(-20,0);
  assert.equal(meshesProjectivelyOverlapXY(assembly,overlap),true);
  assembly.geometry.dispose();overlap.geometry.dispose();
});
test("objects that only touch edges are not overlapping",()=>{
  const a=meshAt(0,0),b=meshAt(10,0);
  assert.equal(meshesProjectivelyOverlapXY(a,b),false);
  a.geometry.dispose();b.geometry.dispose();
});
