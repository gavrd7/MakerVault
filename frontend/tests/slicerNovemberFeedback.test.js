import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const base = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const read = name => fs.readFileSync(path.join(base,name),"utf8");
const setup = read("SlicerWorkbench.jsx");
const styles = fs.readFileSync(path.resolve(base, "../styles.css"), "utf8");
const prepare = read("SlicerPrepareWorkspace.jsx");
const plate = read("SlicerPlateEditor.jsx");

test("engine version is selected from known discovered versions, not typed", () => {
  assert.match(setup, /const engineVersions =/);
  assert.match(setup, /installed_versions/);
  assert.match(setup, /<label>Engine version\s*<select required/);
  assert.match(setup, /Profiles only/);
  assert.doesNotMatch(setup, /placeholder="Exact installed\/version-matched engine version"/);
});

test("named imported material profile is available to assigned slot even when reused as parent", () => {
  assert.match(setup, /const slotFilamentChoices = useMemo\(\(\) => profiles\.filter/);
  assert.match(setup, /filamentProfiles=\{slotFilamentChoices\}/);
  assert.ok(setup.includes(String.raw`!/@\s*.*\bbase\s*$/i.test(profile.name`));
  assert.match(prepare, /onFilamentProfilesReload\?\.\(imported\)/);
  assert.match(prepare, /assignLoadedSlotProfile\(slot,String\(imported\.id\)\)/);
  assert.match(prepare, /Import & assign/);
});

test("variable layer editor can position a selected thickness band", () => {
  assert.match(prepare, /aria-label="Variable layer height Z band thickness"/);
  assert.match(prepare, /type="range" min="0\.5" max="50" step="0\.5"/);
  assert.match(prepare, /Position entire band/);
  assert.match(prepare, /onVariableLayerHeightPick=\{z=>/);
});

test("semantic painting is tool-specific while coloured preview is retained", () => {
  assert.match(plate, /toolMode==="paint_support"\?item\.support_paint:null/);
  assert.match(plate, /toolMode==="paint_seam"\?item\.seam_paint:null/);
  assert.match(plate, /toolMode==="paint_fuzzy"\?item\.fuzzy_skin_paint:null/);
  assert.match(plate, /paintPreview\(mesh, \{\.\.\.item,colour_paint:item\.colour_paint\}/);
  assert.match(plate, /latestToolModeRef\.current==="paint_support"/);
});

test("Creality v7.3.0 legacy imports are explicitly flagged, never silently relabelled as 7.3.1", () => {
  assert.match(setup, /CrealityOfficial\/CrealityPrint@v7\.3\.0\//);
  assert.match(setup, /Legacy v7\.3\.0 manufacturer preset under a 7\.3\.1 engine label/);
  assert.match(setup, /Matching native release is required before importing/);
  assert.match(setup, /This saved preset has not been changed/);
});

test("official catalogue version always follows selected slicer engine", () => {
  assert.match(setup, /const targetVersion = form\.engine_version;/);
  assert.match(setup, /engine_version: form\.engine_version,/);
  assert.match(setup, /Matching official profile release/);
  assert.doesNotMatch(setup, /Follows the selected slicing engine/);
  assert.match(setup, /className="slicerOfficialSourceField">Official source/);
  assert.match(setup, /className="slicerOfficialSourceField">Matching official profile release/);
  assert.doesNotMatch(setup, /Native OrcaSlicer profile release/);
  assert.doesNotMatch(setup, /"2\.5\.0"\) \? form\.engine_version : "2\.5\.0"/);
});

test("profile removal feedback is visible in the saved modal and requires server confirmation", () => {
  assert.match(setup, /profileRemoveError && <p className="integrationError" role="alert">/);
  assert.match(setup, /profileRemoveNotice && <p role="status">/);
  assert.match(setup, /result\?\.removed !== true/);
  assert.match(setup, /setProfileRemoveError\("Unable to remove/);
  assert.match(setup, /setProfiles\(current => current\.filter/);
});

test("saved slicing jobs support draft/slice filters and explicit bulk cleanup", () => {
  assert.match(setup, /Filter saved drafts and slices/);
  assert.match(setup, /Drafts \(not sliced\)/);
  assert.match(setup, /Completed slices/);
  assert.match(setup, /Select all filtered/);
  assert.match(setup, /Delete selected \(\{selectedSavedJobCount\}\)/);
  assert.match(setup, /Remove all drafts/);
  assert.match(setup, /Remove all slices/);
  assert.match(setup, /Remove all unsaved G-code/);
  assert.match(setup, /printing\/slicer\/jobs\/bulk-delete\//);
  assert.match(setup, /printing\/slicer\/jobs\/remove-unsaved-gcode\//);
  assert.match(setup, /if \(!window\.confirm\(/);
});

test("saved slices reuse owner-private generated G-code thumbnails", () => {
  assert.match(setup, /function SlicerJobThumbnail\(\{ job \}\)/);
  assert.match(setup, /SlicerJobThumbnail key=\{job\.id/);
  assert.match(setup, /printing\/slicer\/jobs\/.*thumbnail\//);
  assert.match(setup, /onError=\{\(\) => setUnavailable\(true\)\}/);
});

test("saved slicer entries keep thumbnails and buttons aligned, with shaded 3D model previews", () => {
  assert.match(setup, /cameraSourceRow slicerSavedJobRow/);
  assert.match(setup, /SlicerJobThumbnail key=\{job\.id/);
  assert.match(setup, /ModelThumbnail file=\{model\}/);
  assert.match(setup, /singleModel && !painted/);
  assert.match(setup, /slicerSavedJobModelPreview/);
  assert.match(setup, /printing\/slicer\/jobs\/.*thumbnail\//);
});

test("saved draft status filter sits below the actions and right aligned above entries", () => {
  const toolbar = setup.indexOf('<div className="settingsActions slicerSavedJobToolbar">');
  const filter = setup.indexOf('<div className="slicerSavedJobFilterRow">');
  const entries = setup.indexOf('{filteredSavedJobs.length ? <div className="printingStack">');
  assert.ok(toolbar >= 0 && filter > toolbar && entries > filter);
  const toolbarContents = setup.slice(toolbar, filter);
  assert.match(toolbarContents, /Remove all unsaved G-code/);
  assert.doesNotMatch(toolbarContents, /Filter saved drafts and slices/);
  assert.match(setup.slice(filter, entries), /Filter saved drafts and slices/);
});

test("selection checkbox is absolutely placed in a reserved gutter, never changes saved row columns", () => {
  assert.match(setup, /className="slicerSavedJobCheckbox"/);
  assert.match(styles, /\.cameraSourceRow\.slicerSavedJobRow\{[\s\S]*?position:relative;[\s\S]*?padding-left:44px;/);
  assert.match(styles, /\.slicerSavedJobRow>\.slicerSavedJobCheckbox\{[\s\S]*?position:absolute;/);
  assert.doesNotMatch(styles, /slicerSavedJobRow:has\(> label\.checkRow\)/);
  assert.match(styles, /@media\(max-width:1100px\)\{[\s\S]*?slicerSavedJobRow>[.]cameraSourceActions/);
});

test("bulk selection actions have dedicated spaced row and readable help below", () => {
  assert.match(setup, /className="slicerSavedJobSelectionBar" role="group"/);
  assert.match(setup, /className="slicerSavedJobSelectionHelp"/);
  assert.match(styles, /\.slicerSavedJobSelectionBar\{[\s\S]*?column-gap:12px;row-gap:10px;[\s\S]*?margin:16px 0 18px;/);
  assert.match(styles, /\.slicerSavedJobSelectionHelp\{[\s\S]*?flex-basis:100%/);
  assert.match(styles, /\.settingsActions\.slicerSavedJobToolbar\{[\s\S]*?flex-wrap:wrap/);
});

test("official source and matching release controls use equal height without caption stretching", () => {
  assert.doesNotMatch(setup, /Switch engine version above to use another verified native catalogue/);
  assert.match(styles, /\.formGrid>\.slicerOfficialSourceField/);
  assert.match(styles, /height:48px;/);
  const source = setup.indexOf('className="slicerOfficialSourceField">Official source');
  const version = setup.indexOf('className="slicerOfficialSourceField">Matching official profile release');
  const following = setup.indexOf('Manufacturer / upstream catalogue', version);
  assert.ok(source >= 0 && version > source && following > version);
  assert.doesNotMatch(setup.slice(version, following), /<small>/);
});

test("official catalogue filters are truly optional across engines", () => {
  assert.match(setup, /if \(q\.length > 80\) throw new Error/);
  assert.match(setup, /disabled=\{officialBusy \|\| !officialVendor \|\| !officialVendors\.length\}/);
  assert.doesNotMatch(setup, /join\(" "\)\.length < 2/);
});

test("official profile import cards stack on mobile and feedback spans full width", () => {
  assert.match(setup, /cameraSourceRow slicerOfficialProfileRow/);
  assert.match(styles, /\.slicerOfficialProfileRow>\.slicerProfileImportNotice,[\s\S]*?grid-column:1\/-1/);
  assert.match(styles, /@media\(max-width:800px\)\{[\s\S]*?\.cameraSourceRow\.slicerOfficialProfileRow\{/);
  assert.match(styles, /\.slicerOfficialProfileRow>\.cameraSourceActions button\{[\s\S]*?flex:1 1 160px/);
});

test("official profile browsing is not silently narrowed to the selected printer", () => {
  const start = setup.indexOf('  // Catalogue models come from the pinned upstream index');
  const end = setup.indexOf('  async function searchOfficialProfiles(', start);
  const browse = setup.slice(start, end);
  assert.match(browse, /setOfficialModels\(models\);/);
  assert.doesNotMatch(browse, /models\.find\(item =>/);
  assert.ok(setup.includes('setOfficialQuery("");'));
});

test("device monitor stays over the slicer without navigating away or unmounting its draft", () => {
  const printing = fs.readFileSync(path.resolve(base, "PrintingPage.jsx"), "utf8");
  const app = fs.readFileSync(path.resolve(base, "../App.jsx"), "utf8");
  const start = printing.indexOf('  if (workspaceView === "slicer") {');
  const end = printing.indexOf('  if (workspaceView === "models") {', start);
  assert.ok(start >= 0 && end > start);
  const workspace = printing.slice(start, end);
  assert.match(workspace, /onOpenDevice=\{printerId => \{/);
  assert.match(workspace, /setLivePrinter\(printer\)/);
  assert.match(workspace, /livePrinter && <PrinterConnectionsModal/);
  assert.match(workspace, /onClose=\{\(\) => setLivePrinter\(null\)\}/);
  assert.doesNotMatch(workspace.slice(workspace.indexOf("onOpenDevice="), workspace.indexOf("onOpenGcode=")), /setWorkspaceView|setSection/);
  assert.doesNotMatch(app, /onOpenSlicerDevice=/);
});
