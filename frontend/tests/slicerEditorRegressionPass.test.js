import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TEXT_FONTS, createTextStl } from "../src/components/slicerPrimitives.js";

const components = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const source = name => fs.readFileSync(path.join(components,name),"utf8");

test("bundled text styles generate real printable geometry", () => {
  assert.ok(TEXT_FONTS.length >= 4, "A varied set of text styles is available");
  for (const font of TEXT_FONTS) {
    const result = createTextStl({ text:"HI",font:font.id,width:24,depth:10,height:3 });
    assert.ok(result.triangles > 0, font.id);
    assert.equal(result.buffer.byteLength,84+result.triangles*50,font.id);
  }
});

test("full MakerVault lettering is printable in every bundled font", () => {
  for (const font of TEXT_FONTS) {
    const output=createTextStl({text:"MakerVault",font:font.id,width:80,depth:20,height:4});
    assert.ok(output.triangles>0,font.id);
    assert.ok(output.height>3.9&&output.height<4.1,font.id);
  }
});

test("text edit preserves the model identity and exposes its original parameters", () => {
  const workspace=source("SlicerPrepareWorkspace.jsx");
  const editor=source("SlicerPlateEditor.jsx");
  assert.match(workspace,/object\.text_model && <button/);
  assert.match(workspace,/>Edit text<\/button>/);
  assert.match(workspace,/editTargetId:object\.instance_id/);
  assert.match(editor,/text:editingText\?item\.text_model\.text/);
  assert.match(editor,/font:editingText\?item\.text_model\.font/);
  assert.match(editor,/instance_id:solidDialog\.editTargetId/);
});

test("editing shortcuts guard native text entry and safely place pasted models", () => {
  const editor=source("SlicerPlateEditor.jsx");
  const workspace=source("SlicerPrepareWorkspace.jsx");
  assert.match(editor,/event\.target\?\.isContentEditable/);
  assert.match(editor,/event\.target\?\.closest\?\.\('\[role="dialog"\]'\)/);
  assert.match(editor,/key==="c"\|\|key==="x"/);
  assert.match(editor,/key==="v"/);
  assert.match(editor,/key==="delete"\|\|key==="backspace"/);
  assert.match(editor,/findFreeDuplicatePosition\(/);
  assert.match(workspace,/event\.shiftKey\) redo\(\); else undo\(\)/);
  assert.match(workspace,/event\.key\.toLowerCase\(\) === "y"/);
});

test("sections, Boolean selections and insertion gizmos remain separate from source meshes", () => {
  const editor=source("SlicerPlateEditor.jsx");
  assert.match(editor,/aria-label="Section plane axis"/);
  assert.match(editor,/option value="z"/);
  assert.match(editor,/option value="x"/);
  assert.match(editor,/option value="y"/);
  assert.match(editor,/lastBooleanPlateSelectionRef\.current===booleanSelectionKey/);
  assert.match(editor,/new TransformControls\(state\.camera,canvas\)/);
  assert.match(editor,/gizmo\.attach\(ghost\)/);
  assert.match(editor,/validationWarning/);
  assert.match(editor,/solidPreview\.parts\.some\(part=>part\.validationWarning\)/);
});
