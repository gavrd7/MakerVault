import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const base = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const read = rel => fs.readFileSync(path.join(base, rel), "utf8");
const editor = read("components/SlicerPlateEditor.jsx");
const chooser = read("components/SlicerEngineChoices.jsx");
const styles = read("styles.css");

test("underside build plate visibility applies to native and procedural bed geometry", () => {
  assert.match(editor, /const \[undersidePlateMode, setUndersidePlateMode\]/);
  assert.match(editor, /under(s|S)idePlateModeRef\.current/);
  assert.match(editor, /camera\.position\.z < -0\.5/);
  assert.match(editor, /setMaterials\(bed, 0\.22\)/);
  assert.match(editor, /setMaterials\(plateBody, 0\.12\)/);
  assert.match(editor, /setMaterials\(plateRim, 0\.18\)/);
  assert.match(editor, /if \(nativeBedMesh\) setMaterials\(nativeBedMesh, 0\.12\)/);
  assert.match(editor, /material\.depthWrite = !translucent/);
  assert.match(editor, /updateBedAppearance\(\)/);
  assert.match(editor, /map: bedTexture, side: THREE\.DoubleSide/);
  assert.match(editor, /value="auto">Auto \(see through from below\)/);
  assert.match(editor, /value="opaque">Always opaque/);
  assert.match(editor, /value="transparent">Always transparent/);
});

test("visibility setting adapts to mobile view without changing model meshes", () => {
  assert.match(styles, /\.slicerPlateDisplayOptionsRow \.slicerBedVisibilityControl/);
  assert.match(styles, /\.slicerPlateDisplayOptionsRow \.slicerBedVisibilityControl select/);
  assert.match(editor, /scene\.add\(mesh\)/);
  assert.ok(editor.indexOf('className="slicerBedVisibilityControl"') > editor.indexOf('<legend>Build plate display</legend>'));
  assert.ok(editor.indexOf('className="slicerBedVisibilityControl"') > editor.indexOf('className="slicerPlateCanvasViewport"'));
  assert.doesNotMatch(editor, /for \(const mesh of meshes\.values\(\)\) mesh\.visible = false/);
});

test("planned engine cards load offline bundled upstream SVG icons", () => {
  for (const name of ["elegooslicer", "cura", "anycubicslicernext"]) {
    assert.match(chooser, new RegExp(name + ": logoUri\\("));
    const svg = read("assets/slicer-engines/" + name + ".svg");
    assert.match(svg, /<svg\b/);
    assert.doesNotMatch(svg, /href="https?:\/\//); // No external resource dependencies.
  }
  assert.match(chooser, /snapmakerorca: logoUri\(snapmakerSvg\)/);
  assert.match(chooser, /onError=\{\(\) => setFailed\(true\)\}/);
});
