import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { createPaintMesh, selectPaintFaces, applyPaint, validatePaint, pointTriangleDistanceSquared } from "../src/components/slicerColourPainting.js";

test("facets, brush, connected fill and orientation-aware smart fill", () => {
  const geometry = new THREE.BoxGeometry(10, 10, 10).toNonIndexed();
  const mesh = createPaintMesh(geometry);
  assert.equal(mesh.faceCount, 12);
  assert.deepEqual(selectPaintFaces(mesh, { mode: "facet", face: 0 }), [0]);
  assert.equal(selectPaintFaces(mesh, { mode: "fill", face: 0 }).length, 2);
  assert.equal(selectPaintFaces(mesh, { mode: "smart_fill", face: 0, angleDeg: 10 }).length, 2);
  assert.ok(selectPaintFaces(mesh, { mode: "brush", face: 0, radiusMm: 3 }).includes(0));
  geometry.dispose();
});

test("paint is sparse, immutable, erasable, and JSON round-trippable", () => {
  const geometry = new THREE.BoxGeometry(4, 4, 4).toNonIndexed();
  const mesh = createPaintMesh(geometry);
  const first = applyPaint(null, mesh, [0, 1], 3);
  const second = applyPaint(first, mesh, [1], null);
  assert.deepEqual(first.faces, { 0: 3, 1: 3 });
  assert.deepEqual(JSON.parse(JSON.stringify(second)).faces, { 0: 3 });
  assert.deepEqual(validatePaint(second, mesh, [0, 3]).faces, { 0: 3 });
  assert.throws(() => validatePaint(first, mesh, [0]), /not available/);
  geometry.dispose();
});

test("height selection and stale geometry guard", () => {
  const geometry = new THREE.BoxGeometry(10, 10, 10).toNonIndexed();
  const mesh = createPaintMesh(geometry);
  assert.ok(selectPaintFaces(mesh, { mode: "height", minHeightMm: 4, maxHeightMm: 6 }).length > 0);
  const state = applyPaint(null, mesh, [0], 1);
  geometry.translate(1, 0, 0);
  assert.throws(() => applyPaint(state, createPaintMesh(geometry), [0], 1), /geometry changed/);
  geometry.dispose();
});

test("circle follows clicked surface and sphere selects a 3D neighbourhood", () => {
  const geometry = new THREE.BoxGeometry(10,10,10).toNonIndexed();
  const mesh = createPaintMesh(geometry);
  const origin = mesh.centres[0];
  const circle = selectPaintFaces(mesh, {mode:"circle",face:0,radiusMm:8,
    centre:origin,surfaceNormal:mesh.normals[0]});
  const sphere = selectPaintFaces(mesh, {mode:"sphere",face:0,radiusMm:8,centre:origin});
  assert.ok(circle.includes(0));
  assert.ok(sphere.includes(0));
  assert.ok(circle.length <= mesh.faceCount && sphere.length <= mesh.faceCount);
  assert.throws(()=>selectPaintFaces(mesh,{mode:"circle",face:0,radiusMm:-1}),/Invalid paint radius/);
  geometry.dispose();
});

test("conservative fill does not flood an entire connected mesh",()=>{
  const geometry = new THREE.SphereGeometry(8,24,12).toNonIndexed();
  const mesh=createPaintMesh(geometry);
  const painted=selectPaintFaces(mesh,{mode:"fill",face:90});
  assert.ok(painted.length>0 && painted.length<mesh.faceCount/2);
  geometry.dispose();
});

test("circle covers adjacent triangle edges instead of just triangle centres",()=>{
  const geometry=new THREE.PlaneGeometry(20,20,2,2).toNonIndexed();
  const mesh=createPaintMesh(geometry);
  const seed=mesh.centres[0],normal=mesh.normals[0];
  const faces=selectPaintFaces(mesh,{mode:"circle",face:0,centre:seed,
    surfaceNormal:normal,radiusMm:6});
  assert.ok(faces.length>1,"disc should intersect adjacent faces, not just seed triangle");
  assert.ok(faces.length<mesh.faceCount,"disc should not flood the entire plane");
  geometry.dispose();
});

test("planar fill stays on a roof and avoids an adjoining angled shell",()=>{
  const geometry=new THREE.BoxGeometry(20,20,20).toNonIndexed();
  const mesh=createPaintMesh(geometry);
  const filled=selectPaintFaces(mesh,{mode:"fill",face:0});
  assert.equal(filled.length,2);
  assert.ok(filled.every(face=>mesh.normals[face].every((x,i)=>
    Math.abs(x-mesh.normals[0][i])<1e-6)));
  geometry.dispose();
});

test("brush uses triangle surface rather than centroid and does not paint through box",()=>{
  const geometry=new THREE.BoxGeometry(10,10,10).toNonIndexed();
  const mesh=createPaintMesh(geometry);
  const seed=mesh.triangle(0)[0];
  // A 1-mm brush touching the corner of a coarse triangle must select the
  // triangle even when its centroid is much further away.
  const hits=selectPaintFaces(mesh,{mode:"brush",face:0,radiusMm:1,centre:seed});
  assert.ok(hits.includes(0));
  assert.ok(hits.length<mesh.faceCount/2);
  assert.ok(pointTriangleDistanceSquared(seed,...mesh.triangle(0))<1e-8);
  assert.ok(pointTriangleDistanceSquared([100,100,100],...mesh.triangle(0))>0);
  geometry.dispose();
});

test("height range includes triangles crossing interval, not just centroids",()=>{
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute([
    0,0,0, 8,0,20, 0,8,20, // centroid 13.3 outside the band
    0,0,30, 8,0,40, 0,8,40
  ],3));
  const mesh=createPaintMesh(geometry);
  const hits=selectPaintFaces(mesh,{mode:"height",minHeightMm:4,maxHeightMm:8});
  assert.deepEqual(hits,[0]);
  assert.deepEqual(mesh.heightBounds[0],[0,20]);
  geometry.dispose();
});
