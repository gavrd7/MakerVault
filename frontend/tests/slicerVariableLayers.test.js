import test from "node:test";
import assert from "node:assert/strict";
import {addVariableLayerBand,validateVariableLayerBands} from "../src/components/slicerVariableLayers.js";
test("variable layer bands sort and reject overlap",()=>{
  const result=addVariableLayerBand([{from_mm:10,to_mm:20,layer_mm:0.12}],0,10,0.2);
  assert.deepEqual(result.map(x=>x.from_mm),[0,10]);
  assert.throws(()=>addVariableLayerBand(result,5,15,0.1),/overlap/);
  assert.throws(()=>validateVariableLayerBands([{from_mm:0,to_mm:20,layer_mm:1}]));
});
