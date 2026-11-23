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
