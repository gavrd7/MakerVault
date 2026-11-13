import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {estimateColourFlush,estimateSlotFlush} from "../src/components/slicerFlushEstimates.js";
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../src");

test("Orca analytic fallback is directional and does not imply a printer minimum",()=>{
  assert.ok(Math.abs(estimateColourFlush("#000000","#ffffff")-560)<=1);
  assert.equal(estimateColourFlush("#ffffff","#000000"),80);
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
test("flush form aligns native and custom controls; estimates stay optional",()=>{
  const src=fs.readFileSync(path.join(base,"components/SlicerFlushVolumes.jsx"),"utf8");
  const css=fs.readFileSync(path.join(base,"styles.css"),"utf8");
  assert.match(src,/className="slicerFlushField"/);
  assert.match(src,/id="slicer-flush-multiplier"/);
  assert.match(src,/id="slicer-flush-prime-tower"/);
  assert.match(css,/grid-template-rows:22px 48px minmax\(30px,auto\)/);
  assert.match(css,/height:48px;min-height:48px;max-height:48px/);
  assert.match(src,/Show Orca-style colour estimates/);
  assert.match(src,/window\.confirm\(/);
  assert.match(src,/Copy estimates to draft/);
  assert.match(src,/estimateMode \?/);
});
