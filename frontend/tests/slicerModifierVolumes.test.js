import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const prepare = readFileSync(new URL("../src/components/SlicerPrepareWorkspace.jsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");

test("modifier and negative are non-printing plate-tree rows without STL uploads", () => {
  assert.match(prepare, /Add parameter modifier/);
  assert.match(editor, /modifier_volumes:solidDialog\.editVolumeId/);
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
  assert.match(prepare, /Regional slicing settings/);
  assert.match(prepare, /totalModifierCount>=48/);
  assert.match(prepare, /if\(raw===""\) delete settings\.wall_loops/);
});

test("Add model menu uses shared insertion editor for six non-printing modifier shapes", () => {
  assert.match(prepare, /Add parameter modifier/);
  assert.match(prepare, /Choose parameter modifier primitive/);
  assert.match(prepare, /modifierShapeMenuOpen/);
  assert.match(prepare, /setSolidRequest\(\{kind:"modifier",shape,id:Date\.now\(\)\}\)/);
  assert.match(prepare, /totalModifierCount>=48/);
  assert.match(editor, /modifier_volumes:solidDialog\.editVolumeId/);
});

test("new modifier draft is placed independently with XYZ rotation and scale", () => {
  assert.match(editor, /coordinate_space:"world"/);
  assert.match(editor, /rotation_xyz_deg:numbers\.slice\(6,9\)/);
  assert.match(editor, /scale_xyz_percent:previous\?\.scale_xyz_percent \|\| \[100,100,100\]/);
  assert.match(prepare, /Edit volume/);
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
  assert.match(prepare, /Edit volume/);
  assert.match(editor, /"modifier","negative"\]\.includes\(solidDialog\.kind\)/);
  assert.match(editor, /solidRequest\.editVolumeId/);
  assert.match(editor, /editingVolume\?\.rotation_xyz_deg/);
});

test("stored free modifiers and negative volumes reopen the shared shape and transform editor", () => {
  assert.match(prepare, /Edit volume<\/button>/);
  assert.match(prepare, /editTargetId:object\.owner_instance_id,editVolumeId:object\.id/);
  assert.match(prepare, /kind:object\.kind==="negative"\?"negative":"modifier"/);
  assert.match(editor, /editingVolume\?\.width_mm/);
  assert.match(editor, /editingVolume\?\.rotation_xyz_deg/);
  assert.match(editor, /solidDialog\.editVolumeId/);
});

test("the shared insertion modal shows native world-centred volumes and never doubles rotation", () => {
  assert.match(editor, /createPrimitiveGeometry\(solidOptions\)/);
  assert.match(editor, /ghost\.position\.set\(Number\(solidOptions\.x_mm\),Number\(solidOptions\.y_mm\)/);
  assert.match(editor, /z_mm:pretty\(position\.z\)/);
  assert.match(editor, /rotation_z:degrees\(ghost\.rotation\.z\)\+\(volume\?0:/);
  assert.doesNotMatch(editor, /solidDialog\.kind==="negative"\?Number\(old\.height\|\|0\)\/2/);
});
