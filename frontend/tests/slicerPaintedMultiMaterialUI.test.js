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

test("ordinary slicing remains blocked; native colour is explicit offline test only", () => {
  assert.match(workbench, /mode !== "multi-material-test" && projectPlates/);
  assert.match(workbench, /multi_material_test:true/);
  assert.match(workbench, /printer upload and start are blocked/);
  assert.match(workspace, /Slice multi-colour \(test\)/);
});
