/** Private mask assets: the STL remains its own owned mesh asset.
 * Large brush polygons are saved once, never repeated in slice job JSON.
 */
import {apiFetch} from "../api";

export const PAINT_FIELDS=[
  "colour_paint","support_paint","seam_paint",
  "fuzzy_skin_paint","variable_layer_profile",
];

const uploaded=new Map();
const PAINT_ASSET_THRESHOLD=16*1024;

export async function separatePaintedPlates(plates) {
  const next=[];
  for(const plate of plates){
    const objects=[];
    for(const object of plate.objects||[]){
      const paint=Object.fromEntries(PAINT_FIELDS.filter(field=>
        Object.hasOwn(object,field) && object[field]!=null
      ).map(field=>[field,object[field]]));
      if(!Object.keys(paint).length){
        objects.push(object);
        continue;
      }
      const body=JSON.stringify(paint);
      if(body.length < PAINT_ASSET_THRESHOLD && !object.paint_asset_id){
        objects.push(object);
        continue;
      }
      if(!object.asset_id || String(object.asset_id).startsWith("local:"))
        throw new Error("The source STL must be uploaded before saving its painting.");
      // Reuse a completed asset for identical mesh/mask contents. This is an
      // optimisation only; the server checks the owner, mesh and digest again.
      const key=String(object.asset_id)+"|"+body;
      let assetId=uploaded.get(key);
      if(!assetId){
        const result=await apiFetch("/api/printing/slicer/paint-assets/",{
          method:"POST",compressJson:true,
          body:{mesh_asset_id:String(object.asset_id),paint},
        });
        assetId=result.asset_id;
        uploaded.set(key,assetId);
        if(uploaded.size>12)uploaded.delete(uploaded.keys().next().value);
      }
      const compact=Object.fromEntries(Object.entries(object).filter(
        ([key])=>!PAINT_FIELDS.includes(key)));
      objects.push({...compact,paint_asset_id:assetId});
    }
    next.push({...plate,objects});
  }
  return next;
}

export async function restorePaintedPlates(plates) {
  const next=[];
  const cache=new Map();
  for(const plate of plates){
    const objects=[];
    for(const model of plate.objects||[]){
      if(!model.paint_asset_id){objects.push(model);continue;}
      const key=model.paint_asset_id+"|"+model.asset_id;
      let paint=cache.get(key);
      if(!paint){
        const query=new URLSearchParams({mesh_asset_id:String(model.asset_id)});
        const response=await apiFetch("/api/printing/slicer/paint-assets/"+
          encodeURIComponent(model.paint_asset_id)+"/?"+query);
        paint=response.paint;
        cache.set(key,paint);
      }
      const {paint_asset_id,...plain}=model;
      objects.push({...plain,...paint});
    }
    next.push({...plate,objects});
  }
  return next;
}
