import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = file => fs.readFileSync(path.join(root, "src/components", file), "utf8");

test("saved slice drafts are linked from 3D printing and per-model entries", () => {
  const page = read("PrintingPage.jsx");
  assert.match(page, /Saved slice drafts/);
  assert.match(page, /<SavedSlicerJobsModal/);
  assert.match(page, /title=\{"Saved slices · " \+ sliceDraftModel\.name\}/);
  assert.match(page, /assetIds=\{sliceDraftModel\.revisions\.flatMap/);
});

test("stored slice history is scoped by file asset IDs and remains owner-protected by API", () => {
  const modal = read("SavedSlicerJobsModal.jsx");
  assert.match(modal, /apiFetch\("\/api\/printing\/slicer\/jobs\/"/);
  assert.match(modal, /allowedIds\.has\(String\(job\.input_asset\?\.id\)\)/);
  assert.match(modal, /plate_objects/);
  assert.match(modal, /Show completed and other jobs/);
});

test("the slicer offers opt-in save at slicing time or from a completed job", () => {
  const workbench = read("SlicerWorkbench.jsx");
  const history = read("SavedSlicerJobsModal.jsx");
  assert.match(workbench, /save_gcode_to_library: saveGcodeToLibrary/);
  assert.match(workbench, /Automatically add generated G-code/);
  assert.match(workbench, /save-gcode\//);
  assert.match(history, /Add G-code to library/);
  assert.match(history, /save-gcode\//);
});
