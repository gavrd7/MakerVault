import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const read = name => fs.readFileSync(path.join(root, name), "utf8");

test("setup is retained and a separate interactive Prepare workspace is available", () => {
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(workbench, /Slicer setup/);
  assert.match(workbench, /Slice → Interactive slicer/);
  assert.match(workbench, /onClick=\{\(\) => saveDraft\("quick"\)\}/);
  assert.match(workbench, /onClick=\{\(\) => saveDraft\("draft"\)\}/);
  assert.match(workbench, /editorOpen \? <SlicerPrepareWorkspace/);
  assert.match(workbench, /setEditorOpen\(true\)/);
  assert.match(workbench, /onSaveDraft=\{\(\) => saveDraft\("draft"\)\}/);
  assert.match(workbench, /onSlice=\{\(\) => saveDraft\("slice"\)\}/);
  assert.doesNotMatch(workbench, /onSaveAndSlice=/);
});

test("editor provides actual model tree, undo redo and existing placement operations", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const plate = read("SlicerPlateEditor.jsx");
  assert.match(scene, /onChange\(previous\)/);
  assert.match(scene, /onChange\(next\)/);
  assert.match(scene, /onPrimaryChange\?\.\(next\[0\]\?\.asset_id \|\| ""\)/);
  assert.match(scene, /Ctrl\+Z/);
  assert.match(scene, /aria-label="Build plate object tree"/);
  assert.match(scene, /selectedInstanceId=\{selectedId\}/);
  assert.match(scene, /onSelectedInstanceChange=\{selectSingle\}/);
  for (const tool of ["Move", "Rotate", "Scale", "Auto-arrange", "Duplicate"]) {
    assert.match(scene, new RegExp('name: "' + tool + '"'));
  }
  assert.match(plate, /data-slicer-action="arrange"/);
  assert.match(plate, /data-slicer-action="duplicate"/);
  assert.match(plate, /data-slicer-field="x_mm"/);
});

test("measurement, centre and focus toolbar actions are functional and guarded", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  for (const tool of ["Measure", "Centre selected", "Fit selected"])
    assert.match(scene, new RegExp('name: "' + tool + '", target:'));
  assert.match(scene, /tool.target === "measure"/);
  assert.match(scene, /measurementVisible=\{measurementVisible\}/);
  assert.match(editor, /aria-label="Selected model measurements"/);
  assert.match(editor, /plateModelMeasurement\(chosen, dimensions\[chosen.instance_id\]\)/);
  assert.match(editor, /data-slicer-action="center"/);
  assert.match(editor, /data-slicer-action="focus"/);
  assert.match(editor, /applySelectedTransform\(\{ x_mm: 0, y_mm: 0 \}/);
  assert.match(editor, /height: box.max.z - box.min.z/);
  assert.match(editor, /aria-label="Selected model measurements"/);
});
test("surface picking measures triangle vertices and edges without editing slice geometry", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(scene, /setToolMode\("select"\)/);
  assert.match(scene, /setMeasurementVisible\(false\)/);
  assert.match(editor, /raycaster\.intersectObjects\(\[\.\.\.meshes\.values\(\)\], false\)/);
  assert.match(editor, /latestMeasurementRef\.current\.active/);
  assert.match(editor, /hit\.face\.a, hit\.face\.b, hit\.face\.c/);
  assert.match(editor, /closestPointToPoint\(hit\.point, true/);
  assert.match(editor, /bestEdgeLength = a\.distanceTo\(b\)/);
  assert.match(editor, /Triangle segment length:/);
  assert.match(scene, /measureSnapMode=\{measureSnapMode\}/);
  assert.match(editor, /setMeasurePoints\(current =>/);
  assert.match(editor, /3D distance:/);
  assert.match(scene, /Three-point circle/);
  assert.match(scene, /Millimetres \(mm\)/);
  assert.match(scene, /Inches \(in\)/);
  assert.match(editor, /measureMode === "circle"/);
  assert.match(editor, /setMeasurePoints\(\[\]\); setDetectedFeature\(null\); \}, \[objects, measureMode, measureClearVersion\]\)/);
});
test("Measure options open at the toolbar while a compact readout lives at top left of the plate", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(scene, /name: "Measure", target: "measure", icon: "measure", expandable: true/);
  assert.match(scene, /aria-controls=\{tool\.target === "import" \? "slicer-add-model-toolbar-options" : tool\.target === "auto_orient" \? "slicer-auto-orient-toolbar-options" : tool\.expandable \? "slicer-measure-toolbar-options"/);
  assert.match(scene, /className="slicerToolOptions"/);
  assert.match(scene, /measureMode=\{measureMode\} measureUnit=\{measureUnit\} measureSnapMode=\{measureSnapMode\}\s+measureClearVersion=\{measureClearVersion\}/);
  assert.match(scene, /setMeasureClearVersion\(value => value \+ 1\)/);
  assert.match(scene, /onMeasurePinPlaced=\{\(\) => setMeasureOptionsOpen\(false\)\}/);
  assert.match(scene, /setMeasureOptionsOpen\(current => !current\)/);
  assert.match(scene, /Finish measuring/);
  assert.match(editor, /measurePinPlacedRef\.current\?\.\(\)/);
  assert.match(editor, /className="slicerPlateCanvasViewport"/);
  assert.match(editor, /className="slicerViewportMeasurement"/);
  assert.match(editor, /aria-label="On-plate measurements"/);
  assert.match(editor, /pinDistance !== null/);
  assert.match(editor, /measureOverlayExpanded/);
  assert.match(editor, /measureClearVersion\]\)/);
  assert.doesNotMatch(editor, /Choose measurement mode, units and Clear pins from the expandable/);
  assert.match(css, /\.slicerToolOptions \{/);
  assert.match(css, /\.slicerViewportMeasurement \{/);
  assert.match(css, /position: absolute;/);
  assert.match(css, /@media \(max-width: 700px\)/);
});
test("active 3D model has a temporary outline and preserves preview filament colours", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(scene, /selectMultiple\(object.instance_id, event.ctrlKey/);
  assert.match(editor, /const helper = new THREE.BoxHelper\(mesh, 0x39d9ff\)/);
  assert.match(editor, /selectionOutlines\.forEach\(helper=>helper\.update\(\)\)/);
  assert.match(editor, /state\.setSelectionOutlines\(toolMode === "paint_colour" \? \[\] : selection\.map\(id=>state\.meshes\.get\(id\)\)/);
  assert.match(editor, /paintPreview\(mesh, item, PALETTE\[0\]\)/);
  assert.match(editor, /selection.includes\(item.instance_id\) \? "#168ab4" : "#000000"/);
  assert.match(editor, /setSelectionOutlines\(\[\]\)/);
  // Sorting or arranging must not activate a model merely because it was last touched.
  assert.match(editor, /setSelected\(""\)/);
});
test("advanced tools are visibly gated pending safe native transformations", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  for (const tool of ["Support painting", "Seam painting", "Variable layer height"]) {
    assert.match(scene, new RegExp('name: "' + tool + '", icon: "[^"]+", pending:'));
  }
  assert.match(scene, /name: "Colour painting", target: "paint_colour", icon: "paint-colour"/);
  assert.match(scene, /disabled=\{!!tool.pending/);
  assert.match(scene, /name: "Add plate", target: "add_plate"/);
  assert.match(scene, /name: "Lay on face", target: "lay_face", icon: "face"/);
  assert.match(scene, /name: "Auto-orient", target: "auto_orient", icon: "orient"/);
  for (const group of ["Quality", "Strength", "Speed", "Supports", "Multifilament", "Others"])
    assert.match(scene, new RegExp('"' + group + '"'));
  assert.match(scene, /Wall loops and sparse infill density have passed native Orca/);
  assert.match(scene, /verifiedObjectSettings = new Set\(\["wall_loops", "sparse_infill_density"\]\)/);
  assert.match(scene, /Object settings are not yet verified for slicing|Some Object settings are not yet verified for slicing/);
  assert.match(scene, /process_overrides: changed/);
  assert.match(scene, /Clear object overrides/);
  assert.match(scene, /nativeProcessFields/);
  assert.match(scene, /processOverrides/);
  assert.match(scene, /Restore profile defaults/);
});

test("independent XYZ scaling updates visual mesh and is selectable from the toolbar", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(scene, /name: "Scale", target: "scale_percent"/);
  assert.doesNotMatch(scene, /name: "Individual XYZ scale"/);
  assert.match(editor, /Independent axis scaling \(%\)/);
  assert.match(editor, /data-slicer-field=\{index === 0 \? "scale_xyz_percent"/);
  assert.match(editor, /mesh\.scale\.set\(\.\.\.xyz\.map\(v => v \/ 100\)\)/);
});

test("duplicating a selected model preserves every saved transformation", () => {
  const plate = read("SlicerPlateEditor.jsx");
  assert.match(plate, /const copy = \{ \.\.\.chosen, instance_id: plateUuid\(\) \}/);
  assert.match(plate, /copy\.scale_xyz_percent = \[\.\.\.chosen\.scale_xyz_percent\]/);
  assert.match(plate, /pendingArrangeRef\.current = true/);
  assert.match(plate, /onClick=\{duplicateSelected\}>Duplicate selected/);
});

test("slicer setup offers Save draft / Quick slice / interactive Slice at plate footer", () => {
  const workbench = read("SlicerWorkbench.jsx");
  const footer = workbench.indexOf('className="slicerDraftActions settingsActions"');
  const end = workbench.indexOf('      </>}', footer);
  const buttons = workbench.slice(footer, end);
  assert.match(buttons, /Save draft/);
  assert.match(buttons, /Quick slice/);
  assert.match(buttons, /Slice → Interactive slicer/);
  assert.ok(buttons.indexOf("Save draft") < buttons.indexOf("Quick slice"));
  assert.ok(buttons.indexOf("Quick slice") < buttons.indexOf("Slice → Interactive slicer"));
  assert.doesNotMatch(workbench.slice(workbench.indexOf('className="slicerSetupHeading"'), workbench.indexOf('className="slicerSetupHeading"') + 250), /Open interactive slicer/);
  assert.match(buttons, /disabled=\{!canPrepare \|\| busy \|\| loading\}/);
});

test("quick slice remains private and does not expose direct upload/start actions", () => {
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(workbench, /const workflow = mode === "quick" \? "quick"/);
  assert.match(workbench, /save_gcode_to_library: saveOutput, workflow/);
  assert.match(workbench, /previewJob\.settings\?\.workflow !== "quick"/);
  assert.match(workbench, /job\.settings\?\.workflow !== "quick"/);
});

test("model gizmos and profile switch are accessible without leaving Prepare", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const plate = read("SlicerPlateEditor.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(scene, /toolMode=\{toolMode\}/);
  assert.match(scene, /onClick=\{onChangeProfiles\}/);
  assert.match(scene, /Change profiles/);
  assert.match(scene, /onClick=\{\(\) => setScope\("objects"\)\}>Object</);
  assert.match(plate, /new TransformControls\(camera, renderer\.domElement\)/);
  assert.match(plate, /transform\.setTranslationSnap\(0\.5\)/);
  assert.match(plate, /transform\.setRotationSnap/);
  assert.match(plate, /validPlacement\(candidate, current\)/);
  assert.match(workbench, /profileModal === "change"/);
  assert.match(workbench, /onChangeProfiles=\{\(\) => setProfileModal\("change"\)\}/);
  assert.match(scene, /SlicerUiIcon name=\{tool\.icon/);
});

test("live CFS AMS RFID slots support draft assignments without enabling unverified tool changes", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  assert.match(scene, /apiFetch\("\/api\/printing\/\?include_filaments=0"\)/);
  assert.match(scene, /\.filter\(slot => slot\.is_loaded\)/);
  assert.match(scene, /slot\.spool_code/);
  assert.match(scene, /material_slot:materialSlot/);
  assert.match(scene, /materialRoutingPending/);
  assert.match(scene, /flushSettings != null/);
  assert.match(scene, /physical multi-material path is not yet enabled/);
  assert.match(scene, /live slot-to-tool bindings and physical changeovers are not yet verified/);
});

test("switching registered printers invalidates physical CFS slots and flush volumes", () => {
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(workbench, /const changeSessionPrinter = printerId =>/);
  assert.match(workbench, /setFlushSettings\(null\)/);
  assert.match(workbench, /setProjectPlates\(current => current\.map\(plate => \(\{/);
  assert.match(workbench, /material_slot: oldSlot/);
  assert.match(workbench, /spool_id: ""/);
});

test("icon toolbar tooltips show names and unavailable reasons on hover and focus", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const styles = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(scene, /className="slicerToolTooltip"/);
  assert.match(scene, /data-tooltip=\{tool\.pending \? tool\.name/);
  assert.match(scene, /Not yet available:/);
  assert.match(scene, /aria-label=\{tool\.name\}/);
  assert.match(styles, /\.slicerToolTooltip:hover::after/);
  assert.match(styles, /\.slicerToolTooltip:focus-within::after/);
});


test("native process controls are read from the selected process profile and round-trip with drafts", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(scene, /\/settings\//);
  assert.match(scene, /spec\.minimum/);
  assert.match(scene, /spec\.maximum/);
  assert.match(scene, /onProcessOverridesChange/);
  assert.match(workbench, /job\.settings\?\.process_overrides/);
  assert.match(workbench, /process_overrides: processOverrides/);
});

test("interactive settings can be saved as a selected reusable native process profile", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(scene, /Save as custom profile/);
  assert.match(scene, /Save and select profile/);
  assert.match(scene, /onSaveCustomProcessProfile\(customProfileName\)/);
  assert.match(scene, /customProfileError/);
  assert.match(workbench, /async function saveInteractiveProcessProfile/);
  assert.match(workbench, /\/save-process\//);
  assert.match(workbench, /process_profile_id: saved.id/);
  assert.match(workbench, /setProcessOverrides\(\{\}\)/);
});

test("native process options remain searchable and gated behind Basic/Advanced", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  assert.match(scene, /Find a setting/);
  assert.match(scene, /value=\{settingsLevel\}/);
  assert.match(scene, /value="advanced"/);
  assert.match(scene, /nativeProcessFields/);
  assert.match(scene, /spec\.options\.map/);
  assert.match(scene, /updateNativeChoice/);
  assert.match(scene, /processOverrides\[key\] \?\? spec\.current/);
});

test("slicer lazy-load failures display recovery UI instead of blanking MakerVault", () => {
  const printing = read("PrintingPage.jsx");
  const boundary = read("SlicerErrorBoundary.jsx");
  const vite = fs.readFileSync(path.resolve(root, "../../vite.config.js"), "utf8");
  assert.match(printing, /<SlicerErrorBoundary onBack=/);
  assert.match(printing, /<Suspense fallback=/);
  assert.match(boundary, /getDerivedStateFromError/);
  assert.match(boundary, /Reload MakerVault/);
  assert.match(boundary, /Back to 3D Printing/);
  assert.match(boundary, /dynamically imported module/);
  assert.match(vite, /chunk-\[name\]-\[hash\]\.js/);
});

test("native process selector and reset are available above scoped print settings", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(scene, /Process profile/);
  assert.match(scene, /id="slicer-process-quick-select"/);
  assert.match(scene, /processProfiles\.map/);
  assert.match(scene, /onSelectProcessProfile\?\./);
  assert.match(scene, /onResetProcessSettings\?\./);
  assert.match(workbench, /processProfiles=\{forKind\("process"\)\}/);
  assert.match(workbench, /onSelectProcessProfile=\{id =>/);
  assert.match(workbench, /Discard unsaved print settings/);
});

test("Basic and Advanced are defined by native profile schema rather than a frontend key list", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  assert.match(scene, /spec\.level === "basic"/);
  assert.match(scene, /spec\.section/);
  assert.match(scene, /nativeSections\.map/);
  assert.match(scene, /visibleNativeFields\.filter/);
  assert.match(scene, /spec\.kind === "toggle"/);
  assert.match(scene, /type="checkbox" aria-label=\{spec\.label\}/);
});

test("print settings scroll inside their own rail and expand into the same shared editor modal", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(scene, /createPortal/);
  assert.match(scene, /const settingsPanel =/);
  assert.match(scene, /settingsExpanded \? createPortal/);
  assert.match(scene, /: settingsPanel/);
  assert.match(scene, /aria-modal="true"/);
  assert.match(scene, /Expand settings/);
  assert.match(scene, /Close expanded settings/);
  assert.match(scene, /event.key === "Escape"/);
  assert.match(css, /\.slicerPrepareSettings\{\s*max-height:/);
  assert.match(css, /overflow-y:auto/);
  assert.match(css, /\.slicerSettingsModalBackdrop\{/);
  assert.match(css, /\.slicerSettingsModal\{/);
});

test("selected model tool row wraps within its panel and never exceeds available width", () => {
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(css, /\.slicerPrepareScene \.slicerPlateTransformFields > \.settingsActions\{/);
  assert.match(css, /flex-wrap:wrap/);
  assert.match(css, /\.slicerPrepareScene \.slicerPlateTransformFields > \.settingsActions > button\{/);
  assert.match(css, /max-width:100%/);
  assert.match(css, /overflow-wrap:anywhere/);
});

test("rotation and scale have separate safe resets without moving the object", () => {
  const editor = read("SlicerPlateEditor.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(editor, /id="slicer-model-rotation"/);
  assert.match(editor, /id="slicer-model-uniform-scale"/);
  assert.match(editor, /Reset rotation to the model's imported orientation/);
  assert.match(editor, /applySelectedTransform\(\{ rotation_deg: 0 \}/);
  assert.match(editor, /Restore 100% scale for all three axes/);
  assert.match(editor, /scale_percent: 100, scale_xyz_percent: \[100, 100, 100\]/);
  assert.match(editor, /Resetting the rotation would overlap/);
  assert.match(editor, /Resetting the scale would overlap/);
  assert.match(css, /\.slicerTransformInputRow\{/);
  assert.match(css, /\.slicerTransformInputRow>button\{/);
});


test("expand settings lives next to Detail and conditional native fields use schema dependencies", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  const header = scene.slice(scene.indexOf('className="slicerSettingsPanelHeader"'),
    scene.indexOf('className="slicerProcessQuickSelect"'));
  assert.doesNotMatch(header, /Expand settings/);
  const searchStart = scene.indexOf('className="slicerSettingsSearchRow"');
  assert.ok(searchStart >= 0);
  const searchRow = scene.slice(searchStart, scene.indexOf('{scope === "objects"', searchStart));
  assert.match(searchRow, /slicerExpandSettingsAction/);
  assert.match(searchRow, /Expand settings/);
  assert.match(scene, /spec\.enabled_when/);
  assert.match(scene, /editingOverrides\[condition\.key\]/);
  assert.match(css, /\.slicerSettingsSearchRow \.slicerExpandSettingsAction/);
});


test("native conditional editor distinguishes Simple Advanced and Expert settings", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  assert.match(scene, /<option value="basic">Simple<\/option>/);
  assert.match(scene, /<option value="advanced">Advanced<\/option>/);
  assert.match(scene, /<option value="expert">Expert<\/option>/);
  assert.match(scene, /settingsLevel === "expert"/);
  assert.match(scene, /Array\.isArray\(spec\.enabled_when\)/);
  assert.match(scene, /condition\.in\.includes\(value\)/);
  assert.match(scene, /conditions\.every\(/);
  assert.match(scene, /"Tree support"/);
  assert.match(scene, /"Prime tower"/);
});


test("official and fallback build plates avoid coplanar shimmer and repeating textures", () => {
  const plate = read("SlicerPlateEditor.jsx");
  assert.match(plate, /const canvas = bedTexture\.image/);
  assert.match(plate, /context\.drawImage\(artworkImage, 0, 0, canvas\.width, canvas\.height\)/);
  assert.match(plate, /bedTexture\.needsUpdate = true/);
  assert.doesNotMatch(plate, /bedArtwork = new THREE\.Mesh/);
  assert.doesNotMatch(plate, /makeRepresentativePlateTexture/);
  assert.match(plate, /Math\.max\(2, Math\.min\(bedX, bedY\) \* 0\.015\)/);
});


test("loaded live filaments follow the model tree in the left rail", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const left = scene.indexOf('className="slicerPrepareLeftRail"');
  const tree = scene.indexOf('className="slicerPrepareTree"', left);
  const live = scene.indexOf('className="slicerLiveMaterialSlots"', tree);
  const closeLeft = scene.indexOf('className="slicerPrepareScene"', left);
  assert.ok(left >= 0 && tree > left && live > tree && closeLeft > live);
  const settings = scene.indexOf('const settingsPanel =');
  const settingsEnd = scene.indexOf('return <section className="panel printingSection', settings);
  assert.ok(settings >= 0 && settingsEnd > settings);
  assert.doesNotMatch(scene.slice(settings, settingsEnd), /className="slicerLiveMaterialSlots"/);
  assert.match(scene, /liveMaterials\.map\(slot => \{/);
  assert.match(scene, /className="slicerLiveMaterialSlot slicerLiveMaterialSlotCompact"/);
  assert.match(scene, /setEditingSlotProfile\(String\(slot.id\)\)/);
  assert.match(scene, /onClick=\{refreshPrinterMaterials\}/);
});

test("print settings can reach build-plate bottom before scrolling, with equal-height expand action", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(scene, /new ResizeObserver\(updateHeight\)/);
  assert.match(scene, /observer\.observe\(scene\)/);
  assert.match(scene, /maxHeight: sceneHeight \+ "px"/);
  assert.match(css, /\.slicerPrepareStructure > \.slicerPrepareSettings\{/);
  assert.match(css, /\.slicerPrepareSettings \.slicerSettingsLevelLabel select,\s*\.slicerPrepareSettings \.slicerSettingsSearchRow \.slicerExpandSettingsAction\{/);
  assert.match(css, /height:38px;\s*min-height:38px;/);
  assert.match(css, /\.slicerSettingsModal \.slicerPrepareSettings\{/);
});


test("first slicer navigation is queued while engine status is checking", () => {
  const app = fs.readFileSync(path.resolve(root, "../App.jsx"), "utf8");
  const printing = read("PrintingPage.jsx");
  assert.match(app, /pendingSlicerNavigation/);
  assert.match(app, /if \(next === "MakerVault Slicer" && slicerStatus\.state === "checking"\)/);
  assert.match(app, /setPendingSlicerNavigation\(true\)/);
  assert.match(app, /if \(!pendingSlicerNavigation \|\| slicerStatus\.state === "checking"\) return/);
  assert.match(app, /setSection\("MakerVault Slicer"\)/);
  assert.match(app, /"ready", "preview", "checking"/);
  assert.match(app, /preloadSlicerWorkbench\(\)/);
  assert.match(printing, /export function preloadSlicerWorkbench\(\)/);
});


test("confirmed completed slice actions return to slicer without hiding uncertain submissions", () => {
  const workbench = read("SlicerWorkbench.jsx");
  const printer = read("PrinterStartGcodeModal.jsx");
  const saved = workbench.slice(workbench.indexOf("async function saveOutputToLibrary"),
    workbench.indexOf("async function startSlice"));
  assert.match(saved, /await apiFetch\(/);
  assert.match(saved, /setPreviewJobId\(null\)/);
  assert.match(saved, /setShowDrafts\(false\)/);
  assert.match(workbench, /onSubmissionConfirmed=\{receipt =>/);
  assert.match(workbench, /setPrintSelection\(null\)/);
  assert.match(printer, /isConfirmedSubmission\(result\.submission, operation\)/);
  assert.match(printer, /onSubmissionConfirmed\?\.\(updated\)/);
  assert.match(printer, /submission\?\.status !== "started"/);
  assert.match(printer, /submittedAction === "upload"/);
  assert.match(printer, /submission\?\.status === "uploaded"/);
});


test("slicer Device action opens selected physical printer live monitoring", () => {
  const app = fs.readFileSync(path.resolve(root, "../App.jsx"), "utf8");
  const printing = read("PrintingPage.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  const prepare = read("SlicerPrepareWorkspace.jsx");
  assert.match(prepare, /onClick=\{\(\) => onOpenDevice\?\.\(printerId\)\}/);
  assert.match(prepare, /disabled=\{!printerId \|\| !onOpenDevice\}/);
  assert.match(prepare, />\s*Device\s*<\/button>/);
  assert.match(workbench, /onOpenDevice=\{onOpenDevice\}/);
  assert.match(printing, /onOpenDevice=\{onOpenSlicerDevice\}/);
  assert.match(app, /onOpenSlicerDevice=\{printerId =>/);
  assert.match(app, /type: "printers", id: String\(printerId\), openLive: true/);
  assert.match(printing, /printerIntent\(searchTarget, data\?\.printers, openedLiveTarget\)/);
});

test("live monitoring modal uses the shared camera preview before telemetry", () => {
  const printing = read("PrintingPage.jsx");
  const modalStart = printing.indexOf('title={(addOnly ? "Add live source · " : "Live monitoring · ") + printer.name}');
  const cameraAt = printing.indexOf("<PrinterCameraPreview", modalStart);
  const telemetryAt = printing.indexOf('className="printingIntegrationGrid printerLiveSources"', modalStart);
  assert.ok(modalStart > 0 && cameraAt > modalStart && telemetryAt > cameraAt);
  assert.match(printing.slice(cameraAt, telemetryAt), /live_connections: \(data\.rows \|\| \[\]\)/);
  assert.match(printing, /suspended=\{Boolean\(cameraSetup \|\| livePrinter \|\| cameraOffer \|\| addSourcePrinter\)\}/);
});

test("per-object settings inherit global profile values and remain instance scoped", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(scene, /const selectedObject = objects\.find\(row => row\.instance_id === selectedId\)/);
  assert.match(scene, /editingObject \? objectOverrides : processOverrides/);
  assert.match(scene, /onChange\(next\)/);
  assert.match(scene, /item\.instance_id !== selectedObject\.instance_id/);
  assert.match(scene, /inheritedValue\(key, spec\)/);
  assert.match(scene, /Clear object overrides/);
  assert.match(scene, /id="slicer-object-settings-instance"/);
  assert.match(workbench, /plate_objects: plateObjects/);
});

test("Auto-orient goals are in a toolbar menu and comparison is modal with a non-destructive ghost", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(scene, /slicerAutoOrientMenuChoice/);
  assert.match(scene, /\["balanced", "Balanced"/);
  assert.match(scene, /\["supports", "Fewest supports"/);
  assert.match(scene, /\["speed", "Fastest print"/);
  assert.match(scene, /autoOrientGoal=\{autoOrientGoal\} autoOrientRequest=\{autoOrientRequest\}/);
  assert.match(editor, /createPortal\(/);
  assert.match(editor, /aria-label="Compare model orientations"/);
  assert.match(editor, /userData\.isOrientationPreview = true/);
  assert.match(editor, /positionOrientedMesh\(ghost, \{ \.\.\.chosen, \.\.\.candidate\.orientation \}\)/);
  assert.match(editor, /state\.scene\.remove\(ghost\)/);
  assert.match(editor, /onClick=\{applyAutoOrientation\}/);
  assert.match(css, /\.slicerAutoOrientModalBackdrop/);
});

test("auto-orient comparison labels good and bad deltas rather than treating plus as positive", () => {
  const editor = read("SlicerPlateEditor.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(editor, /percent === null \? "isNeutral" : tied \? "isBetter" : "isWorse"/);
  assert.match(editor, /"✓ Best \/ tied"/);
  assert.match(editor, /"% worse"/);
  assert.match(editor, /orientationComparison\(relative\.time\)/);
  assert.match(css, /\.slicerOrientDelta\.isBetter/);
  assert.match(css, /\.slicerOrientDelta\.isWorse/);
  assert.match(css, /\.slicerOrientDelta\.isNeutral/);
});

test("Split toolbar invokes bounded component preview and atomic private STL replacement", () => {
  const workspace = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(workspace, /name: "Split", target: "split", icon: "split"/);
  assert.match(workspace, /splitRequest=\{splitRequest\}/);
  assert.match(editor, /splitDisconnectedMesh\(mesh, MAX_OBJECTS - objects\.length \+ 1\)/);
  assert.match(editor, /aria-label="Split disconnected objects"/);
  assert.match(editor, /userData\.splitPreview = true/);
  assert.match(editor, /if \(packed\.error\)/);
  assert.match(editor, /\/api\/printing\/slicer\/meshes\/temporary\//);
  assert.match(editor, /onChange\(next\)/);
  assert.match(editor, /setSplitPreview\(null\)/);
});


test("multi-select assembles without merging STL assets and provides guarded group transforms", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(scene, /setSelectedIds\(current =>/);
  assert.match(scene, /event\.ctrlKey \|\| event\.metaKey \|\| event\.shiftKey/);
  assert.match(scene, /Assemble selection/);
  assert.match(scene, /Disassemble/);
  assert.match(scene, /assembly_id: id/);
  assert.match(scene, /assembly_id: null/);
  assert.match(editor, /function transformGroup\(/);
  assert.match(editor, /Group transform would leave the build plate/);
  assert.match(editor, /onChange\(objects\.map\(row => byId\.get\(row\.instance_id\) \|\| row\)\)/);
  assert.match(editor, /aria-label="Multi-model assembly controls"/);
});
test("Move and Rotate have matching on-plate controls and all three rotate gizmo axes", () => {
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(editor, /state\.transform\.showX = true/);
  assert.match(editor, /state\.transform\.showY = true/);
  assert.match(editor, /rotation_xyz_deg: \[mesh\.rotation\.x, mesh\.rotation\.y\]/);
  assert.match(editor, /"On-plate position controls"/);
  assert.match(editor, /"On-plate rotation controls"/);
  assert.match(editor, /Reset rotation/);
});

test("Move Rotate and Scale share compact on-plate panels with validated resets", () => {
  const editor = read("SlicerPlateEditor.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(editor, /"On-plate scale controls"/);
  assert.match(editor, /"Scale · %"/);
  assert.match(editor, /Uniform scale \(%\)/);
  assert.match(editor, /Reset scale/);
  assert.match(editor, /Centre model/);
  assert.match(editor, /className="slicerTransformQuickAction"/);
  assert.match(css, /\.slicerPlateCanvasColumn \.slicerViewportMeasurement\.slicerViewportTransform/);
  assert.match(css, /justify-content: flex-start/);
  assert.match(css, /\.slicerViewportTransform \.slicerTransformQuickAction/);
});
test("Rotate gizmo uses 45 degree default detents with Shift precision and a live drag angle", () => {
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(editor, /transform\.setRotationSnap\(THREE\.MathUtils\.degToRad\(45\)\)/);
  assert.match(editor, /event\.shiftKey \? 5 : 45/);
  assert.match(editor, /transform\.addEventListener\("objectChange"/);
  assert.match(editor, /setLiveRotation\(\{ x:/);
  assert.match(editor, /slicerTransformDragAngle/);
});


test("MakerVault angle gizmo replaces default rotation rings with interactive axis grips", () => {
  const editor = read("SlicerPlateEditor.jsx");
  const gizmo = read("slicerRotationGizmo.js");
  assert.match(editor, /createMakerVaultRotationGizmo\(scene\)/);
  assert.match(editor, /rotationGizmo\.pick\(raycaster\.ray\)/);
  assert.match(editor, /rotationGizmo\.drag\(raycaster\.ray, event\.shiftKey, event\.timeStamp\)/);
  assert.match(editor, /state\.rotationGizmo\?\.update\(selectedMesh\)/);
  assert.match(editor, /setLiveRotation\(angle\)/);
  assert.match(editor, /type: "pointercancel"/);
  assert.match(editor, /positionOrientedMesh\(mesh, original\)/);
  assert.match(gizmo, /MakerVaultRotationGrip-/);
  assert.match(gizmo, /degree % 45 === 0/);
  assert.match(gizmo, /angleBadge\.visible = true/);
  assert.match(gizmo, /activeArc = new THREE\.Line\(/);
});

test("expanded Move, Rotate and Scale panels import the shared icon component", () => {
  const editor = read("SlicerPlateEditor.jsx");
  const icons = read("SlicerUiIcon.jsx");
  assert.match(editor, /import SlicerUiIcon from "\.\/SlicerUiIcon"/);
  assert.match(editor, /<SlicerUiIcon name="center"/);
  assert.match(editor, /<SlicerUiIcon name="rotate"/);
  assert.match(editor, /<SlicerUiIcon name="scale"/);
  for (const name of ["center", "rotate", "scale"])
    assert.match(icons, new RegExp(name + ":"));
});


test("top slicer header provides a matching direct interactive entry on mobile and desktop", () => {
  const workbench = read("SlicerWorkbench.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  const start = workbench.indexOf('className="printingHeroActions slicerHeroActions"');
  const end = workbench.indexOf("</section>", start);
  assert.ok(start > 0 && end > start);
  const header = workbench.slice(start, end);
  assert.match(header, /Printing overview/);
  assert.match(header, /Saved drafts/);
  assert.match(header, /Open interactive slicer/);
  assert.ok(header.indexOf("Saved drafts") < header.indexOf("Open interactive slicer"));
  assert.match(header, /className="primary slicerHeroInteractive"/);
  assert.match(header, /setEditorOpen\(true\)/);
  assert.match(header, /disabled=\{!canPrepare \|\| busy \|\| loading\}/);
  assert.match(header, /!editorOpen && <button/);
  assert.match(css, /\.slicerHeroInteractive \{/);
  assert.match(css, /grid-column: 1 \/ -1/);
  assert.match(css, /@media \(max-width: 900px\)/);
});


test("Move controls expose just model-centre XYZ and reject unsupported Z placement", () => {
  const plate = read("SlicerPlateEditor.jsx");
  assert.match(plate, /import \{ validateStackPlacement \} from "\.\/slicerStacking"/);
  assert.match(plate, /state\.transform\.showZ = toolMode === "move" \|\| toolMode === "scale"/);
  assert.match(plate, /mesh\.position\.z = mesh\.userData\.bedZOffset \+ Number\(item\.z_mm \|\| 0\)/);
  assert.match(plate, /patch\("z_mm", pretty\(number - \(selectedMeasurement\?\.height \|\| 0\) \/ 2\)\)/);
  assert.match(plate, /z_mm: Math\.max\(0, pretty\(mesh\.position\.z/);
  assert.match(plate, /Move rejected: model is unsupported/);
  const header = plate.indexOf('aria-label={toolMode === "move"');
  const move = plate.slice(header, plate.indexOf('toolMode === "rotate" ? <>', header));
  assert.match(move, /\["X", "Y", "Z"\]/);
  assert.doesNotMatch(move, /Coordinates are measured from/);
  assert.doesNotMatch(move, /X bounds:/);
  assert.doesNotMatch(move, /Z \(bed\): 0 mm/);
});

test("conflicting transforms remain editable, highlight affected meshes and block slicing", () => {
  const editor = read("SlicerPlateEditor.jsx");
  const scene = read("SlicerPrepareWorkspace.jsx");
  const workbench = read("SlicerWorkbench.jsx");
  assert.match(editor, /conflictIds\.has\(item\.instance_id\)/);
  assert.match(editor, /onPlateIssuesChange\?\.\(\{ signature: issueSignature, issues: plateIssues \}\)/);
  assert.match(editor, /bedX, bedY, true\)/);
  assert.match(scene, /conflictsBlockSlice/);
  assert.match(scene, /onPlateIssuesChange=\{onPlateIssuesChange\}/);
  assert.match(workbench, /unresolvedPlateIssues/);
  assert.match(workbench, /if \(sliceNow && mode!=="all" && unresolvedPlateIssues\)/);
  assert.match(workbench, /onPlateIssuesChange=\{setPlateValidation\}/);
});
test("duplicate individual XYZ scale toolbar action is removed", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  assert.doesNotMatch(scene, /name: "Individual XYZ scale"/);
  assert.match(scene, /name: "Scale", target: "scale_percent"/);
});


test("model toolbar renders immediately above the interactive build plate, not in page header", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const plate = read("SlicerPlateEditor.jsx");
  const styles = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(scene, /const modelToolbar = \(/);
  assert.match(scene, /<SlicerPlateEditor key=\{activePlateId\} plateIndex=/);
  assert.match(scene, /toolbar=\{modelToolbar\}/);
  const header = scene.slice(scene.indexOf('className="slicerPrepareHeader"'),
    scene.indexOf('className="slicerMobilePaneTabs"'));
  assert.doesNotMatch(header, /className="slicerPrepareTools"/);
  assert.match(plate, /\{toolbar && <AdaptiveEditingToolbar toolbar=\{toolbar\} \/>\}/);
  const index = plate.indexOf('className={"slicerPlateEditingToolbar"');
  assert.ok(index > 0);
  assert.ok(index < plate.indexOf('className="slicerPlateCameraToolbar"', index));
  assert.doesNotMatch(plate, /Arrange models, change their size and position, and preview the build plate/);
  assert.match(styles, /\.slicerPlateEditingToolbar > \.slicerPrepareTools/);
  assert.match(styles, /overflow-x: auto/);
});


test("Add model toolbar offers upload picker and scroll to MakerVault library", () => {
  const workspace = read("SlicerPrepareWorkspace.jsx");
  const plate = read("SlicerPlateEditor.jsx");
  const css = fs.readFileSync(path.resolve(root, "../styles.css"), "utf8");
  assert.match(workspace, /const \[addModelMenuOpen, setAddModelMenuOpen\] = useState\(false\)/);
  assert.match(workspace, /slicer-add-model-toolbar-options/);
  assert.match(workspace, /Upload from device/);
  assert.match(workspace, /Add from MakerVault/);
  assert.match(workspace, /input\[type="file"\]\[accept="\.stl,\.3mf"\]/);
  assert.match(workspace, /\[data-slicer-add-models\]/);
  assert.match(workspace, /scrollIntoView\(/);
  assert.match(plate, /data-slicer-add-models/);
  assert.match(css, /\.slicerAddModelChoice/);
});


test("all existing and new tool descriptions remain inside toolbar border", () => {
  const workspace=read("SlicerPrepareWorkspace.jsx");
  const styles=fs.readFileSync(path.resolve(root,"../styles.css"),"utf8");
  assert.match(workspace,/className="slicerToolbarDescriptor"/);
  assert.match(workspace,/onMouseEnter=\{\(\) => setToolDescriptor/);
  assert.match(workspace,/onFocus=\{\(\) => setToolDescriptor/);
  assert.match(styles,/\.slicerPlateEditingToolbar \.slicerToolTooltip::after/);
  assert.match(styles,/content: none !important/);
  assert.match(styles,/\.slicerPlateEditingToolbar \.slicerToolbarDescriptor/);
  assert.match(styles,/flex: 1 0 100%/);
});
test("Hollow, Drill, Cut and Mesh boolean share one preview-and-confirm model editor", () => {
  const workspace=read("SlicerPrepareWorkspace.jsx");
  const editor=read("SlicerPlateEditor.jsx");
  for (const kind of ["hollow","drill","cut","boolean"])
    assert.match(workspace,new RegExp('target: "'+kind+'"'));
  assert.match(workspace,/solidRequest=\{solidRequest\}/);
  assert.match(editor,/executeSolidOperation\(solidDialog\.kind,target,\{\.\.\.solidOptions,allowOpenPreview:true\},second\)/);
  assert.match(editor,/aria-label=\{solidDialog\.kind\+" model geometry"\}/);
  assert.match(editor,/Preview updates automatically/);
  assert.match(editor,/Apply mesh edit/);
  assert.match(editor,/setSolidPreview\(null\);setSolidDialog\(null\)/);
  assert.match(editor,/meshes\/temporary\//);
});


test("assembly toolbar gizmos use a shared pivot and keep meshes independent",()=>{
  const scene=read("SlicerPlateEditor.jsx");
  const workspace=read("SlicerPrepareWorkspace.jsx");
  assert.match(scene,/groupProxy=new THREE\.Object3D\(\)/);
  assert.match(scene,/state\.transform\.attach\(pivot\)/);
  assert.match(scene,/groupCommitRef\.current\?\.\(dx,dy,rotation,scale\)/);
  assert.match(scene,/groupEditable = canEdit && !solidDialog && selection\.length > 1/);
  assert.match(scene,/state\.setSelectionOutlines\(toolMode === "paint_colour" \? \[\] : selection\.map/);
  assert.match(scene,/transformGroup\(groupDeltaX, groupDeltaY, groupRotation, groupScale\)/);
  assert.match(workspace,/const memberIds = item\.assembly_id/);
  assert.match(workspace,/memberIds\.every\(value => current\.includes\(value\)\)/);
});
test("negative volume warns if the subtraction shape misses the model",()=>{
  const editor=read("SlicerPlateEditor.jsx");
  assert.match(editor,/if \(!targetBounds\.intersectsBox\(toolBounds\)\)/);
  assert.match(editor,/Negative shape does not intersect the selected model/);
});

test("project plates can be added and switched without sharing selection history",()=>{
  const scene=read("SlicerPrepareWorkspace.jsx");
  assert.match(scene,/className="slicerPlateProjectNav"/);
  assert.match(scene,/plates\.map\(\(item,index\)=>/);
  assert.match(scene,/onChoosePlate\?\.\(item\.id\)/);
  assert.match(scene,/onAddPlate\?\.\(\)/);
  assert.match(scene,/onRemovePlate\?\.\(activePlateId\)/);
  assert.match(scene,/undoRef\.current=\[\];redoRef\.current=\[\]/);
  assert.match(scene,/key=\{activePlateId\}/);
});

test("toolbar groups related tools and shows distinct plate and geometry icons",()=>{
  const scene=read("SlicerPrepareWorkspace.jsx");
  const icons=read("SlicerUiIcon.jsx");
  for(const group of ["create","transform","arrange","geometry","inspect","paint"])
    assert.match(scene,new RegExp('group: "'+group+'"'));
  assert.match(scene,/slicerToolGroupStart/);
  assert.match(scene,/name: "Add plate", target: "add_plate", icon: "add-plate"/);
  assert.match(icons,/"add-plate":/);
  assert.match(icons,/"plates-overview":/);
});
test("all-plates overview preserves per-plate placement and returns to selected plate",()=>{
  const scene=read("SlicerPrepareWorkspace.jsx");
  assert.match(scene,/const \[showAllPlates,setShowAllPlates\]/);
  assert.match(scene,/aria-label="All build plates overview"/);
  assert.match(scene,/entry\.objects\.map\(\(item,itemIndex\)=>/);
  assert.match(scene,/Number\(item\.x_mm\|\|0\)/);
  assert.match(scene,/Number\(item\.y_mm\|\|0\)/);
  assert.match(scene,/setShowAllPlates\(false\);onChoosePlate\?\.\(entry\.id\)/);
});
test("assembly detach only selected parts and keeps remaining groups",()=>{
  const scene=read("SlicerPrepareWorkspace.jsx");
  assert.match(scene,/function removeSelectedFromAssembly\(\)/);
  assert.match(scene,/ids\.has\(row\.instance_id\)/);
  assert.match(scene,/counts\.get\(row\.assembly_id\)<2/);
  assert.match(scene,/Remove selected from assembly/);
});
test("inspector top uses measured camera row instead of a fixed viewport offset",()=>{
  const editor=read("SlicerPlateEditor.jsx");
  assert.match(editor,/camera\.getBoundingClientRect\(\)\.top/);
  assert.match(editor,/viewport\.style\.setProperty\("--slicer-overlay-top"/);
});
