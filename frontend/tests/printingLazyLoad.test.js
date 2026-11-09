import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const printing = fs.readFileSync(path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrintingPage.jsx"
), "utf8");

test("3D Printing overview does not eagerly import the slicer editor", () => {
  assert.doesNotMatch(printing, /^import SlicerWorkbench from /m);
  assert.doesNotMatch(printing, /^import SavedSlicerJobsModal from /m);
  assert.match(printing, /lazy\(\(\) => import\("\.\/SlicerWorkbench"\)\)/);
  assert.match(printing, /lazy\(\(\) => import\("\.\/SavedSlicerJobsModal"\)\)/);
  assert.match(printing, /Suspense fallback=\{<LoadingBlock/);
});

test("3D Printing requests overview data without the full filament catalogue", () => {
  assert.match(printing, /useEffect\(\(\) => \{ load\(\{ includeFilaments: false \}\); \}, \[\]\)/);
  assert.match(printing, /options\?\.includeFilaments \?\? filamentsLoaded/);
  assert.match(printing, /\["spools", "filaments", "reusableSpools"\]\.includes\(workspaceView\)/);
  assert.match(printing, /filamentFetchRef\.current/);
  assert.match(printing, /Retry loading filament catalogue/);
});

test("15-second telemetry refresh leaves downloaded filament catalogue alone", () => {
  assert.match(printing, /load\(\{includeFilaments:false\}\)/);
  assert.match(printing, /filaments: previous\?\.filaments \|\| \[\]/);
});
