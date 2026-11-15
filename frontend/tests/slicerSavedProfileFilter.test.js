import test from "node:test";
import assert from "node:assert/strict";
import { profilesForEngineVersion } from "../src/components/slicerSavedProfileFilter.js";

const profiles = [
  { id: 1, engine: "orcaslicer", engine_version: "2.4.2", kind: "printer" },
  { id: 2, engine: "orcaslicer", engine_version: "2.5.0", kind: "printer" },
  { id: 3, engine: "orcaslicer", engine_version: "2.5.0", kind: "filament", is_dependency: true },
  { id: 4, engine: "crealityprint", engine_version: "2.5.0", kind: "printer" },
  { id: 5, engine: "orcaslicer", engine_version: "2.5", kind: "process" },
];

test("saved profiles follow the exact selected engine and engine version", () => {
  assert.deepEqual(profilesForEngineVersion(profiles, "orcaslicer", "2.5.0").map(p => p.id), [2]);
  assert.deepEqual(profilesForEngineVersion(profiles, "orcaslicer", "2.4.2").map(p => p.id), [1]);
  assert.deepEqual(profilesForEngineVersion(profiles, "crealityprint", "2.5.0").map(p => p.id), [4]);
  assert.deepEqual(profilesForEngineVersion(profiles, "orcaslicer", "").map(p => p.id), []);
});

test("native dependencies stay hidden until explicitly shown while managing", () => {
  assert.deepEqual(profilesForEngineVersion(profiles, "orcaslicer", "2.5.0",
    { managing: false, showDependencies: true }).map(p => p.id), [2]);
  assert.deepEqual(profilesForEngineVersion(profiles, "orcaslicer", "2.5.0",
    { managing: true, showDependencies: true }).map(p => p.id), [2, 3]);
});
