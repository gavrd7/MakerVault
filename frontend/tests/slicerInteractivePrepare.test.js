import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const read = name => fs.readFileSync(path.join(root, name), "utf8");

test("setup is retained and a separate interactive Prepare workspace is available", () => {
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(workbench, /Slicer setup/);
  assert.match(workbench, /Slice → Interactive slicer/);
  assert.match(workbench, /onClick=\{\(\) => saveDraft\("quick"\)\}/);
  assert.match(workbench, /onClick=\{\(\) => saveDraft\("draft"\)\}/);
  assert.match(workbench, /editorOpen \? <SlicerPrepareWorkspace/);
  assert.match(workbench, /setEditorOpen\(true\)/);
  assert.match(workbench, /onSaveDraft=\{\(\) => saveDraft\("draft"\)\}/);
  assert.match(workbench, /onSlice=\{\(\) => saveDraft\("slice"\)\}/);
  assert.doesNotMatch(workbench, /onSaveAndSlice=/);
});

test("editor provides actual model tree, undo redo and existing placement operations", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const plate = read("SlicerPlateEditor.jsx");
  assert.match(scene, /onChange\(previous\)/);
  assert.match(scene, /onChange\(next\)/);
  assert.match(scene, /onPrimaryChange\?\.\(next\[0\]\?\.asset_id \|\| ""\)/);
  assert.match(scene, /Ctrl\+Z/);
  assert.match(scene, /aria-label="Build plate object tree"/);
  assert.match(scene, /selectedInstanceId=\{selectedId\}/);
  assert.match(scene, /onSelectedInstanceChange=\{setSelectedId\}/);
  for (const tool of ["Move", "Rotate", "Scale", "Auto-arrange", "Duplicate"]) {
    assert.match(scene, new RegExp('name: "' + tool + '"'));
  }
  assert.match(plate, /data-slicer-action="arrange"/);
  assert.match(plate, /data-slicer-action="duplicate"/);
  assert.match(plate, /data-slicer-field="x_mm"/);
});

test("advanced tools are visibly gated pending safe native transformations", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  for (const tool of ["Auto-orient", "Lay on face", "Cut", "Hollow",
                       "Support painting", "Seam painting", "Variable layer height",
                       "Colour painting", "Add plate"]) {
    assert.match(scene, new RegExp('name: "' + tool + '", pending:'));
  }
  assert.match(scene, /disabled=\{!!tool.pending/);
  for (const group of ["Quality", "Strength", "Speed", "Supports", "Multifilament", "Others"])
    assert.match(scene, new RegExp('"' + group + '"'));
  assert.match(scene, /Per-object overrides require native engine support/);
});

test("independent XYZ scaling updates visual mesh and is selectable from the toolbar", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(scene, /name: "Individual XYZ scale", target: "scale_xyz_percent"/);
  assert.match(editor, /Independent axis scaling \(%\)/);
  assert.match(editor, /data-slicer-field=\{index === 0 \? "scale_xyz_percent"/);
  assert.match(editor, /mesh\.scale\.set\(xyz\[0\] \/ 100, xyz\[1\] \/ 100, xyz\[2\] \/ 100\)/);
});

test("duplicating a selected model preserves every saved transformation", () => {
  const plate = read("SlicerPlateEditor.jsx");
  assert.match(plate, /const copy = \{ \.\.\.chosen, instance_id: plateUuid\(\) \}/);
  assert.match(plate, /copy\.scale_xyz_percent = \[\.\.\.chosen\.scale_xyz_percent\]/);
  assert.match(plate, /pendingArrangeRef\.current = true/);
  assert.match(plate, /onClick=\{duplicateSelected\}>Duplicate selected/);
});

test("slicer setup offers Save draft / Quick slice / interactive Slice at plate footer", () => {
  const workbench = read("SlicerWorkbench.jsx");
  const footer = workbench.indexOf('className="slicerDraftActions settingsActions"');
  const end = workbench.indexOf('      </>}', footer);
  const buttons = workbench.slice(footer, end);
  assert.match(buttons, /Save draft/);
  assert.match(buttons, /Quick slice/);
  assert.match(buttons, /Slice → Interactive slicer/);
  assert.ok(buttons.indexOf("Save draft") < buttons.indexOf("Quick slice"));
  assert.ok(buttons.indexOf("Quick slice") < buttons.indexOf("Slice → Interactive slicer"));
  assert.doesNotMatch(workbench.slice(workbench.indexOf('className="slicerSetupHeading"'), workbench.indexOf('className="slicerSetupHeading"') + 250), /Open interactive slicer/);
  assert.match(buttons, /disabled=\{!canPrepare \|\| busy \|\| loading\}/);
});

test("quick slice remains private and does not expose direct upload/start actions", () => {
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(workbench, /const workflow = mode === "quick" \? "quick"/);
  assert.match(workbench, /save_gcode_to_library: saveOutput, workflow/);
  assert.match(workbench, /previewJob\.settings\?\.workflow !== "quick"/);
  assert.match(workbench, /job\.settings\?\.workflow !== "quick"/);
});
