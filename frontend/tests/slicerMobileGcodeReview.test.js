import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = file => readFileSync(new URL(file, import.meta.url), "utf8");
const preview = read("../src/components/SlicerGcodePreview.jsx");
const viewer = read("../src/components/GcodeViewerModal.jsx");
const viewport = read("../src/components/SlicerToolpath3D.jsx");
const workbench = read("../src/components/SlicerWorkbench.jsx");
const mobileCss = read("../src/components/slicerPreviewMobile.css");

test("mobile preview retains the toolpath, temperatures and primary figures", () => {
  assert.match(preview, /<SlicerToolpath3D segments=/);
  assert.match(preview, /Estimated print time/);
  assert.match(preview, /Requested nozzle/);
  assert.match(preview, /Requested bed/);
  assert.match(viewer, /slicerGcodeQuickSummary/);
  assert.match(mobileCss, /\.slicerGcodeQuickSummary/);
  assert.match(mobileCss, /\.slicerResultLayerLayout/);
});

test("mobile detail and settings panels have explicit close controls", () => {
  assert.match(viewer, /setMobileDetails\(false\)/);
  assert.match(viewer, /G-code details/);
  assert.match(preview, /setMobilePanel\(null\)/);
  assert.match(preview, /Display settings/);
  assert.match(preview, /Visible toolpaths/);
  assert.match(viewport, /View options/);
  assert.match(viewport, /setMobileViewOpen/);
  assert.match(preview, /Visible toolpaths/);
  assert.match(preview, /className="slicerResultSteps"/);
  assert.doesNotMatch(preview, /Inspect individual moves/);
});

test("upload and start retain existing conditions behind a mobile action toggle", () => {
  assert.match(workbench, /mobileActionsOpen/);
  assert.match(workbench, /File &amp; printer actions/);
  assert.match(workbench, /canPrint && previewJob\.settings\?\.workflow !== "quick"/);
  assert.match(workbench, /requestPrint\(previewJob, "print"\)/);
  assert.match(workbench, /saveOutputToLibrary\(previewJob\)/);
  assert.match(workbench, /Download G-code/);
  assert.match(mobileCss, /\.slicerMobileActionContents\.mobileOpen/);
});

test("desktop retains controls without verbose instruction paragraphs", () => {
  assert.doesNotMatch(preview, /Print time comes from the generated G-code/);
  assert.doesNotMatch(preview, /To compare fuzzy skin, enable/);
  assert.doesNotMatch(viewport, /Drag to orbit · Scroll to zoom/);
  assert.match(mobileCss, /@media \(max-width: 700px\)/);
});

test("download button is consistent in file actions and desktop viewer", () => {
  assert.match(workbench, /slicerGcodeDownloadAction/);
  assert.match(viewer, /slicerGcodeDownloadAction/);
  assert.match(mobileCss, /\.slicerGcodeDownloadAction/);
});

test("desktop review keeps preview visible and collapses secondary controls", () => {
  assert.match(viewer, /slicerPreviewNav/);
  assert.match(viewer, /slicerGcodeMetadata/);
  assert.match(viewer, /setMobileDetails\(true\)/);
  assert.match(preview, /slicerPreviewToolButtons/);
  assert.match(preview, /slicerPreviewOptionsPanel/);
  assert.match(mobileCss, /\.slicerPreviewOptionsPanel:not\(\.mobileOpen\)/);
  assert.match(mobileCss, /\.slicerGcodeCompactLayout \.slicerGcodeDesktopActions/);
  assert.match(mobileCss, /@media \(min-width: 701px\)/);
  assert.match(mobileCss, /\.slicerMobileActionContents\.mobileOpen/);
  assert.match(viewer, /Material and layer totals/);
});
