import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const base = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const read = name => fs.readFileSync(path.join(base, name), "utf8");
const workbench = read("components/SlicerWorkbench.jsx");
const editor = read("components/SlicerPlateEditor.jsx");
const detection = read("components/slicerAutoMeasure.js");
const styles = read("styles.css");

test("new interactive editor and resumed draft start at the top of the slicer", () => {
  assert.match(workbench, /useLayoutEffect\(\(\) => \{/);
  assert.match(workbench, /\}, \[editorOpen\]\)/);
  assert.match(workbench, /window\.scrollTo\(\{ top: 0, left: 0, behavior: "instant" \}\)/);
  assert.match(workbench, /if \(node\.scrollTop > 0\) node\.scrollTop = 0/);
  assert.match(workbench, /restoreTop\(\)/);
  assert.match(workbench, /requestAnimationFrame\(restoreTop\)/);
  assert.match(workbench, /setTimeout\(restoreTop, 180\)/);
  assert.match(workbench, /window\.addEventListener\(name, stopOnInteraction/);
  assert.match(workbench, /slicerEditorOpen/);
  assert.doesNotMatch(workbench, /scrollIntoView\(\{ behavior: "smooth" \}\)/);
  assert.match(styles, /\.slicerWorkbenchRoot\.slicerEditorOpen \{ overflow-anchor: none; \}/);
});

test("auto-measured planar patch is highlighted by its detected mesh triangles", () => {
  assert.match(detection, /const highlightPositions = \[\]/);
  assert.match(detection, /highlightPositions\.push\(vertex\.x, vertex\.y, vertex\.z\)/);
  assert.match(detection, /MAX_HIGHLIGHT_TRIANGLES/);
  assert.match(editor, /detectedFeature\.kind === "face"/);
  assert.match(editor, /detectedFeature\.highlightPositions/);
  assert.match(editor, /new THREE\.Float32BufferAttribute\(detectedFeature\.highlightPositions, 3\)/);
  assert.match(editor, /opacity: 0\.38, depthTest: true, depthWrite: false/);
  assert.match(editor, /overlay\.remove\(item\)/);
  assert.match(editor, /item\.geometry\?\.dispose\(\)/);
});
