import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const scene = fs.readFileSync(path.join(root, "SlicerPrepareWorkspace.jsx"), "utf8");
const workbench = fs.readFileSync(path.join(root, "SlicerWorkbench.jsx"), "utf8");

test("single-slot UI accepts an imported slot filament different from main preset", () => {
  const clause = scene.slice(scene.indexOf("const singleSlotProfileMatches ="),
                             scene.indexOf("const materialRoutingPending ="));
  assert.match(clause, /slotFilamentProfiles\.length === 1/);
  assert.match(clause, /slotFilamentProfiles\[0\]\.slot_id === assignedSlots\[0\]\?\.slot_id/);
  assert.match(clause, /filamentProfiles\.some\(profile =>/);
  assert.match(clause, /profile\.id\) === String\(slotFilamentProfiles\[0\]\.profile_id\)/);
  assert.doesNotMatch(clause, /selectedProfiles\?\.filament_id/);
});

test("different physical slots and unrelated profiles stay blocked", () => {
  assert.match(scene, /assignedSlots\.length === objects\.length/);
  assert.match(scene, /slot\.slot_id === assignedSlots\[0\]\.slot_id/);
  assert.match(scene, /slot\.slot_index === assignedSlots\[0\]\.slot_index/);
  assert.match(scene, /const materialRoutingPending = assignedSlots\.length > 0/);
  assert.match(scene, /\!\(hasSingleSlot && singleSlotProfileMatches\)/);
  assert.match(scene, /disabled=\{!activePlateReady \|\| !profilesReady \|\| !workerConfigured \|\| conflictsBlockSlice \|\| objectSettingsPending \|\| materialRoutingPending\}/);
});

test("slot profile and main profile both reach backend for authoritative resolution", () => {
  assert.match(workbench, /slot_filament_profiles:slotFilamentProfiles/);
  assert.match(workbench, /body: \{\s*\.\.\.form,/);
});
