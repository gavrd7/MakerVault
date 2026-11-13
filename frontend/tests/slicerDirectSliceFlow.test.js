import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "src/components/SlicerWorkbench.jsx"), "utf8");

test("main workbench directly submits approved slicing jobs after draft creation", () => {
  assert.match(source, /onClick=\{\(\) => saveDraft\("quick"\)\}/);
  assert.match(source, /Quick slice/);
  assert.match(source, /const sliceNow = !\["draft","project"\]\.includes\(mode\)/);
  assert.match(source, /apiFetch\("\/api\/printing\/slicer\/jobs\/" \+ job\.id \+ "\/start\/"/);
  assert.match(source, /workerConfigured && engines\.some/);
});

test("a failed worker queue leaves a visible, retrievable saved draft", () => {
  assert.match(source, /Draft saved, but slicing could not start:/);
  assert.match(source, /if \(savedJob\) setShowDrafts\(true\)/);
  assert.match(source, /Generated G-code will remain private unless you add it to the library/);
});

test("visual build plate is the only model selector for slicing", () => {
  assert.doesNotMatch(source, /<label className="full">Model STL/);
  assert.match(source, /input_asset_id: plateObjects\[0\]\?\.asset_id/);
  assert.match(source, /\(sliceNow&&mode!=="all"\)\?plateObjects\.length:projectPlates\.some/);
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

test("printer model catalogue failures are shown to the user", () => {
  assert.match(source, /Could not load printer models from the official catalogue/);
  assert.match(source, /setOfficialError\(/);
});

test("manual model search overrides dropdown without requiring a model selection", () => {
  assert.match(source, /Manual printer\/model search \(optional\)/);
  assert.match(source, /const q = \[officialManualModel\.trim\(\), officialQuery\.trim\(\)\]/);
  assert.match(source, /!officialManualModel\.trim\(\) && officialModel/);
  assert.match(source, /Typing here overrides the printer-model dropdown/);
});

test("plate actions call the shared workflow directly and show local errors", () => {
  assert.match(source, /onClick=\{\(\) => saveDraft\("draft"\)\}/);
  assert.match(source, /onClick=\{\(\) => saveDraft\("quick"\)\}/);
  assert.match(source, /className="slicerPlateActionFeedback"/);
  assert.match(source, /role="alert">\{error\}/);
  assert.match(source, /Choose an engine version, printer and valid nozzle diameter/);
});

test("saved drafts can be deleted without touching model files", () => {
  assert.match(source, /can_delete === true/);
  assert.match(source, /\["draft", "failed", "cancelled", "stale"\]\.includes\(job\.status\)/);
  assert.match(source, /method: "DELETE"/);
  assert.match(source, /Delete draft/);
  assert.match(source, /Separately saved files were preserved/);
});

test("three distinct plate actions control draft creation, quick slice and interactive editing", () => {
  assert.match(source, /onClick=\{\(\) => saveDraft\("draft"\)\}/);
  assert.match(source, /onClick=\{\(\) => saveDraft\("quick"\)\}/);
  assert.match(source, /Slice → Interactive slicer/);
  assert.match(source, /const saveOutput = mode === "save-and-slice"/);
  assert.match(source, /save_gcode_to_library: saveOutput, workflow/);
  assert.doesNotMatch(source, /All three native profiles require administrator verification/);
});

test("temporary models are supported without adding STL to the files library", () => {
  assert.match(source, /A temporary STL has not finished uploading/);
  assert.doesNotMatch(source, /first import those STL files with/);
});

test("failed jobs expose a delete action while active jobs remain protected", () => {
  assert.match(source, /mayDeleteDraft && \["draft", "failed", "cancelled", "stale"\]\.includes\(job\.status\)/);
  assert.match(source, /job\.status === "draft" \? "Delete draft" : "Delete"/);
});

test("multi-plate projects preserve every plate but slice only the active plate",()=>{
  assert.match(source,/const \[projectPlates,setProjectPlates\]/);
  assert.match(source,/const \[activePlateId,setActivePlateId\]/);
  assert.match(source,/plates:projectPlates\.map/);
  assert.match(source,/active_plate_id:activePlateId/);
  assert.match(source,/plate_objects: plateObjects/);
  assert.match(source,/setProjectPlates\(restored\)/);
});

test("explicit slice-all creates independent queued jobs, while default Slice is unchanged",()=>{
  assert.match(source,/if\(mode==="all"\)/);
  assert.match(source,/for\(const target of targets\)/);
  assert.match(source,/active_plate_id:target\.id/);
  assert.match(source,/plate_objects:target\.objects/);
  assert.match(source,/onSliceAll=\{\(\) => saveDraft\("all"\)\}/);
  assert.match(source,/onSlice=\{\(\) => saveDraft\("slice"\)\}/);
});
test("3mf project export uses owner-scoped server endpoint",()=>{
  assert.match(source,/export-project\//);
  assert.match(source,/link\.download="MakerVault-project\.3mf"/);
});
