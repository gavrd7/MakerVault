import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const base = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const editor = fs.readFileSync(path.join(base, "components/SlicerPrepareWorkspace.jsx"), "utf8");
const viewer = fs.readFileSync(path.join(base, "components/SlicerGcodePreview.jsx"), "utf8");
const css = fs.readFileSync(path.join(base, "styles.css"), "utf8");

test("mobile slicer tabs expose plate, models, and settings without unmounting their state", () => {
  assert.match(editor, /const \[mobilePane, setMobilePane\] = useState\("plate"\)/);
  assert.match(editor, /role="tablist" aria-label="Mobile slicer workspace"/);
  assert.match(editor, /"plate", "Build"/);
  assert.match(editor, /"models", "Printer & Filament"/);
  assert.match(editor, /"settings", "Print Settings"/);
  assert.match(editor, /<SlicerUiIcon name=\{key === "models" \? "printer" : key\} size=\{18\}/);
  assert.match(editor, /slicerMobileTabLabel/);
  assert.match(editor, /aria-selected=\{mobilePane === key\}/);
  assert.match(editor, /data-mobile-pane=\{mobilePane\}/);
  assert.match(editor, /id="slicer-prepare-plate"/);
  assert.match(editor, /id="slicer-prepare-models"/);
  assert.match(editor, /id="slicer-prepare-settings"/);
  assert.match(css, /\.slicerMobilePaneTabs\{display:none\}/);
  assert.match(css, /@media\(max-width:850px\)/);
  assert.match(css, /data-mobile-pane="plate"/);
  assert.match(css, /data-mobile-pane="models"/);
  assert.match(css, /data-mobile-pane="settings"/);
  assert.match(css, /slicerMobilePaneTabs \.slicerUiIcon/);
  assert.match(css, /slicerMobileTabCount/);
});

test("default G-code view is full printed overview while layer-only inspection remains optional", () => {
  assert.match(viewer, /const \[layerDisplay, setLayerDisplay\] = useState\("all"\)/);
  assert.match(viewer, /<option value="current">Current layer only/);
  assert.match(viewer, /<option value="all">Whole print · full-detail paths/);
  assert.match(viewer, /The preview reached its resource budget/);
});

test("mobile G-code controls are compact without changing desktop layout", () => {
  assert.match(css, /@media\(max-width:650px\)/);
  assert.match(css, /\.slicerPreviewModal \.slicerResultModeRow\{/);
  assert.match(css, /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
});

test("mobile mesh geometry dialogs remain in the visual viewport with wrap-safe actions", () => {
  const editor = fs.readFileSync(path.join(base,"components/SlicerPlateEditor.jsx"),"utf8");
  assert.match(editor,/const width=Math.max\(0,Math.min\(440,screenW-16\)\)/);
  assert.match(editor,/Math.min\(rect.left\+6,screenW-width-8\)/);
  assert.match(css,/\.slicerSolidModal\.slicerViewportAnchoredModal \.slicerAutoOrientModalActions\{/);
  assert.match(css,/\.slicerSolidModal\.slicerViewportAnchoredModal \.slicerSolidGrid\{/);
  assert.match(css,/overflow-x:hidden;overflow-y:auto/);
});

test("painting controls adapt to a shallow, minimisable mobile strip", () => {
  const workspace = fs.readFileSync(path.join(base,"components/SlicerPrepareWorkspace.jsx"),"utf8");
  assert.match(workspace,/paintMobileMinimised/);
  assert.match(workspace,/className="slicerPaintMobileMinimise"/);
  assert.match(css,/\.slicerPrepareScene \.slicerPlateCanvasColumn>\.slicerColourPaintPanel\{/);
  assert.match(css,/max-height:min\(195px,32dvh\)!important/);
  assert.match(css,/\.slicerColourPaintPanel>div\[role="group"\]/);
  assert.match(css,/overflow-x:auto;overscroll-behavior-inline:contain/);
  assert.match(css,/\.slicerColourPaintPanel\.slicerPaintMinimised/);
});

test("touch navigation is not captured by ordinary model selection and pinch interrupts edit", () => {
  const editor=fs.readFileSync(path.join(base,"components/SlicerPlateEditor.jsx"),"utf8");
  assert.match(editor,/event\.pointerType === "touch" && latestToolModeRef\.current === "select"/);
  assert.match(editor,/const activeTouchPointers = new Set\(\)/);
  assert.match(editor,/activeTouchPointers\.size > 1/);
  assert.match(editor,/cancelTouchEdit\(\)/);
  assert.match(editor,/controls\.enabled=true/);
});

test("mobile geometry editing is short and can collapse without discarding the preview", () => {
  const editor=fs.readFileSync(path.join(base,"components/SlicerPlateEditor.jsx"),"utf8");
  assert.match(editor,/maxHeight:"min\(35dvh, 300px\)"/);
  assert.match(editor,/solidInspectorCollapsed/);
  assert.match(editor,/aria-expanded=\{!solidInspectorCollapsed\}/);
  assert.match(css,/\.slicerSolidModal\.slicerSolidInspectorCollapsed/);
});

test("mobile paint eraser stays outside scrolling filament palette", () => {
  const workspace=fs.readFileSync(path.join(base,"components/SlicerPrepareWorkspace.jsx"),"utf8");
  const palette=workspace.indexOf('aria-label="Paint filament palette"');
  const groupEnd=workspace.indexOf('</div>',palette);
  const erase=workspace.indexOf('aria-label="Erase painted faces"',palette);
  assert.ok(palette>=0&&groupEnd>palette&&erase>groupEnd);
  assert.match(css,/\.slicerColourPaintPanel \.slicerPaintEditActions/);
});

test("flushing settings and CFS profile controls use the new modal rather than a cramped inline matrix",()=>{
  const workspace=fs.readFileSync(path.join(base,"components/SlicerPrepareWorkspace.jsx"),"utf8");
  const flushing=fs.readFileSync(path.join(base,"components/SlicerFlushVolumes.jsx"),"utf8");
  assert.match(workspace,/processProfileId=\{selectedProfiles\?\.process_id\}/);
  assert.match(workspace,/className="slicerLiveMaterialSwatch slicerLiveMaterialSwatchRound"/);
  assert.match(workspace,/setEditingSlotProfile\(String\(slot.id\)\)/);
  assert.match(workspace,/onSlotFilamentProfilesChange\?\.\(current=>/);
  assert.match(flushing,/aria-haspopup="dialog"/);
  assert.match(flushing,/createPortal\(/);
  assert.match(flushing,/className="slicerFlushModal"/);
  assert.match(flushing,/value=\{data.multiplier \?\? effectiveMultiplier\}/);
  assert.match(flushing,/slicerFlushSlotLabel/);
  assert.match(flushing,/slicerFlushSwatch/);
});

test("compact filament rows and the flush spreadsheet keep actions readable",()=>{
  const workspace=fs.readFileSync(path.join(base,"components/SlicerPrepareWorkspace.jsx"),"utf8");
  const flushing=fs.readFileSync(path.join(base,"components/SlicerFlushVolumes.jsx"),"utf8");
  assert.match(workspace,/slicerLiveMaterialSlotCompact/);
  assert.match(workspace,/Loaded filament details/);
  assert.match(workspace,/slicerLiveMaterialActions/);
  assert.match(flushing,/slicerFlushMatrix/);
  assert.match(flushing,/slicerFlushCell/);
  assert.match(css,/\.slicerFlushMatrix \.slicerFlushCell/);
  assert.match(css,/\.slicerLiveMaterialSlotCompact \.slicerLiveMaterialActions/);
  assert.match(css,/grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
});

test("adding an existing MakerVault STL returns to the interactive plate",()=>{
  const editor=fs.readFileSync(path.join(base,"components/SlicerPlateEditor.jsx"),"utf8");
  assert.match(editor,/Add STL to plate<\/button>/);
  assert.match(editor,/event\.currentTarget\.closest\("#slicer-prepare-plate"\)/);
  assert.match(editor,/addAsset\(assetChoice\);\s*if\(platePanel\) requestAnimationFrame/);
  assert.match(editor,/platePanel\.scrollIntoView\(\{behavior:"smooth",block:"start"\}\)/);
  const workspace=fs.readFileSync(path.join(base,"components/SlicerPrepareWorkspace.jsx"),"utf8");
  assert.match(workspace,/data-slicer-add-models/);
  assert.match(workspace,/behavior: "smooth", block: "start"/);
});

test("editor-width adaptive toolbar never exceeds two rows and pages with arrows",()=>{
  const plate=fs.readFileSync(path.join(base,"components/SlicerPlateEditor.jsx"),"utf8");
  const workspace=fs.readFileSync(path.join(base,"components/SlicerPrepareWorkspace.jsx"),"utf8");
  assert.match(plate,/function AdaptiveEditingToolbar\(\{toolbar\}\)/);
  assert.match(plate,/new ResizeObserver\(update\)/);
  assert.match(plate,/getBoundingClientRect\(\)\.width<790/);
  assert.match(plate,/aria-label="Previous editing tools"/);
  assert.match(plate,/aria-label="Next editing tools"/);
  assert.match(plate,/disabled=\{!scrollState\.left\}/);
  assert.match(plate,/disabled=\{!scrollState\.right\}/);
  assert.match(plate,/scrollBy\(\{left:direction\*/);
  assert.match(plate,/<AdaptiveEditingToolbar toolbar=\{toolbar\} \/>/);
  assert.match(css,/\.slicerPlateEditingToolbar\.isCompact/);
  assert.match(css,/grid-template-rows:repeat\(2,60px\)/);
  assert.match(css,/grid-auto-flow:column/);
  assert.match(css,/overflow-x:auto/);
  assert.match(css,/\.slicerPrepareWorkspace \{\s*container-type:inline-size/);
  assert.match(css,/@container \(max-width:760px\)/);
  assert.match(workspace,/position:"fixed",left:Math\.max\(12/);
});

test("mobile section slider is horizontal below the canvas and plate uses wider gutters",()=>{
  assert.match(css,/\.slicerPrepareWorkspace \{padding:7px !important;\}/);
  assert.match(css,/\.slicerPrepareScene > \.slicerPlatePanel \{/);
  assert.match(css,/\.slicerPlateCanvasViewport > \.slicerPlateSectionControl \{/);
  assert.match(css,/position:relative !important;\s*order:2/);
  assert.match(css,/height:44px;\s*min-height:44px/);
  assert.match(css,/writing-mode:horizontal-tb/);
  assert.match(css,/\.slicerPlateCanvasColumn \.slicerPlateCanvasViewport > \.slicerPlateCanvas \{\s*order:1/);
});

test("mobile Slice button keeps its dropdown at 42px rather than stretching", () => {
  assert.match(css, /grid-template-columns:minmax\(0,1fr\) 42px/);
  assert.match(css, /\.slicerPrepareActions \.slicerSliceSplit > button:nth-child\(2\)/);
  assert.match(css, /width:42px;min-width:42px;max-width:42px/);
});

test("mobile mesh operations share a scrollable viewport-safe inspector", () => {
  const plate = fs.readFileSync(path.join(base,"components/SlicerPlateEditor.jsx"),"utf8");
  for (const type of ["hollow","drill","cut","boolean"]) {
    assert.match(plate, new RegExp('solidDialog.kind===\\"' + type + '\\"'));
  }
  assert.match(css, /\.slicerAutoOrientModalBackdrop > \.slicerSolidModal\.slicerViewportAnchoredModal/);
  assert.match(css, /max-height:min\(75dvh,680px\)!important/);
  assert.match(css, /overflow-y:auto!important;overflow-x:hidden!important/);
  assert.match(css, /slicerSolidInspectorCollapsed/);
});

test("settings categories are visible in both compact and expanded views", () => {
  assert.match(editor, /const \[settingsLevel, setSettingsLevel\] = useState\("advanced"\)/);
  for (const category of ["Quality", "Strength", "Speed", "Supports", "Multifilament", "Others"]) {
    assert.match(editor, new RegExp('\\["' + category + '",'));
  }
  assert.match(css, /slicerPrepareSettings nav\[aria-label="Process settings groups"\]/);
  assert.match(css, /slicerSettingsModal \.slicerPrepareSettings nav\[aria-label="Process settings groups"\]/);
});

test("painting toolbar uses complete action names", () => {
  for (const label of ["Support painting", "Seam painting", "Variable layer height"])
    assert.match(editor, new RegExp('name: "' + label + '"'));
});

test("mobile mesh tools dock inside the 3D viewport alongside Measure", () => {
  const plate = fs.readFileSync(path.join(base, "components/SlicerPlateEditor.jsx"), "utf8");
  const viewport = plate.indexOf('<div className="slicerPlateCanvasViewport"');
  const measure = plate.indexOf('aria-label="On-plate measurements"', viewport);
  const mount = plate.indexOf('className={"slicerMobileGeometryDock"', measure);
  const options = plate.indexOf('className="slicerPlateDisplayOptions"', mount);
  assert.ok(viewport >= 0 && measure > viewport && mount > measure && options > mount);
  assert.match(plate, /const meshInspectorHost = mobileMeshInspector \? mobileMeshDock : document\.body/);
  assert.match(plate, /solidDialog && meshInspectorHost && createPortal/);
  assert.match(plate, /splitPreview && meshInspectorHost && createPortal/);
  assert.match(css, /slicerPlateCanvasViewport > \.slicerMobileGeometryDock/);
  assert.match(css, /max-height:min\(46dvh, 320px\)!important/);
  assert.match(css, /slicerMobileGeometryDock \.slicerAutoOrientModalHeader h3/);
});

test("mobile settings selection is inset and model transform fields align vertically", () => {
  assert.match(css, /slicerPrepareSettings nav\[aria-label="Process settings groups"\]>button\.selected/);
  assert.match(css, /box-shadow:inset 0 0 0 1px #9b85ee/);
  assert.match(css, /\.slicerPrepareScene \.slicerPlateTransformFields>label/);
  assert.match(css, /grid-template-columns:minmax\(0,1fr\)!important/);
});

test("single-colour slicing explains which required native profile is absent", () => {
  assert.match(editor, /const missingNativeProfiles = \["printer", "process", "filament"\]\.filter/);
  assert.match(editor, /"Missing native " \+ missingNativeProfiles\.join\(", "\)/);
});

test("Move Rotate Scale and Measure share the same mobile viewport dock", () => {
  const plate = fs.readFileSync(path.join(base, "components/SlicerPlateEditor.jsx"), "utf8");
  assert.match(plate, /className="slicerViewportMeasurement slicerViewportTransform slicerViewportToolDock"/);
  assert.match(plate, /className="slicerViewportMeasurement slicerViewportToolDock" aria-label="On-plate measurements"/);
  assert.match(plate, /\["move", "rotate", "scale"\]\.includes\(toolMode\)/);
  assert.match(plate, /transformOverlayExpanded \? "Less" : "Details"/);
  assert.match(css, /\.slicerPlateCanvasColumn \.slicerPlateCanvasViewport > \.slicerViewportToolDock\.slicerViewportTransform/);
  assert.match(css, /max-height:min\(220px, 35dvh\)!important/);
  assert.match(css, /\.slicerPlateCanvasViewport > \.slicerViewportToolDock \.slicerViewportTransformGrid/);
});

test("mobile Add model picker escapes the horizontally scrolling toolbar", () => {
  const menu = editor.slice(editor.indexOf("const addModelMenu = ("), editor.indexOf("const modelToolbar = ("));
  assert.match(menu, /Upload from device/);
  assert.match(menu, /Add from MakerVault/);
  assert.match(menu, /Add primitive shape/);
  assert.match(menu, /Add text/);
  assert.match(menu, /Add SVG/);
  assert.match(menu, /Add negative volume/);
  assert.match(editor, /toolPopupStyle\?\.position === "fixed"\s*\? createPortal\(/);
  assert.match(editor, /className="slicerAddModelOverlay"/);
  assert.match(editor, /document\.body\s*\)\s*:\s*addModelMenu/);
  assert.match(css, /\.slicerAddModelOverlay\s*>\s*\.slicerAddModelMenu/);
  assert.match(css, /max-height:min\(85dvh,650px\)!important/);
  assert.match(css, /z-index:13000/);
});
