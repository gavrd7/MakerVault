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
  assert.match(workbench, /Open interactive slicer/);
  assert.match(workbench, /editorOpen \? <SlicerPrepareWorkspace/);
  assert.match(workbench, /setEditorOpen\(true\)/);
  assert.match(workbench, /onSaveDraft=\{\(\) => saveDraft\("draft"\)\}/);
  assert.match(workbench, /onSlice=\{\(\) => saveDraft\("slice"\)\}/);
  assert.match(workbench, /onSaveAndSlice=\{\(\) => saveDraft\("save-and-slice"\)\}/);
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
                       "Colour painting", "Add plate", "Individual XYZ scale"]) {
    assert.match(scene, new RegExp('name: "' + tool + '", pending:'));
  }
  assert.match(scene, /disabled=\{!!tool.pending/);
  for (const group of ["Quality", "Strength", "Speed", "Supports", "Multifilament", "Others"])
    assert.match(scene, new RegExp('"' + group + '"'));
  assert.match(scene, /Per-object overrides require native engine support/);
});
