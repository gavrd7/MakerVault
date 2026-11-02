import test from "node:test";
import assert from "node:assert/strict";
import {filamentFamily,filamentFamilyKey,filamentVariantLabel,buildFilamentFamilyIndex} from "../src/components/filamentFamilies.js";

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

test("catalogue-context matching groups reordered unknown shade names, not records",()=>{
  const rows=[
    {id:"a",manufacturer:"Sample",material:"PLA",name:"Premium Speed Cherry 2.0",color_hex:"#ae1829"},
    {id:"b",manufacturer:"SAMPLE",material:"PLA",name:"Premium 2.0 Speed Lemon",color_hex:"#f2df20"},
    {id:"c",manufacturer:"Sample",material:"PETG",name:"Premium Speed Cherry 2.0",color_hex:"#ae1829"},
  ];
  const index=buildFilamentFamilyIndex(rows);
  assert.equal(index.get("a").key,index.get("b").key);
  assert.notEqual(index.get("a").key,index.get("c").key);
  assert.deepEqual(index.get("a").family.product.split(" ").sort(), ["premium","speed","2.0"].sort());
  assert.equal(index.get("a").shade,"cherry");
  assert.equal(index.get("b").shade,"lemon");
});
test("unrelated names and one-word overlaps are not conflated",()=>{
  const rows=[
    {id:"a",manufacturer:"Sample",material:"PLA",name:"Basic Red",color_hex:"#aa0000"},
    {id:"b",manufacturer:"Sample",material:"PLA",name:"Matte Blue",color_hex:"#0044aa"},
    {id:"c",manufacturer:"Other",material:"PLA",name:"Premium Speed Lemon",color_hex:"#ffcc00"}
  ];
  const index=buildFilamentFamilyIndex(rows);
  assert.notEqual(index.get("a").key,index.get("b").key);
  assert.notEqual(index.get("a").key,index.get("c").key);
});
