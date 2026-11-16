import test from "node:test";
import assert from "node:assert/strict";
import {matchLoadedSlotProfiles,slotProfileSearchTerm} from "../src/components/slicerSlotProfileMatching.js";

const base={kind:"filament",engine:"orcaslicer",engine_version:"2.5.0"};
const profile=(id,name,extra={})=>({...base,id,name,...extra});
const scope={engine:"orcaslicer",version:"2.5.0",printer:{model:"Creality K2 Combo",manufacturer:"Creality"}};
test("only one exactly matching product is eligible for automatic slot mapping",()=>{
  const slot={product_name:"PLA Silk",material:"PLA"};
  let result=matchLoadedSlotProfiles(slot,[
    profile("silk","Generic PLA Silk @System"),
    profile("basic","Generic PLA Basic @System"),
  ],scope);
  assert.equal(result.level,"exact");
  assert.equal(result.profile.id,"silk");
  result=matchLoadedSlotProfiles(slot,[
    profile("a","Generic PLA Silk @System"),
    profile("b","Generic PLA Silk @System"),
  ],scope);
  assert.equal(result.level,"ambiguous");
  assert.equal(result.profile,undefined);
});
test("material-only suggestions do not silently auto-select a different product",()=>{
  const result=matchLoadedSlotProfiles({product_name:"PLA Basic",material:"PLA"},[
    profile("generic","Generic PLA @System"),profile("silk","Generic PLA Silk @System"),
  ],scope);
  assert.equal(result.level,"fallback");
  assert.equal(result.profile,undefined);
  assert.deepEqual(result.suggestions.map(p=>p.id),["generic"]);
});
test("printer, engine, version and material type are mandatory",()=>{
  const slot={product_name:"PLA Silk",material:"PLA"};
  const result=matchLoadedSlotProfiles(slot,[
    profile("petg","Generic PETG Silk @System"),
    profile("old","Generic PLA Silk @System",{engine_version:"2.4.2"}),
    profile("foreign","Generic PLA Silk @Creality K1"),
    profile("dependency","Generic PLA Silk @System",{is_dependency:true}),
  ],scope);
  assert.equal(result.level,"missing");
});
test("branded slots do not claim exact matches with generic or unrelated brands",()=>{
  const slot={product_name:"Hyper PLA",material:"PLA",manufacturer:"Creality"};
  const result=matchLoadedSlotProfiles(slot,[
    profile("generic","Generic Hyper PLA @System"),
    profile("other","Sunlu Hyper PLA @System"),
  ],scope);
  assert.notEqual(result.level,"exact");
});
test("PLA+ never auto-matches an ordinary PLA native preset",()=>{
  const result=matchLoadedSlotProfiles({product_name:"PLA+",material:"PLA"},[
    profile("plain","Generic PLA @System"),
  ],scope);
  assert.notEqual(result.level,"exact");
  const plus=matchLoadedSlotProfiles({product_name:"PLA+",material:"PLA"},[
    profile("plus","Generic PLA+ @System"),
  ],scope);
  assert.equal(plus.level,"exact");
  assert.equal(plus.profile.id,"plus");
});
test("unknown material is not auto matched and search terms stay bounded",()=>{
  assert.equal(matchLoadedSlotProfiles({product_name:"Unknown Spool"},[profile("x","Generic PLA")],scope).level,"unknown");
  assert.equal(slotProfileSearchTerm({product_name:"PLA Silk",material:"PLA"}),"PLA Silk");
  assert.equal(slotProfileSearchTerm({material:"PETG"}),"PETG");
});
