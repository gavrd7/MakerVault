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

test("progressive full-quality preview reports limited geometry separately from exact layer inspection", () => {
  assert.match(preview, /gcode\/layers\/\?quality=full&zs=/);
  assert.match(preview, /Whole print · full-detail paths/);
  assert.match(preview, /slicerWholeModelProgress/);
  assert.match(preview, /wholeModel\.loadedLayers/);
  assert.match(preview, /The preview reached its resource budget/);
  assert.match(preview, /const previous = wholeModel\.chunks\.flat\(\)\.filter/);
  assert.match(preview, /framingSegments=/);
  assert.match(toolpath, /cameraSource = framingSegments\.length/);
  assert.match(toolpath, /layerDisplay = "current"/);
  assert.match(toolpath, /featureMatchesFocus\(feature, featureFocus\)/);

});


test("progressive large prints append complete geometry without polluting exact-layer cache", () => {
  assert.match(preview, /offset \+= requested\.length/);
  assert.match(preview, /quality=full&zs=/);
  assert.match(preview, /&page_start=/);
  assert.doesNotMatch(preview, /const maxMoves = 1500000/);
  assert.match(preview, /progressiveLayerBatchSize/);
  assert.match(preview, /const EMPTY_PATHS = Object\.freeze\(\[\]\)/);
  assert.match(preview, /full-detail/i);
  assert.doesNotMatch(preview, /fullLayerCache\.current\.set\(key,item\)/);
  assert.match(preview, /progressiveMode=\{progressiveMode\}/);
  assert.match(preview, /if \(progressiveMode\) return EMPTY_PATHS/);
  assert.match(preview, /segmentChunks=\{progressiveMode \? wholeModel\.chunks : \[\]\}/);
  assert.match(toolpath, /canAppend/);
  assert.match(toolpath, /const startChunk=canAppend \? previous\.chunkCount : 0/);
  assert.match(toolpath, /const batches=progressiveMode \? segmentChunks\.slice\(startChunk\) : \[segments\]/);
  assert.match(toolpath, /view\.geometryCache = progressiveMode/);
  assert.match(preview, /const naturalLayer = wholeModel\.complete/);
});

test("cold preview requests asynchronous preparation and has direct fallback", () => {
  assert.match(preview, /"&warm=1"/);
  assert.match(preview, /response\.status === 202/);
  assert.match(preview, /"&direct=1"/);
  assert.doesNotMatch(preview, /"&all_zs="/);

});

test("transient mobile network failures retry smaller exact batches without discarding loaded layers", () => {
  assert.match(preview, /loadCheckpoint\.current/);
  assert.match(preview, /for \(let offset = completed;/);
  assert.match(preview, /requestSize = Math\.max\(1, Math\.floor\(requestSize \/ 2\)\)/);
  assert.match(preview, /checkpoint\.completed = completed/);
  assert.match(preview, /Retry remaining layers/);
  assert.match(preview, /setRetryGeneration\(value => value \+ 1\)/);
  assert.doesNotMatch(preview, /const maxMoves = 1500000/);
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
  assert.match(toolpath, /clippingPlanes:\s*\[view\.layerClipPlane\]/);
  const geometryEffect = toolpath.slice(toolpath.indexOf("const geometryLayer = progressiveMode"));
  assert.match(geometryEffect, /\[segments, segmentChunks, layers, geometryLayer, geometryStep,/);
  assert.doesNotMatch(geometryEffect, /\[segments, layers, activeLayer, activeStep,/);
});

test("high-fidelity renderer uses GPU instancing without reducing extrusion paths", () => {
  assert.match(toolpath, /function makeUnitBead\(\)/);
  assert.match(toolpath, /new THREE\.InstancedMesh\(/);
  assert.match(toolpath, /beadMesh\.setMatrixAt\(beadCount,beadMatrix\)/);
  assert.match(toolpath, /beadMesh\.setColorAt\(beadCount,hex\)/);
  assert.match(toolpath, /beadMesh\.instanceMatrix\.needsUpdate=true/);
  assert.match(toolpath, /clippingPlanes:\[view\.layerClipPlane\]/);
  assert.doesNotMatch(toolpath, /const pushTri =/);
});

test("mobile uses the same full-height budget and immutable GPU chunk loading", () => {
  assert.doesNotMatch(preview, /mobile \? 700000/);
  assert.doesNotMatch(preview, /const maxMoves = 1500000/);
  assert.match(preview, /progressiveLayerBatchSize/);
  assert.match(preview, /chunks\.push\(batch\)/);
  assert.match(preview, /chunks:chunks\.slice\(\)/);
  assert.match(toolpath, /for \(const batch of batches\)/);
  assert.match(toolpath, /chunkCount:segmentChunks\.length/);
  assert.match(toolpath, /lastChunk:segmentChunks\[segmentChunks\.length-1\]/);
  assert.doesNotMatch(toolpath, /const startSegment = canAppend/);
});
