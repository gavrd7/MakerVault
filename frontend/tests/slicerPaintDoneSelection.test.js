import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const source=readFileSync(
  new URL("../src/components/SlicerPrepareWorkspace.jsx",import.meta.url),"utf8");

test("painting Done clears transient model highlights without modifying masks",()=>{
  assert.match(source,/const finishPainting = \(\) => \{/);
  const section=source.match(/const finishPainting = \(\) => \{([\s\S]*?)\n  \};/)?.[1];
  assert.ok(section,"shared painting exit handler exists");
  assert.match(section,/setToolMode\("select"\)/);
  assert.match(section,/setSelectedId\(""/);
  assert.match(section,/setSelectedIds\(\[\]\)/);
  assert.doesNotMatch(section,/updatePlate|onChange|support_paint|seam_paint|fuzzy_skin_paint/);
  assert.match(source,/aria-label="Close painting">Done<\/button>/);
  assert.equal((source.match(/onClick=\{finishPainting\}/g)||[]).length,2,
    "painting and variable-layer Done use the same clear-selection path");
});


test("Done also clears Three.js selection helpers and material glow",()=>{
  assert.match(source,/setSelectionClearVersion\(version => version \+ 1\)/);
  assert.match(source,/selectionClearVersion=\{selectionClearVersion\}/);
  const editor=readFileSync(new URL("../src/components/SlicerPlateEditor.jsx",import.meta.url),"utf8");
  assert.match(editor,/\[selectionClearVersion\]/);
  assert.match(editor,/state\.setSelectionOutlines\(\[\]\)/);
  assert.match(editor,/state\.transform\.detach\(\)/);
  assert.match(editor,/mesh\.material\.emissiveIntensity = 0/);
});
