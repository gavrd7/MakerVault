import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const components = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const full = fs.readFileSync(path.join(components, "GcodeFullSource.jsx"), "utf8");
const viewer = fs.readFileSync(path.join(components, "GcodeViewerModal.jsx"), "utf8");
const workbench = fs.readFileSync(path.join(components, "SlicerWorkbench.jsx"), "utf8");

test("complete source uses authenticated endpoint instead of the bounded inspection preview", () => {
  assert.match(full, /gcode\/source\//);
  assert.match(full, /credentials: "same-origin"/);
  assert.match(viewer, /<GcodeFullSource fileId=\{file.id\}/);
  assert.match(viewer, /Complete G-code/);
  assert.match(viewer, /report.preview_truncated/);
});

test("large files are paged and the copy action references the entire stored source", () => {
  assert.match(full, /PAGE_LINES = 400/);
  assert.match(full, /lines.slice\(page \* PAGE_LINES/);
  assert.match(full, /clipboard.writeText\(source.text\)/);
  assert.match(full, /\?download=1/);
  assert.match(full, /Download complete G-code/);
});

test("per-object evidence is distinguished from settings saved in the slicer job", () => {
  assert.match(full, /EXCLUDE_OBJECT_START/);
  assert.match(full, /Per-object toolpath evidence/);
  assert.match(full, /not wall-loop counts or infill percentages/);
  assert.match(viewer, /Settings saved with this slicing job/);
  assert.match(viewer, /overrides.wall_loops/);
  assert.match(viewer, /overrides.sparse_infill_density/);
  assert.match(workbench, /objectSettings=\{previewJob.settings\?\.plate_objects\}/);
});
