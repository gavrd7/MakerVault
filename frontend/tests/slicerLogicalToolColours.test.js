import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const read = f => readFileSync(new URL("../src/components/" + f, import.meta.url), "utf8");
const viewer = read("SlicerGcodePreview.jsx");
const render = read("SlicerToolpath3D.jsx");

test("filament tool view needs explicit G-code tool identity", () => {
  assert.match(viewer, /preview\?\.observed_tools\?\.length/);
  assert.match(viewer, /Logical filament \/ tool/);
  assert.match(viewer, /CFS\/AMS bay mapping/);
  assert.match(viewer, /slicerLogicalToolNotice/);
});
test("logical filament rendering reads the tool number, never a slot RGB guess", () => {
  assert.match(render, /const logicalTool = segment\[7\]/);
  assert.match(render, /colourMode === "filament"/);
  assert.match(render, /Number\.isInteger\(logicalTool\)/);
});
