import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const dir=path.dirname(fileURLToPath(import.meta.url));
const read=name=>fs.readFileSync(path.resolve(dir,"../src/components",name),"utf8");
const manager=read("SlicerEngineManager.jsx");
const workbench=read("SlicerWorkbench.jsx");

test("engine installer shows actual approved releases and worker status",()=>{
  assert.match(manager,/approved_releases/);
  assert.match(manager,/host_updater_connected/);
  assert.match(manager,/installed_version/);
  assert.match(manager,/Recent engine operations/);
  assert.match(manager,/Installation package not yet available/);
  assert.match(manager,/state\?\.can_manage !== false/);
});

test("user-initiated engine installation uses a pinned release and confirmation",()=>{
  assert.match(manager,/window\.confirm/);
  assert.match(manager,/release_sha256:release\.bundle_sha256/);
  assert.match(manager,/method:"POST"/);
  assert.match(manager,/installation_available/);
  assert.match(manager,/!!operation/);
  assert.doesNotMatch(manager,/eval\(|docker\s|window\.location\s*=/);
});

test("existing setup opens the integrated engine manager without altering slicing",()=>{
  assert.match(workbench,/import SlicerEngineManager/);
  assert.match(workbench,/<SlicerEngineManager engines=\{engines\}/);
  assert.doesNotMatch(workbench,/canManage=\{canVerifyProfiles\}/);
  assert.match(workbench,/View engine installations/);
});

test("installed OrcaSlicer never looks unavailable just because an update is absent",()=>{
  assert.match(manager,/engine\.available === true \|\| engine\.status === "validated"/);
  assert.match(manager,/Already installed — no newer version available/);
  assert.doesNotMatch(manager,/No approved installation release is available yet/);
  assert.match(manager,/rollback_available/);
});
