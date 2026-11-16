import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const base = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const read = name => fs.readFileSync(path.join(base,name),"utf8");
const setup = read("SlicerWorkbench.jsx");
const prepare = read("SlicerPrepareWorkspace.jsx");
const plate = read("SlicerPlateEditor.jsx");

test("engine version is selected from known discovered versions, not typed", () => {
  assert.match(setup, /const engineVersions =/);
  assert.match(setup, /installed_versions/);
  assert.match(setup, /<label>Engine version\s*<select required/);
  assert.match(setup, /Profiles only/);
  assert.doesNotMatch(setup, /placeholder="Exact installed\/version-matched engine version"/);
});

test("named imported material profile is available to assigned slot even when reused as parent", () => {
  assert.match(setup, /const slotFilamentChoices = profiles\.filter/);
  assert.match(setup, /filamentProfiles=\{slotFilamentChoices\}/);
  assert.match(setup, /!\/@\\s\*\.\*\\bbase\\s\*\$\/i\.test\(profile\.name/);
  assert.match(prepare, /onFilamentProfilesReload\?\.\(\)/);
  assert.match(prepare, /profile_id: String\(imported\.id\)/);
  assert.match(prepare, /Import & assign/);
});

test("variable layer editor can position a selected thickness band", () => {
  assert.match(prepare, /aria-label="Variable layer height Z band thickness"/);
  assert.match(prepare, /type="range" min="0\.5" max="50" step="0\.5"/);
  assert.match(prepare, /Position entire band/);
  assert.match(prepare, /onVariableLayerHeightPick=\{z=>/);
});

test("painted surface annotations are hidden until their tool is active", () => {
  assert.match(plate, /toolMode==="paint_support"\?item\.support_paint:null/);
  assert.match(plate, /toolMode==="paint_seam"\?item\.seam_paint:null/);
  assert.match(plate, /toolMode==="paint_fuzzy"\?item\.fuzzy_skin_paint:null/);
  assert.match(plate, /toolMode==="paint_colour"\?item\.colour_paint:null/);
  assert.match(plate, /latestToolModeRef\.current==="paint_support"/);
});
