import test from "node:test";
import assert from "node:assert/strict";
import {
  engineFeature, engineCompatibilityIssues, usedNativeFeatures,
} from "../src/components/slicerEngineCompatibility.js";

const engine = {
  feature_capabilities: {
    "2.5.0": {
      support_paint: {status:"draft_only",reason:"Native export pending"},
      fuzzy_skin_paint: {status:"draft_only",reason:"Native export pending"},
    },
    default: {
      support_paint: {status:"unverified",reason:"Not reviewed"},
      fuzzy_skin_paint: {status:"unverified",reason:"Not reviewed"},
    },
  },
};

test("engine capability follows the exact native version",()=>{
  assert.equal(engineFeature(engine,"2.5.0","support_paint").status,"draft_only");
  assert.equal(engineFeature(engine,"2.6.0","support_paint").status,"unverified");
  assert.equal(engineFeature(null,"2.5.0","support_paint").status,"unverified");
});

test("saved semantic edits survive inspection and all used unverified features block",()=>{
  const project = [{objects:[
    {support_paint:{regions:[{slot:0}]},fuzzy_skin_paint:{regions:[]}},
    {fuzzy_skin_paint:{regions:[{slot:0}]}},
  ]}];
  assert.deepEqual(usedNativeFeatures(project),["fuzzy_skin_paint","support_paint"]);
  assert.deepEqual(
    engineCompatibilityIssues(engine,"2.5.0",project).map(item=>item.feature),
    ["fuzzy_skin_paint","support_paint"]);
  assert.deepEqual(usedNativeFeatures([{objects:[{support_paint:{regions:[]}}]}]),[]);
});
