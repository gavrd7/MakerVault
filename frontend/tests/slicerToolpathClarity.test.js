import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { featureColour, featureFamily, featureMatchesFocus, hasFeatureFocus } from "../src/components/slicerToolpathFeatures.js";

const base = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const preview = fs.readFileSync(path.join(base, "SlicerGcodePreview.jsx"), "utf8");
const renderer = fs.readFileSync(path.join(base, "SlicerToolpath3D.jsx"), "utf8");

test("feature colours are stable regardless of sample order or printer", () => {
  assert.equal(featureFamily("Support material"), "support");
  assert.equal(featureFamily("Support interface"), "interface");
  assert.equal(featureFamily("External perimeter"), "outer");
  assert.equal(featureFamily("Inner wall"), "inner");
  assert.equal(featureFamily("Sparse infill"), "infill");
  assert.notEqual(featureColour("Support material"), featureColour("Outer wall"));
  assert.ok(featureMatchesFocus("Support interface", "support"));
  assert.ok(!featureMatchesFocus("Outer wall", "support"));
  assert.ok(hasFeatureFocus(["Inner wall", "Support material"], "support"));
});

test("shell detail hides internal infill without deleting outer-wall moves", () => {
  assert.ok(featureMatchesFocus("Outer wall", "shell"));
  assert.ok(featureMatchesFocus("Inner wall", "shell"));
  assert.ok(featureMatchesFocus("Top surface", "shell"));
  assert.ok(!featureMatchesFocus("Sparse infill", "shell"));
  assert.ok(!featureMatchesFocus("Support material", "shell"));
  assert.match(preview, /Shell detail · hide internal infill/);
});

test("G-code preview defaults to complete-print overview while retaining layer detail", () => {
  assert.match(preview, /const \[layerDisplay, setLayerDisplay\] = useState\("all"\)/);
  assert.match(preview, /Layer visibility/);
  assert.match(preview, /Current layer only/);
  assert.match(preview, /Current \+ 8 faded layers/);
  assert.match(preview, /Supports? \+ interface/);
  assert.match(preview, /featureFocus=\{featureFocus\}/);
  assert.match(preview, /featureColour\(feature\)/);
});

test("complete model preview is not unnecessarily ghosted or labelled sampled", () => {
  assert.match(preview, /Whole print · surface overview/);
  assert.match(preview, /previewSampled={false}/);
  assert.match(preview, /wholeModel.complete/);
  assert.match(preview, /Fade previous layers/);
  assert.match(preview, /fadePrevious=\{highlightCurrent\}/);
  assert.match(renderer, /previewSampled = false, fadePrevious = false/);
  assert.match(renderer, /previewSampled \? 0\.82 : 1/);
  assert.match(renderer, /new THREE\.HemisphereLight/);
});

test("3D preview filters by selected layers and uses shaded bead geometry", () => {
  assert.match(renderer, /layerDisplay === "current"/);
  assert.match(renderer, /segmentLayerIndex < minVisibleIndex/);
  assert.match(renderer, /featureMatchesFocus\(feature, featureFocus\)/);
  assert.match(renderer, /geometry\.computeVertexNormals\(\)/);
  assert.match(renderer, /THREE\.MeshLambertMaterial/);
  assert.match(renderer, /const target = valid \? centre : bedCentre/);
});
