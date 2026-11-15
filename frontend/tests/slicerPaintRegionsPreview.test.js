import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import {createPaintMesh} from "../src/components/slicerColourPainting.js";
import {createPaintRegions,appendPaintRegion} from "../src/components/slicerPaintRegions.js";
import {paintPreview} from "../src/components/slicerColourPaintPreview.js";

test("v2 uses the same saved clipped polygons for preview without changing source geometry",()=>{
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute([
    -50,-50,0, 50,-50,0, 0,50,0
  ],3));
  const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial());
  const original=Array.from(geometry.getAttribute("position").array);
  const paintMesh=createPaintMesh(geometry);
  let paint=createPaintRegions(paintMesh);
  paint={...paint,palette:[{color:"#ff0000",label:"Red"}]};
  paint=appendPaintRegion(paint,paintMesh,{mode:"disc",faces:[0],
    centre:[0,0,0],normal:[0,0,1],radiusMm:5},0);
  paintPreview(mesh,{colour_paint:paint,color:"#777777"});
  const overlay=mesh.userData.paintRegionOverlay;
  assert.ok(overlay);
  assert.ok(overlay.geometry.getAttribute("position").count>12);
  assert.deepEqual(Array.from(geometry.getAttribute("position").array),original);
  assert.equal(mesh.children.length,1);
  paintPreview(mesh,{colour_paint:null,color:"#777777"});
  assert.equal(mesh.userData.paintRegionOverlay,undefined);
  assert.equal(mesh.children.length,0);
  geometry.dispose();
  mesh.material.dispose();
});
