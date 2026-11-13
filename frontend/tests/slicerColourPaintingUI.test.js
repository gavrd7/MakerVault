import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../src/components");
const read=name=>fs.readFileSync(path.join(base,name),"utf8");

test("painting palette and icon tools are in the viewport overlay, not above the plate",()=>{
  const workspace=read("SlicerPrepareWorkspace.jsx");
  const editor=read("SlicerPlateEditor.jsx");
  assert.match(workspace,/paintControls=\{paintPanel\}/);
  assert.match(editor,/className="slicerPlateCanvasViewport"[^>]*>[\s\S]*?\{paintControls\}/);
  assert.match(workspace,/role="group" aria-label="Painting tools"/);
  assert.match(workspace,/\["circle","paint-disc"/);
  assert.match(workspace,/\["sphere","paint-sphere"/);
  assert.match(workspace,/borderRadius:"50%"/);
  assert.match(workspace,/title=\{description\}/);
});

test("paint mode restores right-mouse navigation and hides non-paint selection outlines",()=>{
  const editor=read("SlicerPlateEditor.jsx");
  assert.match(editor,/controls\.mouseButtons\.RIGHT = THREE\.MOUSE\.PAN/);
  assert.match(editor,/state\.controls\.enabled = true/);
  assert.match(editor,/toolMode === "paint_colour" \? \[\] : selection/);
  assert.match(editor,/toolMode === "paint_colour" \? 0 : conflictIds/);
  assert.match(editor,/previewPaintGuide\(hit\)/);
  assert.match(editor,/latestPaintHeightPickRef\.current\?\.\(next\)/);
});

test("height fill does not recalculate an entire mesh on every drag event",()=>{
  const editor=read("SlicerPlateEditor.jsx");
  assert.match(editor,/\["height","fill","smart_fill","facet"\]\.includes/);
  assert.match(editor,/hidePaintGuides\(\)/);
});
