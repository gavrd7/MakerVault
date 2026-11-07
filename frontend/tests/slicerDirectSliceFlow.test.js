import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "src/components/SlicerWorkbench.jsx"), "utf8");

test("main workbench directly submits approved slicing jobs after draft creation", () => {
  assert.match(source, /form="slicer-configuration-form" value="slice" className="primary"/);
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

test("visual build plate is the only model selector for slicing", () => {
  assert.doesNotMatch(source, /<label className="full">Model STL/);
  assert.match(source, /input_asset_id: plateObjects\[0\]\.asset_id/);
  assert.match(source, /if \(!plateObjects\.length\)/);
  assert.match(source, /!plateObjects\.length \|\| !printers\.length/);
});

test("slicer profile actions are consolidated in the saved profiles modal", () => {
  assert.doesNotMatch(source, /profileModal === "manage"/);
  assert.doesNotMatch(source, />Manage profiles<\/button>/);
  assert.match(source, /setManagingSavedProfiles\(current => !current\)/);
  assert.match(source, /Saved profiles \(/);
  assert.match(source, /<ProfileActionIcon name="bookmark"/);
  assert.match(source, /<ProfileActionIcon name="upload"/);
});

test("profile selectors replace duplicate editable preset labels", () => {
  assert.match(source, /\["printer", "filament", "process"\]\.map\(kind/);
  assert.doesNotMatch(source, /Engine printer preset \(draft label\)/);
  assert.doesNotMatch(source, /Engine filament preset \(draft label\)/);
  assert.doesNotMatch(source, /Engine process preset \(draft label\)/);
  assert.match(source, /id="slicer-configuration-form"/);
  assert.match(source, /footer=\{<>/);
});

test("profile import screens provide back navigation and local success feedback", () => {
  assert.match(source, /Back to selected profiles/);
  assert.match(source, /Back to official profiles/);
  assert.match(source, /View saved profiles/);
  assert.match(source, /officialImportNotice && <p role="status"/);
  assert.match(source, /setOfficialImportNotice\(imported\.name/);
});

test("official profile search lists catalogue models and scopes fuzzy results", () => {
  assert.match(source, /models: "1"/);
  assert.match(source, /Printer model/);
  assert.match(source, /officialModels\.map\(model/);
  assert.match(source, /All models \/ generic profiles/);
  assert.match(source, /params\.set\("model", officialModel\)/);
  assert.match(source, /name-based, not verified compatibility/);
});
