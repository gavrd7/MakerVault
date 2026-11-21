import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {autoPrimeTowerPosition,towerFits} from "../src/components/slicerPrimeTower.js";

const model={instance_id:"benchy",x_mm:0,y_mm:0,rotation_deg:0,scale_percent:100};
const dimensions={benchy:{width:40,depth:40,height:50}};

test("automatic tower placement avoids a centre model and bed edges",()=>{
  const tower=autoPrimeTowerPosition([model],dimensions,260,260,35,35);
  assert.ok(tower);
  assert.equal(towerFits(tower,[model],dimensions,260,260,35,35),true);
  assert.ok(tower.x>4 && tower.x+35<256);
  assert.ok(tower.y>4 && tower.y+35<256);
});
test("manual position preserves safe location and rejects overlaps",()=>{
  assert.equal(towerFits({x:110,y:110},[model],dimensions,260,260,35,35),false);
  assert.equal(towerFits({x:8,y:210},[model],dimensions,260,260,35,35),true);
  assert.equal(towerFits({x:0,y:220},[model],dimensions,260,260,35,35),false);
});
test("missing dimensions and packed plates never invent clearance",()=>{
  assert.equal(autoPrimeTowerPosition([model],{},260,260,35,35),null);
  assert.equal(autoPrimeTowerPosition([model],dimensions,35,35,35,35),null);
  assert.equal(towerFits({x:15,y:220},[model],{},260,260,35,35),false);
});
test("a manually shifted model changes the available tower positions",()=>{
  const shifted={...model,x_mm:0,y_mm:100};
  assert.equal(towerFits({x:108,y:218},[shifted],dimensions,260,260,35,35),false);
  const tower=autoPrimeTowerPosition([shifted],dimensions,260,260,35,35);
  assert.ok(tower);
  assert.equal(towerFits(tower,[shifted],dimensions,260,260,35,35),true);
});

test("Creality Print exposes the existing draggable tower with native X/Y persistence",()=>{
  const workspace=readFileSync(new URL("../src/components/SlicerPrepareWorkspace.jsx",import.meta.url),"utf8");
  const workbench=readFileSync(new URL("../src/components/SlicerWorkbench.jsx",import.meta.url),"utf8");
  assert.match(workspace,/primeTowerEnabled=\{\["orcaslicer","crealityprint"\]\.includes\(activeEngine\)/);
  assert.match(workspace,/assignedSlotIds=\{requiredMultiSlots\}/);
  assert.match(workspace,/engine=\{activeEngine\}/);
  assert.match(workbench,/primeTower=\{primeTower\} onPrimeTowerChange=\{setPrimeTower\}/);
  assert.doesNotMatch(workbench,/\(\(!singlePainted && !twoPlain\) \|\| flushSettings\)/);
});

test("Creality flush modal retains a native multiplier and blocks unmapped slot edits",()=>{
  const modal=readFileSync(new URL("../src/components/SlicerFlushVolumes.jsx",import.meta.url),"utf8");
  assert.match(modal,/id="slicer-flush-multiplier"[^]*?disabled=\{disabled\}/);
  assert.match(modal,/disabled=\{disabled \|\| !editableTransition\(from,to\)\}/);
  assert.match(modal,/Selected process profile belongs to a different slicer engine/);
});
