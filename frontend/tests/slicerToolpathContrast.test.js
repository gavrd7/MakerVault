import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const features = readFileSync(new URL("../src/components/slicerToolpathFeatures.js", import.meta.url), "utf8");
const preview = readFileSync(new URL("../src/components/SlicerGcodePreview.jsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/components/SlicerToolpath3D.jsx", import.meta.url), "utf8");

test("outer-only focus isolates outer feature family", () => {
  assert.match(features, /focus === "outer"\) return family === "outer"/);
  assert.match(preview, /value="outer"[^\n]*Outer walls only/);
});

test("outer wall contrast is optional and display-only", () => {
  assert.match(preview, /outerContrast=\{outerContrast\}/);
  assert.match(viewer, /featureFamily\(feature\) === "outer"/);
  assert.match(viewer, /hex\.set\("#ffd166"\)/);
  assert.match(viewer, /outerContrast, bedSize/);
});

test("outer-wall inspection uses complete current layer lines and restores mode", () => {
  assert.match(preview, /const toggleOuterInspection = \(enabled\) =>/);
  assert.match(preview, /setRenderMode\("lines"\)/);
  assert.match(preview, /setLayerDisplay\("current"\)/);
  assert.match(preview, /setFeatureFocus\("outer"\)/);
  assert.match(preview, /setRenderMode\(previous\.renderMode\)/);
  assert.match(preview, /setLayerDisplay\(previous\.layerDisplay\)/);
  assert.match(preview, /toggleOuterInspection\(e\.target\.checked\)/);
  assert.match(viewer, /if \(outerContrast && featureFamily\(feature\) !== "outer"\) continue/);
});
