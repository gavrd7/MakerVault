import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const prepare = readFileSync(new URL("../src/components/SlicerPrepareWorkspace.jsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");

test("modifier entry is model-owned and not added as a printable STL", () => {
  assert.match(prepare, /Add parameter modifier/);
  assert.match(prepare, /modifier_volumes: \[\.\.\.\(item\.modifier_volumes \|\| \[\]\), fresh\]/);
  assert.match(prepare, /Native regional slicing remains blocked/);
  assert.doesNotMatch(prepare, /newPlateInstance\(id,objects\.length\+index\).*modifier/s);
});

test("all six primitive modifier shapes have edit and preview paths", () => {
  for (const shape of ["box", "cylinder", "sphere", "cone", "disc", "torus"]) {
    assert.match(prepare, new RegExp('"' + shape + '"'));
    assert.match(editor, new RegExp('"' + shape + '"'));
  }
  assert.match(editor, /isModifierVolume = true/);
  assert.match(editor, /ghost\.raycast = \(\) => \{\}/);
  assert.match(editor, /parent\.add\(ghost\)/);
  assert.match(editor, /syncModifierOverlays\(mesh, item, state\.sectionPlane\)/);
});

test("duplicate keeps modifier children independent from the original parent", () => {
  assert.match(editor, /copy\.modifier_volumes = chosen\.modifier_volumes\.map\(modifier =>/);
  assert.match(editor, /id: plateUuid\(\), settings: \{\.\.\.modifier\.settings\}/);
});

test("torus preview uses the exact backend major and minor radii", () => {
  assert.match(editor, /TorusGeometry\(\.30, \.20, 16, 32\)/);
  assert.match(editor, /geometry\.scale\(w, d, h \/ \.4\)/);
});

test("object settings exposes regional walls and enforces total plate modifier count", () => {
  assert.match(prepare, /Regional wall loops/);
  assert.match(prepare, /totalModifierCount >= 48/);
  assert.match(prepare, /totalModifierCount>=48/);
  assert.match(prepare, /if\(raw===""\) delete settings\.wall_loops/);
});

test("Add model menu offers six parameter modifier shapes with non-printing child ownership", () => {
  assert.match(prepare, /Add parameter modifier/);
  assert.match(prepare, /Choose parameter modifier primitive/);
  assert.match(prepare, /modifierShapeMenuOpen/);
  assert.match(prepare, /addModifier\(shape\)/);
  assert.match(prepare, /onClick=\{\(\)=>addModifier\(\)\}/);
  assert.match(prepare, /totalModifierCount>=48/);
  assert.match(prepare, /modifier_volumes: \[\.\.\.\(item\.modifier_volumes \|\| \[\]\), fresh\]/);
});
