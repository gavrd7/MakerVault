import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const toolbar = fs.readFileSync(path.join(root, "SlicerPrepareWorkspace.jsx"), "utf8");
const plate = fs.readFileSync(path.join(root, "SlicerPlateEditor.jsx"), "utf8");

test("measurement toolbar supports explicitly selected snapping behaviour", () => {
  for (const mode of ["auto", "vertex", "edge", "surface"])
    assert.match(toolbar, new RegExp('value="' + mode + '"'));
  assert.match(toolbar, /measureSnapMode=\{measureSnapMode\}/);
  assert.match(plate, /latestMeasurementRef\.current\.snapMode !== "surface"/);
  assert.match(plate, /latestMeasurementRef\.current\.snapMode !== "edge"/);
  assert.match(plate, /latestMeasurementRef\.current\.snapMode !== "vertex"/);
});

test("measurements are shown on the 3D model as read-only labels and cleaned up", () => {
  assert.match(plate, /new THREE\.CanvasTexture\(canvas\)/);
  assert.match(plate, /new THREE\.Sprite\(new THREE\.SpriteMaterial/);
  assert.match(plate, /measurementFormat\(distance, measureUnit\)/);
  assert.match(plate, /measurementFormat\(circle\.diameter, measureUnit\)/);
  assert.match(plate, /item\.material\?\.map\?\.dispose\(\)/);
  assert.match(plate, /aria-label="Selected model measurements"/);
});
