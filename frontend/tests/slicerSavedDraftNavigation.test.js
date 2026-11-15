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
  assert.match(workbench, /save_gcode_to_library: saveOutput/);
  assert.match(workbench, /onClick=\{\(\) => saveDraft\("quick"\)\}/);
  assert.match(workbench, /previewJob\.settings\?\.workflow !== "quick"/);
  assert.match(workbench, /save-gcode\//);
  assert.match(history, /Add G-code to library/);
  assert.match(history, /save-gcode\//);
});

test("a model-linked draft opens its specific workbench configuration in preview or ready mode", () => {
  const app = fs.readFileSync(path.join(root, "src/App.jsx"), "utf8");
  const page = read("PrintingPage.jsx");
  const history = read("SavedSlicerJobsModal.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(app, /\["ready", "preview"\]\.includes\(slicerStatus\.state\)/);
  assert.match(app, /type: "slicer_job", id: jobId/);
  assert.match(page, /initialDraftId=\{searchTarget\?\.type === "slicer_job" \? searchTarget\.id : null\}/);
  assert.match(history, /onOpenSlicer\?\.\(job\.id\)/);
  assert.match(workbench, /function loadSavedDraft\(job\)/);
  assert.match(workbench, /jobs\.find\(item => item\.id === initialDraftId\)/);
});

test("completed slice opens existing read-only G-code preview within jobs modal", () => {
  const workbench = read("SlicerWorkbench.jsx");
  const viewer = read("GcodeViewerModal.jsx");
  assert.match(workbench, /awaitingSlicePreviewRef\.current = job\.id/);
  assert.match(workbench, /result\?\.status === "completed"/);
  assert.match(workbench, /setPreviewJobId\(result\.id\)/);
  assert.match(workbench, /Preview G-code/);
  assert.match(workbench, /<GcodeViewerModal key=\{previewJob\.output_asset\.id\} embedded/);
  assert.match(viewer, /embedded \? content : <Modal/);
  assert.match(viewer, /apiFetch\(`\/api\/files\/\$\{file\.id\}\/gcode\/inspect\/`\)/);
});

test("slicer result preview restores upload-only send-to-printer route", () => {
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(workbench, /requestPrint\(previewJob, "upload"\)/);
  assert.match(workbench, /Upload to printer/);
  assert.match(workbench, /Upload and start print/);
  assert.match(workbench, /requestPrint\(previewJob, "print"\)/);
  assert.match(workbench, /initialAction=\{printSelection\.action === "upload" \? "upload" : "print"\}/);
  assert.match(workbench, /Review upload/);
});

test("printer send modal lists all saved G-code by category, not encrypted filename", () => {
  const modal = read("PrinterStartGcodeModal.jsx");
  assert.match(modal, /apiFetch\("\/api\/files\/\?category=gcode"\)/);
  assert.match(modal, /\.filter\(f => f\.category === "gcode"\)/);
  assert.doesNotMatch(modal, /\.filter\(f => \(f\.filename \|\| ""\)\.toLowerCase\(\)\.endsWith\("\.gcode"\)\)/);
});

test("printer send modal includes completed private slices without promoting them", () => {
  const modal = read("PrinterStartGcodeModal.jsx");
  assert.match(modal, /apiFetch\("\/api\/files\/\?category=gcode"\)/);
  assert.match(modal, /apiFetch\("\/api\/printing\/slicer\/jobs\/"\)/);
  assert.match(modal, /job\.status === "completed" && !job\.gcode_in_library && job\.output_asset\?\.id/);
  assert.match(modal, /Private slice \(not in library\)/);
  assert.match(modal, /const knownIds = new Set\(libraryFiles\.map/);
  assert.doesNotMatch(modal, /save-gcode\/.*await.*load/s);
});
