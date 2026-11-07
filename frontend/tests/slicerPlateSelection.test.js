import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const file = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../src/components/SlicerPlateEditor.jsx");
const source = fs.readFileSync(file, "utf8");

test("auto-arrange clears explicit mesh highlighting without clearing the selected-model controls", () => {
  assert.match(source, /onChange\(result\.objects\);\s*\/\/ Arranging[^]*?setSelected\("");/);
  assert.match(source, /mesh\.material\.emissive\.set\(item\.instance_id === selected \?/);
  assert.doesNotMatch(source, /chosen\?\.instance_id \|\| selected/);
  assert.match(source, /const chosen = objects\.find\([^]*?\|\| objects\[0\] \|\| null/);
});

test("plate movement retains stored preview colours and clears residual emission", () => {
  assert.match(source, /mesh\.material\.color\.set\(item\.color \|\| PALETTE\[0\]\)/);
  assert.match(source, /mesh\.material\.emissiveIntensity = item\.instance_id === selected \? 0\.18 : 0/);
});
