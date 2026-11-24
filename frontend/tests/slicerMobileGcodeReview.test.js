import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const viewport = read("../src/components/SlicerToolpath3D.jsx");
const preview = read("../src/components/SlicerGcodePreview.jsx");
const viewer = read("../src/components/GcodeViewerModal.jsx");
const workbench = read("../src/components/SlicerWorkbench.jsx");
const mobileCss = read("../src/components/slicerPreviewMobile.css");

test("K2 print modal refreshes CFS before checking mapped-print availability", () => {
  const modal = read("../src/components/PrinterStartGcodeModal.jsx");
  assert.match(modal, /load\(connection\.adapter === "creality_local"\)/);
  assert.match(modal, /\/files\/\?refresh_status=1/);
  assert.match(modal, /mapped_cfs_blockers/);
  assert.match(modal, /Refresh K2 CFS readiness \(read-only\)/);
  assert.match(modal, /!cfsMappedAvailable/);
  assert.match(modal, /supervisedTestEligible && mappedCfs/);
});

test("G-code toolpath uses right-handed printer coordinates, not a reflected axis swap", () => {
  // The native build plate uses X right, Y rear, Z up. Three.js uses Y up.
  // Proper mapping is (X, Y, Z) -> (X, Z, -Y), a rotation, not a reflection.
  const editor = read("../src/components/SlicerPlateEditor.jsx");
  assert.match(editor, /camera\.position\.set\(bedX \* 1\.0, -bedY \* 1\.3,/);
  assert.match(viewport, /new THREE\.Vector3\(segment\[0\], segment\[4\], -segment\[1\]\)/);
  assert.match(viewport, /new THREE\.Vector3\(segment\[2\], segment\[4\], -segment\[3\]\)/);
  assert.match(viewport, /new THREE\.Vector3\(width \/ 2, 0, -depth \/ 2\)/);
  assert.match(viewport, /positions\.push\(x1, z, -y1, x2, z, -y2\)/);
  assert.match(viewport, /lastStep = \[x2, z, -y2\]/);
  assert.match(viewport, /-\(y1\+y2\)\/2/);
  assert.match(viewport, /new THREE\.Vector3\(distance \* 0\.7, distance \* 0\.9, distance\)/);
  assert.match(viewport, /new THREE\.Vector3\(0, span \* 0\.25, span\)/);
  assert.match(viewport, /new THREE\.Vector3\(span \* 0\.7, span \* 0\.85, span\)/);
  assert.match(viewport, /viewName === "top" \? \[0, 0, -1\] : \[0, 1, 0\]/);
  assert.doesNotMatch(viewport, /positions\.push\(x1, z, y1, x2, z, y2\)/);
});

test("mobile preview retains the toolpath, temperatures and primary figures", () => {
  assert.match(preview, /<SlicerToolpath3D segments=/);
  assert.match(preview, /Estimated print time/);
  assert.match(preview, /temperatureInfo/);
  assert.match(viewer, /profileTemperatures=\{analysis\.print_setup\?\.profile_temperatures_c\}/);
  assert.match(preview, /Nozzle temperature · G-code\/profile/);
  assert.match(preview, /Bed temperature · G-code\/profile/);
  assert.match(viewer, /slicerGcodeQuickSummary/);
  assert.match(mobileCss, /\.slicerGcodeQuickSummary/);
  assert.match(mobileCss, /\.slicerResultLayerLayout/);
});

test("review layout keeps temperatures, detail table and source reader responsive", () => {
  const source = read("../src/components/GcodeFullSource.jsx");
  assert.match(preview, /Chamber temperature · G-code\/profile/);
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
  assert.ok(styles.includes(".slicerWorkbenchRoot .slicerHeroActions > .slicerHeroBack"));
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
