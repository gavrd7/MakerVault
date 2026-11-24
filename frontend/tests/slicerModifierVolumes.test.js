import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const prepare = readFileSync(new URL("../src/components/SlicerPrepareWorkspace.jsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");

test("modifier and negative are non-printing plate-tree rows without STL uploads", () => {
  assert.match(prepare, /Add parameter modifier/);
  assert.match(prepare, /modifier_volumes: \[\.\.\.\(item\.modifier_volumes \|\| \[\]\), fresh\]/);
  assert.match(prepare, /allPlateRows = objects.flatMap/);
  assert.match(prepare, /isPlateVolume: true/);
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

test("printable duplicates do not duplicate independently placed volumes", () => {
  assert.match(editor, /copy\.modifier_volumes = \[\]/);
  assert.match(editor, /A free volume is a separate plate item/);
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

test("Add model menu uses shared insertion editor for six non-printing modifier shapes", () => {
  assert.match(prepare, /Add parameter modifier/);
  assert.match(prepare, /Choose parameter modifier primitive/);
  assert.match(prepare, /modifierShapeMenuOpen/);
  assert.match(prepare, /setSolidRequest\(\{kind:"modifier",shape,id:Date\.now\(\)\}\)/);
  assert.match(prepare, /setSolidRequest\(\{kind:"modifier",id:Date\.now\(\)\}\)/);
  assert.match(prepare, /totalModifierCount>=48/);
  assert.match(prepare, /modifier_volumes: \[\.\.\.\(item\.modifier_volumes \|\| \[\]\), fresh\]/);
});

test("new modifier draft is placed independently with XYZ rotation and scale", () => {
  assert.match(prepare, /coordinate_space: "world"/);
  assert.match(prepare, /rotation_xyz_deg: \[0, 0, 0\]/);
  assert.match(prepare, /scale_xyz_percent: \[100, 100, 100\]/);
  assert.match(prepare, /Edit shape \/ Move \/ Scale \/ Rotate/);
  assert.match(prepare, /selectedModifierId=\{activeModifier\?\.id \|\| null\}/);
  assert.match(editor, /ghost\.userData\.isWorldModifier = modifier\.coordinate_space === "world"/);
  assert.match(editor, /state\.transform\.attach\(activeModifier\)/);
  assert.match(editor, /Independent modifier transform controls/);
});

test("world modifier cannot become a model drag and preserves independent pose", () => {
  assert.match(editor, /mesh\.userData\.isWorldModifier/);
  assert.match(editor, /modifierSelectionRef\.current\.onChange/);
  assert.match(editor, /latestOnChangeRef\.current\(current\.map/);
  assert.match(editor, /modifier\.coordinate_space === "world"/);
});

test("non-destructive negative volume uses shared insertion and is a selectable tree object", () => {
  assert.match(prepare, /kind:"negative",id:Date\.now\(\)/);
  assert.match(editor, /\["modifier","negative"\]\.includes\(solidDialog\.kind\)/);
  assert.match(editor, /settings:solidDialog\.kind==="negative"\?\{\}/);
  assert.match(prepare, /object\.kind==="negative"\?"negative volume":"parameter modifier"/);
  assert.match(prepare, /selectedRows\.length < 2/);
  assert.match(editor, /modifierSelectionRef\.current\.onChange\?\.\(candidate\.object\.userData\.modifierId/);
  assert.match(editor, /volumesById = new Map/);
});

test("modifier and negative volumes share primitive shape and transform modal", () => {
  assert.match(prepare, /kind:"modifier",shape,id:Date\.now\(\)/);
  assert.match(prepare, /Edit shape \/ Move \/ Scale \/ Rotate/);
  assert.match(editor, /"modifier","negative"\]\.includes\(solidDialog\.kind\)/);
  assert.match(editor, /solidRequest\.editVolumeId/);
  assert.match(editor, /editingVolume\?\.rotation_xyz_deg/);
});
