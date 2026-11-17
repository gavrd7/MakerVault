import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const read = name => fs.readFileSync(path.join(root, name), "utf8");
const preview = read("SlicerGcodePreview.jsx");
const toolpath = read("SlicerToolpath3D.jsx");
const viewer = read("GcodeViewerModal.jsx");

test("preview retrieves exact selected layer from stored original G-code", () => {
  assert.match(viewer, /<SlicerGcodePreview fileId=\{file\.id\}/);
  assert.match(preview, /gcode\/layer\/\?z=/);
  assert.match(preview, /credentials: "same-origin"/);
  assert.match(preview, /controller\.abort\(\)/);
  assert.match(preview, /fullLayerCache\.current\.size > 12/);
  assert.match(preview, /const current = layerSegments/);
  assert.match(preview, /if \(layerDisplay === "current"\) return current/);
  assert.match(preview, /setLayerBusy\(true\)/);
});

test("progressive geometry uses exact layers and explicitly reports partial loads", () => {
  assert.match(preview, /gcode\/layers\/\?zs=/);
  assert.match(preview, /Whole print · progressive full resolution/);
  assert.match(preview, /slicerWholeModelProgress/);
  assert.match(preview, /wholeModel\.loadedLayers/);
  assert.match(preview, /Whole-model geometry reached the device preview budget/);
  assert.match(preview, /const previous = wholeModel\.segments\.filter/);
  assert.match(preview, /framingSegments=/);
  assert.match(toolpath, /cameraSource = framingSegments\.length/);
  assert.match(toolpath, /layerDisplay = "current"/);
  assert.match(toolpath, /featureMatchesFocus\(feature, featureFocus\)/);

});
