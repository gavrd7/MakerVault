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

test("v2 eraser cuts a hole in a painted face without removing the whole triangle",()=>{
  const base=createPaintRegions(mesh);
  const painted=appendPaintRegion(base,mesh,{mode:"facet",faces:[0]},1);
  const erased=appendPaintRegion(painted,mesh,{mode:"disc",faces:[0],
    centre:[0,0,0],normal:[0,0,1],radiusMm:5},null);
  assert.ok(erased.regions.length>0,"the surrounding colour must remain");
  assert.ok(erased.regions[0].patches.length>1,"the original face should split into fragments");
  assert.ok(erased.regions[0].patches.every(p=>p.polygon.length>=3));
  assert.deepEqual(painted.regions[0].patches[0].polygon,mesh.triangle(0));
  assert.deepEqual(validatePaintRegions(JSON.parse(JSON.stringify(erased)),mesh,[1]),erased);
});
test("v2 overlapping colour replaces only the intersecting subregion",()=>{
  const painted=appendPaintRegion(createPaintRegions(mesh),
    mesh,{mode:"facet",faces:[0]},1);
  const recoloured=appendPaintRegion(painted,mesh,{mode:"disc",faces:[0],
    centre:[0,0,0],normal:[0,0,1],radiusMm:5},2);
  assert.ok(recoloured.regions.some(r=>r.slot===1));
  assert.ok(recoloured.regions.some(r=>r.slot===2));
  assert.ok(recoloured.regions.find(r=>r.slot===1).patches.length>1);
  assert.ok(recoloured.regions.find(r=>r.slot===2).patches[0].polygon.length>=12);
});
test("v2 large height selection is stored as one region rather than one edit per face",()=>{
  const many={signature:"5000:abc",faceCount:5000,triangle:()=>mesh.triangle(1)};
  const painted=appendPaintRegion(createPaintRegions(many),many,
    {mode:"height",faces:Array.from({length:5000},(_,i)=>i),
      minHeightMm:4,maxHeightMm:9},1);
  assert.equal(painted.regions.length,1);
  assert.equal(painted.regions[0].patches.length,5000);
});
test("v2 spherical paint clips a tangent plane to the correct circle",()=>{
  const painted=appendPaintRegion(createPaintRegions(mesh),mesh,{mode:"sphere",
    faces:[0],centre:[0,0,3],radiusMm:5},1);
  const polygon=painted.regions[0].patches[0].polygon;
  assert.ok(polygon.length>=12);
  assert.ok(polygon.every(p=>Math.hypot(p[0],p[1])<=4.00001));
  assert.ok(polygon.every(p=>Math.abs(p[2])<1e-6));
});

test("v2 a later smaller stamp inside an erased hole does not fragment surrounding paint",()=>{
  const solid=appendPaintRegion(createPaintRegions(mesh),mesh,
    {mode:"facet",faces:[0]},1);
  const erased=appendPaintRegion(solid,mesh,{mode:"disc",faces:[0],
    centre:[0,0,0],normal:[0,0,1],radiusMm:5},null);
  const around=erased.regions[0].patches.length;
  const smaller=appendPaintRegion(erased,mesh,{mode:"disc",faces:[0],
    centre:[0,0,0],normal:[0,0,1],radiusMm:2},2);
  assert.equal(smaller.regions[0].patches.length,around);
  assert.equal(smaller.regions.find(r=>r.slot===2).patches.length,1);
});
