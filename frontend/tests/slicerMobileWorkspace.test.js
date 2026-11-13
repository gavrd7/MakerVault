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
  assert.match(viewer, /<option value="all">All earlier layers/);
  assert.match(viewer, /Earlier layers are still a sampled orientation reference/);
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
  assert.match(css,/\.slicerPlateCanvasViewport>\.slicerColourPaintPanel\{/);
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
  assert.match(workspace,/onSlotFilamentProfilesChange\?\.\(updated\)/);
  assert.match(flushing,/aria-haspopup="dialog"/);
  assert.match(flushing,/createPortal\(/);
  assert.match(flushing,/className="slicerFlushModal"/);
  assert.match(flushing,/value=\{data.multiplier \?\? nativeMultiplier \?\? ""\}/);
  assert.match(flushing,/slicerFlushSlotLabel/);
  assert.match(flushing,/slicerFlushSwatch/);
});
