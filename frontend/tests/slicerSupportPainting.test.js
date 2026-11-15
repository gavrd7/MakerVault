import test from "node:test";
import assert from "node:assert/strict";
import {createSupportPaint,applySupportPaint,validateSupportPaint,
  supportPaintPatchCount,SUPPORT_ENFORCE,SUPPORT_BLOCK} from "../src/components/slicerSupportPainting.js";

const mesh={signature:"1:abc123",faceCount:1,
  triangle:()=>[[0,0,0],[20,0,0],[0,20,0]]};
const at=(x,y)=>({mode:"disc",faces:[0],centre:[x,y,0],normal:[0,0,1],radiusMm:2});
test("support paint preserves clipped geometry independently of filament slots",()=>{
  const empty=createSupportPaint(mesh);
  const enforce=applySupportPaint(empty,mesh,at(5,5),SUPPORT_ENFORCE);
  assert.equal(supportPaintPatchCount(enforce),1);
  assert.equal(enforce.regions[0].slot,SUPPORT_ENFORCE);
  assert.ok(enforce.regions[0].patches[0].polygon.length>3);
  assert.equal(empty.regions.length,0);
  const block=applySupportPaint(enforce,mesh,at(5,5),SUPPORT_BLOCK);
  assert.equal(block.regions.at(-1).slot,SUPPORT_BLOCK);
  assert.ok(block.regions.every(r=>r.slot===SUPPORT_ENFORCE||r.slot===SUPPORT_BLOCK));
  assert.deepEqual(validateSupportPaint(block,mesh),block);
});
test("support eraser removes the targeted patch without adding a material slot",()=>{
  const state=applySupportPaint(createSupportPaint(mesh),mesh,at(5,5),SUPPORT_ENFORCE);
  const cleared=applySupportPaint(state,mesh,at(5,5),null);
  assert.equal(supportPaintPatchCount(cleared),0);
  assert.equal(state.regions.length,1);
});
test("support paint rejects stale meshes, arbitrary colour slot and malformed actions",()=>{
  const state=createSupportPaint(mesh);
  assert.throws(()=>validateSupportPaint(state,{...mesh,signature:"1:changed"}));
  assert.throws(()=>applySupportPaint(state,mesh,at(5,5),2));
  assert.throws(()=>validateSupportPaint({...state,regions:[{slot:2,patches:[{
    face:0,polygon:[[0,0,0],[1,0,0],[0,1,0]]}]}]},mesh));
});
