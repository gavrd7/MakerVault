import test from "node:test";
import assert from "node:assert/strict";
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
