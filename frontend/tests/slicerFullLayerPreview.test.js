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

test("progressive surface overview reports incomplete loads separately from exact layer inspection", () => {
  assert.match(preview, /gcode\/layers\/\?overview=1&detail=/);
  assert.match(preview, /Whole print · surface overview/);
  assert.match(preview, /slicerWholeModelProgress/);
  assert.match(preview, /wholeModel\.loadedLayers/);
  assert.match(preview, /The overview could not cover all layers/);
  assert.match(preview, /const previous = wholeModel\.segments\.filter/);
  assert.match(preview, /framingSegments=/);
  assert.match(toolpath, /cameraSource = framingSegments\.length/);
  assert.match(toolpath, /layerDisplay = "current"/);
  assert.match(toolpath, /featureMatchesFocus\(feature, featureFocus\)/);

});


test("progressive large prints append surface geometry without polluting exact-layer cache", () => {
  assert.match(preview, /offset \+= 64/);
  assert.match(preview, /overview=1&detail=/);
  assert.match(preview, /Math\.floor\(maxMoves \/ layers\.length\)/);
  assert.match(preview, /Math\.max\(80, Math\.min\(450,/);
  assert.doesNotMatch(preview, /fullLayerCache\.current\.set\(key,item\)/);
  assert.match(preview, /progressiveMode=\{progressiveMode\}/);
  assert.match(preview, /return wholeModel\.segments/);
  assert.match(toolpath, /canAppend/);
  assert.match(toolpath, /startSegment = canAppend \? previous\.count : 0/);
  assert.match(toolpath, /view\.geometryCache = progressiveMode/);
  assert.match(preview, /const naturalLayer = wholeModel\.complete/);
});

test("whole-print layer scrubbing changes a GPU clipping plane rather than geometry", () => {
  assert.match(preview, /const progressiveMode=layerDisplay==="all"/);
  assert.match(preview, /const colours = useMemo\(/);
  assert.match(preview, /layerDisplay !== "current" && step === null/);
  assert.match(toolpath, /renderer\.localClippingEnabled = true/);
  assert.match(toolpath, /const layerClipPlane = new THREE\.Plane/);
  assert.match(toolpath, /view\.layerClipPlane\.constant =/);
  assert.match(toolpath, /const geometryLayer = progressiveMode \? layers\.length-1 : activeLayer/);
  assert.match(toolpath, /const geometryStep = progressiveMode \? -1 : activeStep/);
  assert.match(toolpath, /clippingPlanes: \[view\.layerClipPlane\]/);
  const geometryEffect = toolpath.slice(toolpath.indexOf("const geometryLayer = progressiveMode"));
  assert.match(geometryEffect, /\[segments, layers, geometryLayer, geometryStep,/);
  assert.doesNotMatch(geometryEffect, /\[segments, layers, activeLayer, activeStep,/);
});
