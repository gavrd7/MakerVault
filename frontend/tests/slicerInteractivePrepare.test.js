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
  assert.match(scene, /onSelectedInstanceChange=\{setSelectedId\}/);
  for (const tool of ["Move", "Rotate", "Scale", "Auto-arrange", "Duplicate"]) {
    assert.match(scene, new RegExp('name: "' + tool + '"'));
  }
  assert.match(plate, /data-slicer-action="arrange"/);
  assert.match(plate, /data-slicer-action="duplicate"/);
  assert.match(plate, /data-slicer-field="x_mm"/);
});

test("advanced tools are visibly gated pending safe native transformations", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  for (const tool of ["Auto-orient", "Lay on face", "Cut", "Hollow",
                       "Support painting", "Seam painting", "Variable layer height",
                       "Colour painting", "Add plate"]) {
    assert.match(scene, new RegExp('name: "' + tool + '", icon: "[^"]+", pending:'));
  }
  assert.match(scene, /disabled=\{!!tool.pending/);
  for (const group of ["Quality", "Strength", "Speed", "Supports", "Multifilament", "Others"])
    assert.match(scene, new RegExp('"' + group + '"'));
  assert.match(scene, /Per-object settings are not yet available/);
  assert.match(scene, /nativeProcessFields/);
  assert.match(scene, /processOverrides/);
  assert.match(scene, /Restore profile defaults/);
});

test("independent XYZ scaling updates visual mesh and is selectable from the toolbar", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  const editor = read("SlicerPlateEditor.jsx");
  assert.match(scene, /name: "Individual XYZ scale", target: "scale_xyz_percent"/);
  assert.match(editor, /Independent axis scaling \(%\)/);
  assert.match(editor, /data-slicer-field=\{index === 0 \? "scale_xyz_percent"/);
  assert.match(editor, /mesh\.scale\.set\(xyz\[0\] \/ 100, xyz\[1\] \/ 100, xyz\[2\] \/ 100\)/);
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

test("live CFS AMS RFID material slots remain read-only until real multi-material slicing", () => {
  const scene = read("SlicerPrepareWorkspace.jsx");
  assert.match(scene, /apiFetch\("\/api\/printing\/\?include_filaments=0"\)/);
  assert.match(scene, /\.filter\(slot => slot\.is_loaded\)/);
  assert.match(scene, /slot\.spool_code/);
  assert.match(scene, /native multi-material mapping is implemented/);
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
  assert.match(scene, /processOverrides\[condition\.key\]/);
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
  assert.match(scene, /liveMaterials\.map\(slot => <div className="slicerLiveMaterialSlot"/);
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
