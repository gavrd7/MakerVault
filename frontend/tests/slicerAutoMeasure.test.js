import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as THREE from "three";
import { detectMeshMeasurement, formatDetectedMeasurement } from "../src/components/slicerAutoMeasure.js";

const components = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const plate = fs.readFileSync(path.join(components, "SlicerPlateEditor.jsx"), "utf8");
const toolbar = fs.readFileSync(path.join(components, "SlicerPrepareWorkspace.jsx"), "utf8");
const styles = fs.readFileSync(path.join(components, "../styles.css"), "utf8");

function square() {
  const geometry = new THREE.BufferGeometry();
  // Two adjacent triangles forming one 10 x 10 mm planar patch.
  geometry.setAttribute("position", new THREE.Float32BufferAttribute([
    0, 0, 0, 10, 0, 0, 10, 10, 0,
    0, 0, 0, 10, 10, 0, 0, 10, 0,
  ], 3));
  const mesh = new THREE.Mesh(geometry);
  mesh.updateMatrixWorld();
  return mesh;
}

test("auto detect finds a connected planar region rather than an individual triangle", () => {
  const mesh = square();
  const hit = { faceIndex: 0, face: { a: 0, b: 1, c: 2 }, point: new THREE.Vector3(5, 5, 0) };
  const result = detectMeshMeasurement(mesh, hit, 0.1);
  assert.equal(result.kind, "face");
  assert.equal(result.triangles, 2);
  assert.ok(Math.abs(result.value - 100) < 0.001);
  mesh.geometry.dispose();
});

test("auto detect reports a boundary mesh edge and converts units", () => {
  const mesh = square();
  const hit = { faceIndex: 0, face: { a: 0, b: 1, c: 2 }, point: new THREE.Vector3(5, 0.1, 0) };
  const result = detectMeshMeasurement(mesh, hit, 0.5);
  assert.equal(result.kind, "edge");
  assert.ok(Math.abs(result.value - 10) < 0.001);
  assert.equal(formatDetectedMeasurement(result, "mm"), "10.000 mm");
  assert.equal(formatDetectedMeasurement(result, "in"), "0.394 in");
  mesh.geometry.dispose();
});

test("auto detection is wired into toolbar and read-only viewport controls", () => {
  assert.match(toolbar, /Auto-detect mesh edge \/ face/);
  assert.match(plate, /detectMeshMeasurement\(target, hit, tolerance\)/);
  assert.match(plate, /DetectedFeature|detectedFeature/);
  assert.match(plate, /formatDetectedMeasurement\(detectedFeature, measureUnit\)/);
});

test("measurement panel is anchored at the camera toolbar level", () => {
  assert.match(styles, /\.slicerPlateCanvasColumn \{ position: relative; \}/);
  assert.match(styles, /\.slicerPlateCanvasViewport \{ position: static; \}/);
  assert.match(styles, /\.slicerViewportMeasurement \{\s*position: absolute;\s*top: 18px;/);
  assert.match(styles, /@media \(max-width: 700px\)/);
});
