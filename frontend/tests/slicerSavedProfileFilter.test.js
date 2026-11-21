import test from "node:test";
import assert from "node:assert/strict";
import { profilesForEngineVersion, isInternalNativeProfile, readableNativeProfile } from "../src/components/slicerSavedProfileFilter.js";

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

test("Orca base and BBL base entries are hidden even without a dependency flag", () => {
  const entries = [
    {id:"base",engine:"orcaslicer",engine_version:"2.5.0",kind:"filament",name:"SUNLU PLA+ 2.0 @base"},
    {id:"bbl",engine:"orcaslicer",engine_version:"2.5.0",kind:"filament",name:"Generic PLA Silk @BBL base"},
    {id:"system",engine:"orcaslicer",engine_version:"2.5.0",kind:"filament",name:"Generic PLA @System"},
    {id:"k2",engine:"orcaslicer",engine_version:"2.5.0",kind:"filament",name:"Hyper PLA @Creality K2"},
  ];
  assert.deepEqual(profilesForEngineVersion(entries,"orcaslicer","2.5.0").map(p=>p.id),["system","k2"]);
  assert.deepEqual(profilesForEngineVersion(entries,"orcaslicer","2.5.0",{
    managing:true,showDependencies:true,
  }).map(p=>p.id),["base","bbl","system","k2"]);
  assert.equal(isInternalNativeProfile(entries[0]),true);
  assert.equal(isInternalNativeProfile(entries[1]),true);
  assert.equal(isInternalNativeProfile(entries[2]),false);
  assert.deepEqual(readableNativeProfile(entries[2]),{
    name:"Generic PLA",type:"Generic preset",internal:false,
  });
  assert.equal(readableNativeProfile(entries[1]).name,"Generic PLA Silk");
  assert.equal(readableNativeProfile(entries[3]).name,"Hyper PLA @Creality K2");
});

test("dependency metadata takes precedence over an otherwise selectable name", () => {
  const parent={name:"Shared PLA @System",is_dependency:true};
  assert.equal(isInternalNativeProfile(parent),true);
  assert.equal(readableNativeProfile(parent).internal,true);
});
