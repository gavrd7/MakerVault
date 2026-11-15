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

test("G-code preview defaults to complete-print overview while retaining layer detail", () => {
  assert.match(preview, /const \[layerDisplay, setLayerDisplay\] = useState\("all"\)/);
  assert.match(preview, /Layer visibility/);
  assert.match(preview, /Current layer only/);
  assert.match(preview, /Current \+ 8 faded layers/);
  assert.match(preview, /Supports? \+ interface/);
  assert.match(preview, /featureFocus=\{featureFocus\}/);
  assert.match(preview, /featureColour\(feature\)/);
});

test("3D preview filters by selected layers and uses shaded bead geometry", () => {
  assert.match(renderer, /layerDisplay === "current"/);
  assert.match(renderer, /segmentLayerIndex < minVisibleIndex/);
  assert.match(renderer, /featureMatchesFocus\(feature, featureFocus\)/);
  assert.match(renderer, /geometry\.computeVertexNormals\(\)/);
  assert.match(renderer, /THREE\.MeshLambertMaterial/);
  assert.match(renderer, /const target = valid \? centre : bedCentre/);
});
