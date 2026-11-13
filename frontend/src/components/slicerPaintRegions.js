/** Persist exact clipped surface polygons in model-local coordinates, not face-wide colours.
 * Candidate face discovery and visibility filtering remain the caller's responsibility.
 * Native slicer export is NOT implemented by this representation.
 */
import {clipPaintTriangleDisc,clipPaintTriangleHeight} from "./slicerPaintSurfaceGeometry.js";
const valid3=p=>Array.isArray(p)&&p.length===3&&p.every(Number.isFinite);
const guard=(ok,message)=>{if(!ok)throw Error(message);};
const MAX_REGIONS=4096,MAX_PATCHES=500000,MAX_PER_EDIT=100000;
export function createPaintRegions(mesh){
  guard(typeof mesh?.signature==="string"&&mesh.signature.length>0&&
    Number.isInteger(mesh.faceCount)&&mesh.faceCount>0&&typeof mesh.triangle==="function",
    "Invalid painting mesh.");
  return {version:2,signature:mesh.signature,regions:[]};
}
export function validatePaintRegions(state,mesh,allowedSlots=null){
  guard(state?.version===2&&state.signature===mesh?.signature&&
    Array.isArray(state.regions)&&state.regions.length<=MAX_REGIONS,
    "Invalid or stale v2 painted regions.");
  guard(Number.isInteger(mesh.faceCount)&&mesh.faceCount>0,"Invalid painting mesh.");
  const allowed=allowedSlots===null?null:new Set(allowedSlots);
  let count=0;
  for(const region of state.regions){
    guard(Number.isInteger(region?.slot)&&region.slot>=0&&region.slot<64&&
      (!allowed||allowed.has(region.slot)),"Invalid painted-region slot.");
    guard(Array.isArray(region.patches)&&region.patches.length>0&&
      region.patches.length<=MAX_PER_EDIT,"Invalid painted-region patches.");
    count+=region.patches.length;
    guard(count<=MAX_PATCHES,"Too many painted surface patches.");
    for(const patch of region.patches){
      guard(Number.isInteger(patch?.face)&&patch.face>=0&&patch.face<mesh.faceCount&&
        Array.isArray(patch.polygon)&&patch.polygon.length>=3&&
        patch.polygon.length<=128&&patch.polygon.every(valid3),
        "Invalid painted surface polygon.");
    }
  }
  return state;
}
export function appendPaintRegion(state,mesh,selection,slot){
  validatePaintRegions(state,mesh);
  guard(Number.isInteger(slot)&&slot>=0&&slot<64,"Invalid logical paint slot.");
  guard(Array.isArray(selection?.faces)&&selection.faces.length<=MAX_PER_EDIT,
    "Invalid surface selection.");
  guard(state.regions.length<MAX_REGIONS,"Too many paint edits.");
  const mode=selection.mode;
  guard(mode==="disc"||mode==="height","Unsupported v2 region type.");
  if(mode==="disc")
    guard(valid3(selection.centre)&&valid3(selection.normal)&&
      Number.isFinite(selection.radiusMm)&&selection.radiusMm>0&&
      selection.radiusMm<=1000,"Invalid projected brush.");
  else
    guard(Number.isFinite(selection.minHeightMm)&&Number.isFinite(selection.maxHeightMm)&&
      selection.minHeightMm<=selection.maxHeightMm,"Invalid height range.");
  const seen=new Set(),patches=[];
  for(const face of selection.faces){
    guard(Number.isInteger(face)&&face>=0&&face<mesh.faceCount,
      "Invalid selected triangle.");
    if(seen.has(face))continue;
    seen.add(face);
    const triangle=mesh.triangle(face);
    const polygon=mode==="disc"?
      clipPaintTriangleDisc(triangle,selection.centre,selection.normal,selection.radiusMm):
      clipPaintTriangleHeight(triangle,selection.minHeightMm,selection.maxHeightMm);
    if(polygon.length>=3)patches.push({face,polygon:polygon.map(p=>[...p])});
  }
  if(!patches.length)return state;
  return {...state,regions:[...state.regions,{slot,patches}]};
}
/** Snapshot-friendly undo for additive region edits. */
export function removeLastPaintRegion(state,mesh){
  validatePaintRegions(state,mesh);
  return state.regions.length?{...state,regions:state.regions.slice(0,-1)}:state;
}
