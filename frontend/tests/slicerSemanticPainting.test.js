import test from "node:test";
import assert from "node:assert/strict";
import {createSemanticPaint,applySemanticPaint,validateSemanticPaint,semanticField} from "../src/components/slicerSemanticPainting.js";
const mesh={faceCount:1,signature:"1:abcd",triangle:()=>[[0,0,0],[10,0,0],[0,10,0]]};
test("seam and fuzzy semantic paint share clipped patches but not slots",()=>{
  const original=createSemanticPaint(mesh);
  const paint={mode:"facet",faces:[0]};
  const seam=applySemanticPaint(original,mesh,"seam",paint,1);
  assert.equal(seam.regions[0].slot,1);
  assert.throws(()=>validateSemanticPaint(seam,mesh,"fuzzy"));
  const fuzzy=applySemanticPaint(original,mesh,"fuzzy",paint,0);
  assert.equal(fuzzy.regions.length,1);
  assert.throws(()=>applySemanticPaint(fuzzy,mesh,"fuzzy",paint,1));
  const erased=applySemanticPaint(fuzzy,mesh,"fuzzy",paint,null);
  assert.equal(erased.regions.length,0);
  assert.equal(semanticField("seam"),"seam_paint");
  assert.equal(semanticField("fuzzy"),"fuzzy_skin_paint");
});
