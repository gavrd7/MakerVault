import test from "node:test";
import assert from "node:assert/strict";
import {
 clipPaintTriangleHeight,clipPaintTriangleDisc,triangulatePaintPolygon
} from "../src/components/slicerPaintSurfaceGeometry.js";
const approx=(a,b)=>Math.abs(a-b)<1e-6;

test("height clipping creates exact Z boundaries instead of painting whole triangles",()=>{
  const tri=[[0,0,0],[12,0,20],[0,12,20]];
  const polygon=clipPaintTriangleHeight(tri,4,9);
  assert.ok(polygon.length>=3);
  assert.ok(polygon.every(p=>p[2]>=4-1e-7&&p[2]<=9+1e-7));
  assert.ok(polygon.some(p=>approx(p[2],4)));
  assert.ok(polygon.some(p=>approx(p[2],9)));
  assert.ok(triangulatePaintPolygon(polygon).length>=1);
  assert.deepEqual(clipPaintTriangleHeight(tri,21,22),[]);
});
test("brush clipping produces small circular patch on a large planar triangle",()=>{
  const tri=[[-50,-50,0],[50,-50,0],[0,50,0]];
  const poly=clipPaintTriangleDisc(tri,[0,0,0],[0,0,1],5);
  assert.ok(poly.length>=12,"clipped patch should have many curved boundary segments");
  assert.ok(poly.every(p=>p.every(Number.isFinite)));
  assert.ok(poly.every(p=>Math.hypot(p[0],p[1])<=5+1e-5));
  assert.ok(poly.every(p=>Math.abs(p[2])<1e-6));
  const sub=triangulatePaintPolygon(poly);
  assert.ok(sub.length>=10);
});
test("clipping validates untrusted geometry and limits polygon complexity",()=>{
  assert.throws(()=>clipPaintTriangleHeight([[0,0,0]],0,1));
  assert.throws(()=>clipPaintTriangleDisc([[0,0,0],[1,0,0],[0,1,0]],[0,0,0],[0,0,1],-2));
  assert.deepEqual(clipPaintTriangleDisc([[100,100,0],[102,100,0],[100,102,0]],
    [0,0,0],[0,0,1],2),[]);
});
