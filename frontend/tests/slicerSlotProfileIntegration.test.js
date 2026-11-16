import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const scene = fs.readFileSync(path.join(root, "SlicerPrepareWorkspace.jsx"), "utf8");
const parent = fs.readFileSync(path.join(root, "SlicerWorkbench.jsx"), "utf8");

test("existing matching slot profiles are assigned only when an exact unique match exists",()=>{
  assert.match(scene,/matchLoadedSlotProfiles\(slot, filamentProfiles/);
  assert.match(scene,/\.filter\(\(\{match\}\) => match\.level === "exact"\)/);
  assert.match(scene,/const existing = new Set\(slotFilamentProfiles\.map/);
  assert.match(scene,/!existing\.has\(String\(slot\.id\)\)/);
  assert.match(scene,/suppressedSlotMatches\.includes/);
});
test("official catalogue search and import require an explicit slot selection",()=>{
  assert.match(scene,/findOfficialSlotProfiles = async slot/);
  assert.match(scene,/onClick=\{\(\) => findOfficialSlotProfiles\(slot\)\}/);
  assert.match(scene,/importOfficialSlotProfile = async \(slot, candidate\)/);
  assert.match(scene,/window\.confirm\("Import "/);
  assert.match(scene,/candidate\.vendor/);
  assert.match(scene,/onFilamentProfilesReload\?\.\(\)/);
  assert.doesNotMatch(scene,/onChange\(.*\bdownloadLatestEngine\b/);
});
test("slot import reloads profiles without overwriting global native filament selection",()=>{
  assert.match(parent,/onFilamentProfilesReload=\{async \(\) => \{/);
  assert.match(scene,/\.filter\(row => String\(row\.slot_id\) !== String\(slot\.id\)\)/);
  const handler=scene.slice(scene.indexOf("const importOfficialSlotProfile"), scene.indexOf("const [materialRefreshing"));
  assert.doesNotMatch(handler,/selectedProfiles\.filament_id\s*=/);
  assert.doesNotMatch(handler,/onChangeProfiles\(/);
});
test("profiles for unassigned loaded bays do not block one logical filament",()=>{
  assert.match(scene,/const activeSlotProfiles = slotFilamentProfiles\.filter/);
  assert.match(scene,/const materialRoutingPending = assignedSlots\.length > 0/);
  assert.match(scene,/: false;/);
  assert.match(scene,/assignedSlots\.every\(slot => String\(slot\.printer_id\)/);
});
