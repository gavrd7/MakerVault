import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const source = fs.readFileSync(path.join(root, "SlicerGcodePreview.jsx"), "utf8");

test("post-slice preview exposes vertical layer and horizontal sampled step controls", () => {
  assert.match(source, /id="slice-layer-slider"/);
  assert.match(source, /id="slice-step-slider"/);
  assert.match(source, /onChange=\{e => \{ setLayer\(Number\(e\.target\.value\)\); setStep\(null\); \}\}/);
  assert.match(source, /Sampled toolhead step/);
  assert.match(source, /Show entire sampled layer/);
  assert.match(source, /Current sampled toolhead location/);
});

test("feature visibility is configurable while unavailable numeric modes remain disabled", () => {
  assert.match(source, /Visible extrusion features/);
  assert.match(source, /visible\[feature\] !== false/);
  assert.match(source, /disabled=\{!mode\.supported\}/);
  for (const mode of ["Speed", "Flow", "Temperature", "Acceleration", "Line width"])
    assert.match(source, new RegExp('label: "' + mode + '", supported: false'));
});

test("bounded path sample is never represented as complete G-code execution", () => {
  assert.match(source, /sampled extrusion moves only/);
  assert.match(source, /paths can be omitted/);
  assert.match(source, /not a complete/);
  assert.match(source, /estimates/);
});
