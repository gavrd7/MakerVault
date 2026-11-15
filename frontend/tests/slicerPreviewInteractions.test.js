import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const source = fs.readFileSync(path.join(root, "SlicerGcodePreview.jsx"), "utf8");

test("post-slice preview exposes vertical layer and full-resolution layer-step controls", () => {
  assert.match(source, /id="slice-layer-slider"/);
  assert.match(source, /id="slice-step-slider"/);
  assert.match(source, /onChange=\{e => \{ setLayer\(Number\(e\.target\.value\)\); setStep\(null\); \}\}/);
  assert.match(source, /Full-resolution/);
  assert.match(source, /layer move/);
  assert.match(source, /Show entire selected layer/);
  assert.match(source, /<SlicerToolpath3D segments=\{displaySegments\}/);
  const renderer = fs.readFileSync(path.join(root, "SlicerToolpath3D.jsx"), "utf8");
  assert.match(renderer, /marker\.position\.set\(\.\.\.lastStep\)/);
});

test("feature visibility is configurable while unavailable numeric modes remain disabled", () => {
  assert.match(source, /Visible extrusion features/);
  assert.match(source, /visible\[feature\] !== false/);
  assert.match(source, /disabled=\{!mode\.supported\}/);
  for (const mode of ["Speed", "Flow", "Temperature", "Acceleration", "Line width"])
    assert.match(source, new RegExp('label: "' + mode + '", supported: false'));
});

test("bounded path sample is never represented as complete G-code execution", () => {
  assert.match(source, /Earlier layers are still a sampled orientation reference/);
  assert.match(source, /Partial samples can still omit fine toolpaths/);
  assert.match(source, /not a complete/);
  assert.match(source, /estimates/);
});

test("visualiser renders 3D extrusion geometry rather than top-down SVG", () => {
  const parent = fs.readFileSync(path.join(root, "SlicerGcodePreview.jsx"), "utf8");
  const renderer = fs.readFileSync(path.join(root, "SlicerToolpath3D.jsx"), "utf8");
  assert.match(parent, /<SlicerToolpath3D segments=\{displaySegments\}/);
  assert.doesNotMatch(parent, /<svg viewBox="0 0 600 600"/);
  assert.match(renderer, /new THREE\.WebGLRenderer/);
  assert.match(renderer, /new OrbitControls\(camera, renderer\.domElement\)/);
  assert.match(renderer, /new THREE\.LineSegments\(geometry/);
  assert.match(renderer, /new THREE\.Vector3\(segment\[0\], segment\[4\], segment\[1\]\)/);
  assert.match(renderer, /marker\.position\.set\(\.\.\.lastStep\)/);
  assert.match(renderer, /observer\?\.disconnect\(\)/);
  assert.match(renderer, /renderer\.dispose\(\)/);
});
