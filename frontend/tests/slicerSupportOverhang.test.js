import test from "node:test";
import assert from "node:assert/strict";
import {filterSupportOverhangFaces} from "../src/components/slicerSupportOverhang.js";

const identity=[1,0,0,0,1,0,0,0,1];
const normals=[
  [0,0,-1],       // downward-facing floor
  [0,0,1],        // upward-facing roof
  [0,1,0],        // vertical wall
  [0,Math.SQRT1_2,-Math.SQRT1_2], // 45 degree downward overhang
  [0,0.5,-Math.sqrt(0.75)],       // 60 degree downward overhang
];
test("overhang filter accepts downward support surfaces, not walls and rooftops",()=>{
  assert.deepEqual(filterSupportOverhangFaces([0,1,2,3,4],normals,identity,45),[0,4]);
  assert.deepEqual(filterSupportOverhangFaces([0,1,2,3,4],normals,identity,30),[0,3,4]);
  assert.deepEqual(filterSupportOverhangFaces([0,1,2,3,4],normals,identity,75),[0]);
});
test("overhang eligibility follows the printed orientation, not STL local Z",()=>{
  // 180 degree rotation around X makes local top faces point downward.
  const flipX=[1,0,0,0,-1,0,0,0,-1];
  assert.deepEqual(filterSupportOverhangFaces([0,1,2],normals,flipX,45),[1]);
  // 90 degree rotation around X puts local +/- Z faces on vertical walls.
  const rotateX=[1,0,0,0,0,1,0,-1,0];
  assert.deepEqual(filterSupportOverhangFaces([0,1,2],normals,rotateX,45),[2]);
});
test("malformed and degenerate normals cannot accidentally receive support paint",()=>{
  const n=[[0,0,0],[Infinity,0,-1],null,[0,0,-1]];
  assert.deepEqual(filterSupportOverhangFaces([0,1,2,3],n,identity,45),[3]);
  assert.throws(()=>filterSupportOverhangFaces([0],n,[1,0],45));
});
