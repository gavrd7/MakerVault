import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = name => readFileSync(new URL("../src/components/" + name, import.meta.url), "utf8");
const workspace = read("SlicerPrepareWorkspace.jsx");
const workbench = read("SlicerWorkbench.jsx");

test("single painted model can resolve multiple explicit filament slots", () => {
  assert.match(workspace, /const paintedSlotRefs = objects\.flatMap/);
  assert.match(workspace, /\.palette\?\.\[region\.slot\]/);
  assert.match(workspace, /requiredMultiSlots\.length >= 2/);
  assert.match(workspace, /slotFilamentProfiles\.some/);
  assert.match(workspace, /painted colour/i);
});

test("painted swatches can be rebound to loaded slots without changing region indexes", () => {
  assert.match(workspace, /const reassignPaintSwatch =/);
  assert.match(workspace, /palette: row\.colour_paint\.palette\.map/);
  assert.match(workspace, /slot_id: String\(slot\.id\)/);
  assert.match(workspace, /Assigned printer filament for painted colour/);
  assert.match(workspace, /reassignPaintSwatch\(paintSlot,event\.target\.value\)/);
});

test("single Slice action chooses offline multi-colour automatically", () => {
  assert.match(workbench, /function plateNeedsMultiMaterial\(objects\)/);
  assert.match(workbench, /offlineMultiMaterial \? \{multi_material_test:true\}/);
  assert.match(workbench, /printer upload and start are blocked/);
  assert.match(workspace, /onClick=\{onSlice\}>Slice/);
  assert.doesNotMatch(workspace, /Slice multi-colour \(test\)/);
});

test("painted colour remains visible in build plate selection and transform modes", () => {
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(editor, /colour_paint:item\.colour_paint/);
  assert.match(editor, /colour_paint:original\.colour_paint/);
  assert.doesNotMatch(editor, /colour_paint:toolMode==="paint_colour"\?item\.colour_paint:null/);
});

test("profiled loaded bays are not mistaken for an assigned model base", () => {
  assert.match(workspace, /paintedObjectsWithoutBase = objects\.filter/);
  assert.match(workspace, /baseCandidates\.length === 1/);
  assert.match(workspace, /Model base filament slot/);
  assert.match(workspace, /Use matching base profile:/);
  assert.match(workspace, /worker-verified Orca 2\.5\.0 native profile/);
  assert.match(workspace, /profile\.status === "verified" \? " · Worker verified"/);
  assert.match(workspace, /baseProfileMismatch/);
});
