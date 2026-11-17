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

test("review layout keeps temperatures, detail table and source reader responsive", () => {
  const source = read("../src/components/GcodeFullSource.jsx");
  assert.match(preview, /Requested chamber/);
  assert.match(viewer, /Chamber /);
  assert.ok(viewer.includes("<strong>Build plate</strong>"));
  assert.match(viewer, /slicerGenerator/);
  assert.match(viewer, /slicerGcodeSavedSettingsScroll/);
  assert.match(viewer, /slicerGcodeSourceModeActions/);
  assert.match(source, /slicerFullSourceSearch/);
  assert.match(source, /slicerFullSourcePagination/);
  assert.doesNotMatch(source, /Jump to object/);
  assert.doesNotMatch(source, /Per-object toolpath evidence/);
  assert.doesNotMatch(preview, /Show entire selected layer/);
  assert.doesNotMatch(preview, /slicerPreviewCoverage/);
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

test("download uses ordinary buttons and settings labels cannot vertically stretch", () => {
  const reader=read("../src/components/GcodeFullSource.jsx");
  const styles=read("../src/styles.css");
  assert.match(workbench, /className="buttonLink slicerGcodeDownloadAction"/);
  assert.match(viewer, /className="buttonLink slicerGcodeDownloadAction"/);
  assert.match(reader, /className="buttonLink slicerGcodeDownloadAction"/);
  assert.ok(mobileCss.includes(".slicerResultModeRow.slicerPreviewOptionsPanel.mobileOpen > label {"));
  assert.match(mobileCss, /flex:0 0 auto!important/);
  assert.ok(styles.includes(".slicerHeroProjectNavigation > .slicerHeroBack"));
  assert.match(styles, /height: 43px/);
});

test("desktop review keeps preview visible and collapses secondary controls", () => {
  assert.match(viewer, /slicerPreviewNav/);
  assert.match(viewer, /slicerGcodeMetadata/);
  assert.match(viewer, /setMobileDetails\(true\)/);
  assert.match(preview, /toolbarActions=\{<>/);
  assert.match(viewport, /slicerUnifiedViewActions/);
  assert.match(preview, /slicerPreviewOptionsPanel/);
  assert.match(mobileCss, /\.slicerPreviewOptionsPanel:not\(\.mobileOpen\)/);
  assert.match(mobileCss, /\.slicerGcodeCompactLayout \.slicerGcodeDesktopActions/);
  assert.match(mobileCss, /@media \(min-width: 701px\)/);
  assert.match(mobileCss, /\.slicerMobileActionContents\.mobileOpen/);
  assert.match(viewer, /Material and layer totals/);
});

test("mobile action row, slider and settings dialog remain compact", () => {
  assert.match(viewport, /slicerUnifiedViewActions/);
  assert.match(preview, /toolbarActions=\{<>/);
  assert.doesNotMatch(preview, /Previous sampled toolhead step/);
  assert.doesNotMatch(preview, /Next sampled toolhead step/);
  assert.match(mobileCss, /\.slicerUnifiedViewActions/);
  assert.match(mobileCss, /flex-direction: column !important/);
  assert.match(mobileCss, /\.slicerResultSteps input\.slicerFullRange::-webkit-slider-runnable-track/);
  assert.match(mobileCss, /\.slicerResultLayerSlider input\.slicerFullRange::-webkit-slider-runnable-track/);
});

test("iOS ranges preserve endpoint travel while aligning thumb centres", () => {
  assert.match(mobileCss, /\.slicerResultSteps input\.slicerFullRange::-webkit-slider-thumb\s*\{\s*transform: translateY\(-11px\)/);
  assert.match(mobileCss, /\.slicerResultLayerSlider input\.slicerFullRange::-webkit-slider-thumb\s*\{\s*transform: translateX\(-11px\)/);
  assert.match(mobileCss, /\.slicerResultLayerLayout \{\s*align-items: stretch/);
  assert.match(mobileCss, /\.slicerResultLayerLayout > \.slicerResultLayerSlider \{\s*align-self: stretch;\s*height: auto/);
  assert.doesNotMatch(mobileCss, /height: calc\(clamp\(290px, 43dvh, 450px\) \+ 150px\)/);
  assert.match(preview, /id="slice-step-slider"/);
  assert.match(preview, /id="slice-layer-slider"/);
});
