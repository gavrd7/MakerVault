import test from "node:test";
import assert from "node:assert/strict";
import {separatePaintedPlates,restorePaintedPlates} from "../src/components/slicerPaintAssets.js";

test("large painting is stored separately and restored with exact original polygon precision", async()=>{
  const oldFetch=globalThis.fetch;
  const oldDocument=globalThis.document;
  try{
    globalThis.document={cookie:""};
    const polygons=Array.from({length:350},(_,face)=>({
      face,polygon:[[1.123456789,2.123456789,3],[1.4,2.7,3],[1.5,2.6,3]],
    }));
    const original=[{id:"plate-1",name:"Benchy",objects:[{
      instance_id:"one",asset_id:"mesh-one",x_mm:0,
      support_paint:{version:2,signature:"350:abc",regions:[{
        slot:0,patches:polygons,
      }]},
    }]}];
    let paintSaved;
    globalThis.fetch=async(path,init)=>{
      if(String(path).endsWith("/paint-assets/")){
        paintSaved=JSON.parse(init.body);
        return {ok:true,json:async()=>({asset_id:"immutable-asset-1"})};
      }
      if(String(path).includes("/paint-assets/immutable-asset-1/")){
        return {ok:true,json:async()=>({paint:paintSaved.paint})};
      }
      throw Error("Unexpected API path "+path);
    };
    const compact=await separatePaintedPlates(original);
    assert.equal(compact[0].objects[0].paint_asset_id,"immutable-asset-1");
    assert.equal(compact[0].objects[0].support_paint,undefined);
    assert.ok(JSON.stringify(compact).length < JSON.stringify(original).length/10);
    assert.deepEqual(paintSaved.paint,{"support_paint":original[0].objects[0].support_paint});
    const restored=await restorePaintedPlates(compact);
    assert.deepEqual(restored,original);
    assert.deepEqual(original[0].objects[0].support_paint.regions[0].patches,polygons);
  } finally {
    globalThis.fetch=oldFetch;
    globalThis.document=oldDocument;
  }
});

test("plain models and small edit masks do not add separate upload requests",async()=>{
  const oldFetch=globalThis.fetch;
  try{
    globalThis.fetch=async()=>{throw Error("Unexpected upload")};
    const plain=[{id:"plate-1",objects:[{instance_id:"first",asset_id:"mesh-one"}]}];
    assert.deepEqual(await separatePaintedPlates(plain),plain);
    const small=[{id:"plate-1",objects:[{
      instance_id:"first",asset_id:"mesh-one",
      variable_layer_profile:{version:1,bands:[{from_mm:3,to_mm:5,layer_mm:.12}]},
    }]}];
    assert.deepEqual(await separatePaintedPlates(small),small);
  } finally {globalThis.fetch=oldFetch;}
});
