import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {estimateColourFlush,estimateSlotFlush,multiplyFlushEstimate,slotMaterialCompatibility} from "../src/components/slicerFlushEstimates.js";
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../src");

test("Orca analytic fallback is directional and does not imply a printer minimum",()=>{
  assert.ok(Math.abs(estimateColourFlush("#000000","#ffffff")-560)<=1);
  assert.ok(Math.abs(estimateColourFlush("#ffffff","#000000")-80)<=1);
  assert.notEqual(estimateColourFlush("#00ff00","#ffffff"),
    estimateColourFlush("#ffffff","#00ff00"));
});
test("malformed swatches and mixed or unknown materials cannot be estimated",()=>{
  assert.equal(estimateColourFlush("#123","#abcdef"),null);
  assert.equal(estimateSlotFlush({material:"PLA",color_hex:"#000000"},
    {material:"ABS",color_hex:"#ffffff"}),null);
  assert.ok(Math.abs(estimateSlotFlush({material:"PLA",color_hex:"#000000"},
    {material:"PLA",color_hex:"#ffffff"})-560)<=1);
  assert.equal(estimateSlotFlush({material:"?",color_hex:"#000000"},
    {material:"?",color_hex:"#ffffff"}),null);
});
test("flush form aligns controls without obsolete estimate toggles",()=>{
  const src=fs.readFileSync(path.join(base,"components/SlicerFlushVolumes.jsx"),"utf8");
  const css=fs.readFileSync(path.join(base,"styles.css"),"utf8");
  assert.match(src,/className="slicerFlushField"/);
  assert.match(src,/id="slicer-flush-multiplier"/);
  assert.match(src,/id="slicer-flush-prime-tower"/);
  assert.match(css,/grid-template-rows:22px 48px minmax\(30px,auto\)/);
  assert.match(css,/height:48px;min-height:48px;max-height:48px/);
  assert.doesNotMatch(src,/Show colour-only estimates/);
  assert.doesNotMatch(src,/window\.confirm\(/);
  assert.doesNotMatch(src,/Copy estimates to draft/);
  assert.doesNotMatch(src,/estimateMode/);
  assert.match(src,/Reset to default/);
});

test("mixed PLA/ABS is previewable but not an auto-copy candidate",()=>{
 const pla={material:"PLA",color_hex:"#ffffff"},abs={material:"ABS",color_hex:"#000000"};
 assert.equal(slotMaterialCompatibility(pla,abs),"mixed");
 assert.equal(estimateSlotFlush(pla,abs),null);
 assert.ok(estimateSlotFlush(pla,abs,{allowMixed:true})>0);
 assert.equal(slotMaterialCompatibility(pla,pla),"same");
 assert.equal(slotMaterialCompatibility({material:"unknown"},abs),"unknown");
});
test("recalculate preview multiplier, retaining directional overrides",()=>{
 assert.equal(multiplyFlushEstimate(100,1),100);
 assert.equal(multiplyFlushEstimate(100,1.3),130);
 assert.equal(multiplyFlushEstimate(100,2),200);
 assert.equal(multiplyFlushEstimate(null,2),null);
 assert.equal(multiplyFlushEstimate(100,NaN),null);
 const src=fs.readFileSync(path.join(base,"components/SlicerFlushVolumes.jsx"),"utf8");
 assert.ok(src.includes("setPreviewMultiplier(desiredMultiplier)"));
 assert.ok(src.includes("Recalculate"));
 assert.ok(src.includes("estimateSlotFlush(from,to,{allowMixed:true})"));
 assert.ok(!src.includes("Copy estimates to draft"));
 assert.ok(!src.includes("Copy estimates to draft"));
});
