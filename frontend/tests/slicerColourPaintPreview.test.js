import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { createPaintMesh, applyPaint } from "../src/components/slicerColourPainting.js";
import { paintPreview } from "../src/components/slicerColourPaintPreview.js";

function model() {
  const geometry = new THREE.BoxGeometry(2, 2, 2).toNonIndexed();
  return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({color:"#abcdef"}));
}

test("painted facets show palette colours while unpainted faces retain base colour", () => {
  const mesh = model();
  const topology = createPaintMesh(mesh.geometry);
  const state = applyPaint(null, topology, [0], 1);
  state.palette = [{color:"#0000ff",label:"Blue"}, {color:"#ff0000",label:"Red"}];
  paintPreview(mesh, {color:"#abcdef",colour_paint:state});
  assert.equal(mesh.material.vertexColors, true);
  const color = mesh.geometry.getAttribute("color");
  const red = new THREE.Color("#ff0000");
  const base = new THREE.Color("#abcdef");
  assert.ok(Math.abs(color.getX(0) - red.r) < 1e-6);
  assert.ok(Math.abs(color.getY(0) - red.g) < 1e-6);
  assert.ok(Math.abs(color.getX(3) - base.r) < 1e-6);
  paintPreview(mesh, {color:"#abcdef"});
  assert.equal(mesh.material.vertexColors, false);
  assert.equal(mesh.geometry.getAttribute("color"), undefined);
  mesh.geometry.dispose(); mesh.material.dispose();
});

test("painting rejects mismatched geometry instead of recolouring unrelated faces", () => {
  const mesh = model();
  const state = applyPaint(null, createPaintMesh(mesh.geometry), [0], 0);
  state.palette = [{color:"#00ff00",label:"Green"}];
  mesh.geometry.translate(1, 0, 0);
  assert.throws(()=>paintPreview(mesh,{colour_paint:state}),/geometry changed|stale/);
  mesh.geometry.dispose(); mesh.material.dispose();
});
