import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { createPrimitiveStl,createPrimitiveMesh,createTextStl,PRIMITIVE_TYPES } from "../src/components/slicerPrimitives.js";
import { executeSolidOperation } from "../src/components/slicerSolidOperations.js";

test("all five parametric primitives produce valid binary STLs",()=>{
  for(const primitiveType of PRIMITIVE_TYPES) {
    const output=createPrimitiveStl({primitiveType,width:25,depth:25,height:12});
    assert.ok(output.buffer.byteLength>=84);
    assert.equal(new DataView(output.buffer).getUint32(80,true),output.triangles);
    assert.ok(output.triangles>=12,primitiveType);
    assert.ok(output.height>0,primitiveType);
  }
});
test("a negative box subtracts geometry without changing the original",()=>{
  const source=createPrimitiveMesh({primitiveType:"box",width:30,depth:30,height:30});
  const tool=createPrimitiveMesh({primitiveType:"box",width:10,depth:10,height:35},[0,0,0]);
  const before=source.geometry.getAttribute("position").array.slice();
  const result=executeSolidOperation("boolean",source,{booleanMode:"difference"},tool);
  assert.ok(result.length===1&&result[0].triangles>0);
  assert.deepEqual(Array.from(source.geometry.getAttribute("position").array),Array.from(before));
  source.geometry.dispose();tool.geometry.dispose();
});

test("Text creates printable geometry without external font downloads",()=>{
  const output=createTextStl({text:"MAKERVAULT 2026",width:100,depth:16,height:3});
  assert.ok(output.triangles>30);
  assert.equal(output.buffer.byteLength,84+output.triangles*50);
  assert.ok(output.height>2.9 && output.height<3.1);
});
test("Disc and rotation produce distinct real STL geometry",()=>{
  const shape=createPrimitiveStl({primitiveType:"disc",width:25,depth:25,height:4});
  assert.ok(shape.triangles>12);
  const rotated=createPrimitiveStl({primitiveType:"box",width:24,depth:12,height:8,rotation_z:45});
  assert.ok(rotated.width>24 && rotated.depth>12);
});
