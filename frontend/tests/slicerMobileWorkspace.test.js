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
  assert.match(editor, /"plate", "Build plate"/);
  assert.match(editor, /"models", `Models \(\$\{objects\.length\}\)`/);
  assert.match(editor, /"settings", "Print settings"/);
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
