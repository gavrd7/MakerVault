import test from "node:test";
import assert from "node:assert/strict";
import {createPaintRegions,appendPaintRegion,removeLastPaintRegion,validatePaintRegions}
  from "../src/components/slicerPaintRegions.js";
const mesh={signature:"2:abc",faceCount:2,triangle:f=>f===0?
  [[-50,-50,0],[50,-50,0],[0,50,0]]:
  [[0,0,0],[10,0,20],[0,10,20]]};
test("v2 disc stores a clipped circular boundary that survives JSON round-trip",()=>{
  const blank=createPaintRegions(mesh);
  const painted=appendPaintRegion(blank,mesh,{mode:"disc",faces:[0],
    centre:[0,0,0],normal:[0,0,1],radiusMm:5},1);
  const polygon=painted.regions[0].patches[0].polygon;
  assert.ok(polygon.length>=12);
  assert.ok(polygon.every(p=>Math.hypot(p[0],p[1])<=5+1e-5));
  assert.deepEqual(blank.regions,[]);
  assert.deepEqual(validatePaintRegions(JSON.parse(JSON.stringify(painted)),mesh,[1]),painted);
  assert.deepEqual(removeLastPaintRegion(painted,mesh),blank);
});
test("v2 height clips to both exact Z planes",()=>{
  const painted=appendPaintRegion(createPaintRegions(mesh),mesh,
    {mode:"height",faces:[0,1],minHeightMm:4,maxHeightMm:9},2);
  assert.deepEqual(painted.regions[0].patches.map(p=>p.face),[1]);
  const polygon=painted.regions[0].patches[0].polygon;
  assert.ok(polygon.some(p=>Math.abs(p[2]-4)<1e-6));
  assert.ok(polygon.some(p=>Math.abs(p[2]-9)<1e-6));
  assert.ok(polygon.every(p=>p[2]>=4-1e-6&&p[2]<=9+1e-6));
});
test("reject stale geometry, palette mismatch and malicious patch coordinates",()=>{
  const painted=appendPaintRegion(createPaintRegions(mesh),mesh,
    {mode:"disc",faces:[0],centre:[0,0,0],normal:[0,0,1],radiusMm:5},1);
  assert.throws(()=>validatePaintRegions(painted,{...mesh,signature:"changed"}),/stale/);
  assert.throws(()=>validatePaintRegions(painted,mesh,[0]),/slot/);
  assert.throws(()=>validatePaintRegions({...painted,regions:[{slot:1,
    patches:[{face:500,polygon:[[0,0,0],[1,0,0],[0,1,0]]}]}]},mesh),/polygon/);
  assert.throws(()=>appendPaintRegion(painted,mesh,{mode:"disc",faces:[1],
    centre:[0,0,0],normal:[0,0,0],radiusMm:5},1));
});
