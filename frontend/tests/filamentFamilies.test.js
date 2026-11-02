import test from "node:test";
import assert from "node:assert/strict";
import {filamentFamily,filamentFamilyKey,filamentVariantLabel} from "../src/components/filamentFamilies.js";

test("multiple manufacturers share the same product/variant normalization",()=>{
  const samples=[
    [{manufacturer:"Sunlu",name:"2.0 Aqua Blue",material:"PETG",color_hex:"#00aabb"},
     {manufacturer:"SUNLU",name:"2.0 Beige",material:"PETG",color_hex:"#eee8da"},"2.0"],
    [{manufacturer:"Extrudr",name:"NX2-MATT - Military Beige",material:"PLA"},
     {manufacturer:"Extrudr",name:"NX2-MATT - Metallic Grey",material:"PLA"},"NX2-MATT"],
    [{manufacturer:"Polymaker",name:"PolyLite PLA - Red",material:"PLA"},
     {manufacturer:"Polymaker",name:"PolyLite PLA - Blue",material:"PLA"},"PolyLite PLA"],
    [{manufacturer:"3D-Fuel",name:"Almond",material:"PLA+"},
     {manufacturer:"3D-Fuel",name:"Aquamarine",material:"PLA+"},"PLA+"],
  ];
  for(const [a,b,expected] of samples){
    assert.equal(filamentFamily(a).product,expected);
    assert.equal(filamentFamily(b).product,expected);
    assert.equal(filamentFamilyKey(a),filamentFamilyKey(b));
  }
});
test("different materials and manufacturer are different families",()=>{
  const a={manufacturer:"Maker",name:"Hyper PLA - Red",material:"PLA"};
  assert.notEqual(filamentFamilyKey(a),filamentFamilyKey({...a,material:"PETG"}));
  assert.notEqual(filamentFamilyKey(a),filamentFamilyKey({...a,manufacturer:"Other"}));
});
test("retain unknown colour product names rather than blindly removing suffix",()=>{
  assert.equal(filamentFamily({manufacturer:"Brand",name:"Special Blend - Carbon Fiber",material:"PLA"}).product,"Special Blend - Carbon Fiber");
  assert.equal(filamentVariantLabel({name:"2.0 Aqua Blue"}),"Aqua Blue");
});
