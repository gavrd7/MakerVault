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

test("sampling and full-layer limitations are labelled separately", () => {
  assert.match(preview, /Full-resolution layer:/);
  assert.match(preview, /Earlier layers are still a sampled orientation reference/);
  assert.match(preview, /only the first/);
  assert.match(preview, /All earlier layers · sampled overview/);
  assert.match(toolpath, /layerDisplay = "current"/);
  assert.match(toolpath, /featureMatchesFocus\(feature, featureFocus\)/);
});
