import test from "node:test";
import assert from "node:assert/strict";
import {ORCA_PLATE_TYPES,plateOptions} from "../src/components/slicerPlateOptions.js";

test("imported Orca profile controls available plate illustrations",()=>{
  const plates=plateOptions("orcaslicer",{
    default:"textured_pei",
    supported:["textured_pei","high_temp"],
  });
  assert.deepEqual(plates.map(([key])=>key),["high_temp","textured_pei"]);
  assert.equal(plates.find(([key])=>key==="textured_pei")[1],"Textured PEI Plate");
  assert.equal(ORCA_PLATE_TYPES.length,7);
});

test("unknown or unrelated engines do not claim support for every plate",()=>{
  assert.deepEqual(plateOptions("orcaslicer",null).map(([key])=>key),["default"]);
  assert.deepEqual(plateOptions("cura",{
    supported:["cool","textured_pei"],
  }).map(([key])=>key),["default"]);
  assert.deepEqual(plateOptions("orcaslicer",{
    supported:[],
  }).map(([key])=>key),["cool","engineering","high_temp","textured_pei","textured_cool","supertack"]);
});

test("Creality Print native profile offers bed surfaces from resolved capabilities",()=>{
  const plates=plateOptions("crealityprint",{
    default:null,
    supported:["engineering","textured_pei","supertack"],
  });
  assert.deepEqual(plates.map(([key])=>key),
    ["engineering","textured_pei","supertack"]);
  assert.deepEqual(plateOptions("crealityprint",null).map(([key])=>key),["default"]);
  assert.deepEqual(plateOptions("crealityprint",{supported:[]}).map(([key])=>key),["default"]);
});
