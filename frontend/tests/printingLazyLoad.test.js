import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const source = fs.readFileSync(path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrintingPage.jsx"
), "utf8");

test("3D Printing does not eagerly import the slicer editor", () => {
  assert.ok(!source.includes('import SlicerWorkbench from'));
  assert.ok(!source.includes('import SavedSlicerJobsModal from'));
  assert.ok(source.includes('lazy(() => import("./SlicerWorkbench"))'));
  assert.ok(source.includes('lazy(() => import("./SavedSlicerJobsModal"))'));
  assert.ok(source.includes('<Suspense fallback='));
});

test("overview defers huge filament and model file catalogues", () => {
  assert.ok(source.includes('load({ includeFilaments: false, includeFiles: false })'));
  assert.ok(source.includes('query.set("include_filaments", "0")'));
  assert.ok(source.includes('query.set("include_files", "0")'));
  assert.ok(source.includes('filamentFetchRef.current'));
  assert.ok(source.includes('filesFetchRef.current'));
  assert.ok(source.includes('Retry loading filament catalogue'));
  assert.ok(source.includes('Retry loading model and G-code files'));
});

test("telemetry refresh preserves already fetched immutable catalogues", () => {
  assert.ok(source.includes('load({includeFilaments:false, includeFiles:false})'));
  assert.ok(source.includes('filaments: includeFilaments ? fresh.filaments : previous?.filaments || []'));
  assert.ok(source.includes('gcode_files: includeFiles ? fresh.gcode_files : previous?.gcode_files || []'));
  assert.ok(source.includes('model_files: includeFiles ? fresh.model_files : previous?.model_files || []'));
});
