import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../src/components");
const read=name=>fs.readFileSync(path.join(base,name),"utf8");

test("painting palette and icon tools are anchored beside the camera toolbar",()=>{
  const workspace=read("SlicerPrepareWorkspace.jsx");
  const editor=read("SlicerPlateEditor.jsx");
  assert.match(workspace,/paintControls=\{paintPanel\}/);
  assert.match(editor,/\{paintControls\}[\s\S]*?className="slicerPlateCameraToolbar"/);
  assert.match(workspace,/role="group" aria-label="Painting tools"/);
  assert.doesNotMatch(workspace,/\["circle","paint-disc"/);
  assert.match(workspace,/\["sphere","paint-sphere"/);
  assert.match(workspace,/\["smart_fill","paint-fill"/);
  assert.doesNotMatch(workspace,/\["facet","paint-facet"/);
  assert.doesNotMatch(workspace,/\["fill","paint-fill"/);
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

test("painting uses palette icon and four unambiguous options",()=>{
  const icons=read("SlicerUiIcon.jsx");
  const workspace=read("SlicerPrepareWorkspace.jsx");
  assert.match(workspace,/target: "paint_colour", icon: "paint-colour"/);
  assert.match(icons,/"paint-colour": <><path d="M12 2a10/);
  for(const mode of ["brush","sphere","smart_fill","height"])
    assert.ok(workspace.includes('["'+mode+'","paint-'));
});

test("model toolbar keeps permanent action captions alongside distinct pictograms",()=>{
  const workspace=read("SlicerPrepareWorkspace.jsx");
  const icons=read("SlicerUiIcon.jsx");
  const styles=fs.readFileSync(path.resolve(base,"../styles.css"),"utf8");
  assert.match(workspace,/className="slicerToolButtonLabel"/);
  assert.match(workspace,/TOOL_SHORT_LABELS\[tool\.name\] \|\| tool\.name/);
  for(const label of ["Centre","Arrange","Auto-orient","Lay on face","Hollow","Boolean","Colour paint"])
    assert.ok(workspace.includes('"'+label+'"')||workspace.includes(">"+label+"<"),label);
  for(const name of ["arrange","orient","face","split","cut","drill","hollow","boolean","measure"])
    assert.match(icons,new RegExp("\\b"+name+": <"));
  assert.match(styles,/\.slicerPrepareTools \.slicerToolButtonLabel/);
  assert.match(styles,/\.slicerPlateEditingToolbar \.slicerToolTooltip/);
});

test("approved icons are preserved and other tools use Material-style symbols",()=>{
  const icons=read("SlicerUiIcon.jsx");
  const workspace=read("SlicerPrepareWorkspace.jsx");
  const style=fs.readFileSync(path.resolve(base,"../styles.css"),"utf8");
  for(const name of ["center","orient","face","focus","split","cut","drill","hollow","boolean","measure","paint-support","paint-seam"]){
    assert.ok(icons.includes('"'+name+'":')||icons.includes("  "+name+":"),name);
  }
  assert.match(icons,/materialTools\.has\(name\) \? 2 : 1\.7/);
  assert.match(workspace,/"Lay on face":"Lay on face"/);
  assert.doesNotMatch(workspace,/"Lay on face":"Lay flat"/);
  assert.match(workspace,/index>0&&TOOLS\[index-1\]\.group!==tool\.group/);
  assert.match(style,/column-gap:4px/);
  assert.match(style,/margin-inline-start:10px/);
  assert.match(style,/left:-7px/);
  assert.match(style,/width:57px/);
  assert.match(style,/hyphens:none/);
});
