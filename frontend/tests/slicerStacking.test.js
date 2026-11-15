import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { validateStackPlacement } from "../src/components/slicerStacking.js";

function block(id, x, y, z, width = 20, depth = 20, height = 10) {
  const geometry = new THREE.BoxGeometry(width, depth, height);
  geometry.translate(0, 0, height / 2);
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({side: THREE.DoubleSide}));
  mesh.position.set(x, y, z);
  mesh.updateMatrixWorld(true);
  return { row: {instance_id:id}, mesh };
}
function verdict(...parts) {
  return validateStackPlacement(parts.map(p=>p.row),
    new Map(parts.map(p=>[p.row.instance_id,p.mesh])), parts[0].row.instance_id, 220, 220);
}

test("grounded STL is valid, isolated floating STL is rejected", () => {
  assert.equal(verdict(block("a",0,0,0)).valid, true);
  assert.equal(verdict(block("a",0,0,15)).valid, false);
});
test("touching stacked parts and multi-level support chains are allowed", () => {
  const base=block("base",0,0,0), top=block("top",0,0,10);
  assert.equal(verdict(base,top).valid,true);
  const third=block("third",0,0,20);
  assert.equal(verdict(base,top,third).valid,true);
});
test("gap or XY miss breaks the contact path", () => {
  const base=block("base",0,0,0);
  assert.equal(verdict(base,block("top",0,0,11)).valid,false);
  assert.equal(verdict(base,block("top",50,0,10)).valid,false);
});
test("interpenetrating model volumes are rejected", () => {
  assert.equal(verdict(block("base",0,0,0),block("top",0,0,9)).valid,false);
});
test("a supported top piece cannot stand on an unsupported lower piece", () => {
  assert.equal(verdict(block("lower",0,0,12),block("top",0,0,22)).valid,false);
});
