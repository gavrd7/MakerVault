import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "src/components/SlicerWorkbench.jsx"), "utf8");

test("main workbench directly submits approved slicing jobs after draft creation", () => {
  assert.match(source, /value="slice" className="primary"/);
  assert.match(source, /Save and slice/);
  assert.match(source, /event\.nativeEvent\?\.submitter\?\.value === "slice"/);
  assert.match(source, /apiFetch\("\/api\/printing\/slicer\/jobs\/" \+ job\.id \+ "\/start\/"/);
  assert.match(source, /workerConfigured && engines\.some/);
});

test("a failed worker queue leaves a visible, retrievable saved draft", () => {
  assert.match(source, /Draft saved, but slicing could not start:/);
  assert.match(source, /if \(savedJob\) setShowDrafts\(true\)/);
  assert.match(source, /No print was started or filament deducted/);
});
