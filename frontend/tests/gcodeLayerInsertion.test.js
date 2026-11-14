import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { layerBoundaries, insertGcodeAfterLayer } from "../src/utils/gcodeLayerInsertion.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const view = fs.readFileSync(path.join(root, "SlicerGcodePreview.jsx"), "utf8");
const modal = fs.readFileSync(path.join(root, "GcodeViewerModal.jsx"), "utf8");
const workbench = fs.readFileSync(path.join(root, "SlicerWorkbench.jsx"), "utf8");

const ORIGINAL = [
  ";FLAVOR:Marlin",
  ";LAYER_CHANGE", ";Z:0.20",
  "G1 X10 Y10 E0.2",
  ";LAYER_CHANGE", ";Z:0.40",
  "G1 X15 Y15 E0.4",
  ";LAYER_CHANGE", ";Z:0.60",
  "G1 X20 Y20 E0.6", "",
].join("\n");

test("insertion after selected layer is precisely before next layer marker", () => {
  const copy = ORIGINAL;
  const result = insertGcodeAfterLayer(copy, 0.2, 0.4, "M0 ; deliberate pause");
  assert.equal(copy, ORIGINAL);
  assert.ok(result.text.indexOf("G1 X10 Y10 E0.2") < result.text.indexOf("M0 ; deliberate pause"));
  assert.ok(result.text.indexOf("M0 ; deliberate pause") < result.text.indexOf(";LAYER_CHANGE\n;Z:0.40"));
  assert.equal((result.text.match(/;LAYER_CHANGE/g) || []).length, 3);
  assert.equal(layerBoundaries(ORIGINAL).length, 3);
  assert.equal(layerBoundaries(result.text).length, 3);
});

test("CRLF layers preserve original newline convention", () => {
  const input = ORIGINAL.replace(/\n/g, "\r\n");
  const result = insertGcodeAfterLayer(input, 0.4, 0.6, "M0\nG4 S2");
  assert.match(result.code, /M0\r\nG4 S2/);
  assert.equal(result.text.replace(/\r\n/g, "").includes("\n"), false);
});

test("missing or ambiguous native layers cannot insert arbitrary commands", () => {
  assert.throws(() => insertGcodeAfterLayer("G1 Z0.2\nG1 Z0.4", 0.2, 0.4, "M0"), /verifiable/);
  assert.throws(() => insertGcodeAfterLayer(ORIGINAL, 0.2, 0.8, "M0"), /does not match/);
  assert.throws(() => insertGcodeAfterLayer(ORIGINAL, 0.6, 0.8, "M0"), /does not match/);
  assert.throws(() => insertGcodeAfterLayer(ORIGINAL, 0.2, 0.4, "M0\0"), /plain-text/);
  const duplicate = ORIGINAL.replace(";LAYER_CHANGE\n;Z:0.60", ";LAYER_CHANGE\n;Z:0.40");
  assert.throws(() => insertGcodeAfterLayer(duplicate, 0.4, 0.6, "M0"), /uniquely/);
});

test("existing slicer visualiser exposes layer editing without printer submission", () => {
  assert.match(view, /Add G-code at selected layer/);
  assert.match(view, /nextZ=\{layers\[currentLayer \+ 1\]\}/);
  assert.match(view, /<GcodeLayerInsert/);
  assert.match(modal, /canEdit=\{canEdit\}/);
  assert.match(workbench, /canEdit=\{canPrepare\} onSaved=\{refresh\}/);
  const dialog = fs.readFileSync(path.join(root, "GcodeLayerInsert.jsx"), "utf8");
  assert.match(dialog, /Save as new G-code version/);
  assert.match(dialog, /gcode\/source\//);
  assert.match(dialog, /gcode\/source\//);
  assert.match(dialog, /versions\//);
  assert.doesNotMatch(dialog, /\/printing\/.*submit/);
});
