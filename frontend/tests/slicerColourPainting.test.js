import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { createPaintMesh, selectPaintFaces, applyPaint, validatePaint } from "../src/components/slicerColourPainting.js";

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
