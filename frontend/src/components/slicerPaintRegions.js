/** Persist exact clipped surface polygons in model-local coordinates, not face-wide colours.
 * Candidate face discovery and visibility filtering remain the caller's responsibility.
 * Native slicer export is NOT implemented by this representation.
 */
import {clipPaintTriangleDisc,clipPaintTriangleHeight,clipPaintPolygon,triangulatePaintPolygon} from "./slicerPaintSurfaceGeometry.js";
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
/** Subtract one convex paint patch from another in the same triangle plane.
 * Split only affected polygons, preserving untouched portions and colours.
 * This also implements a true eraser (rather than drawing base colour on top).
 */
function subtractPatch(subject,cutter){
  if(subject.length<3||cutter.length<3)return [subject];
  const sub=(a,b)=>a.map((v,i)=>v-b[i]);
  const cross=(a,b)=>[
    a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]
  ];
  const dot=(a,b)=>a.reduce((sum,v,i)=>sum+v*b[i],0);
  const n=cross(sub(cutter[1],cutter[0]),sub(cutter[2],cutter[0]));
  const normalLength=Math.hypot(...n);
  if(normalLength<1e-10)return [subject];
  const clip=(polygon,axis,offset)=>clipPaintPolygon(polygon,axis,offset);
  let remaining=subject;
  const outside=[];
  for(let i=0;i<cutter.length&&remaining.length>=3;i++){
    const a=cutter[i],b=cutter[(i+1)%cutter.length];
    const edge=sub(b,a);
    const outward=cross(edge,n).map(v=>v/normalLength);
    const offset=dot(outward,a);
    // Negative of the outside half-space is a fresh convex fragment.
    const piece=clip(remaining,outward.map(v=>-v),-offset);
    if(piece.length>=3&&triangulatePaintPolygon(piece).length)outside.push(piece);
    remaining=clip(remaining,outward,offset);
  }
  return outside;
}
export function appendPaintRegion(state,mesh,selection,slot){
  validatePaintRegions(state,mesh);
  guard(slot===null||(Number.isInteger(slot)&&slot>=0&&slot<64),
    "Invalid logical paint slot.");
  guard(Array.isArray(selection?.faces)&&selection.faces.length<=MAX_PER_EDIT,
    "Invalid surface selection.");
  const mode=selection.mode;
  guard(["disc","sphere","height","facet"].includes(mode),"Unsupported v2 region type.");
  if(mode==="disc")
    guard(valid3(selection.centre)&&valid3(selection.normal)&&
      Number.isFinite(selection.radiusMm)&&selection.radiusMm>0&&
      selection.radiusMm<=1000,"Invalid projected brush.");
  if(mode==="sphere")
    guard(valid3(selection.centre)&&Number.isFinite(selection.radiusMm)&&
      selection.radiusMm>0&&selection.radiusMm<=1000,"Invalid spherical brush.");
  if(mode==="height")
    guard(Number.isFinite(selection.minHeightMm)&&Number.isFinite(selection.maxHeightMm)&&
      selection.minHeightMm<=selection.maxHeightMm,"Invalid height range.");
  const seen=new Set();
  const additions=new Map();
  for(const face of selection.faces){
    guard(Number.isInteger(face)&&face>=0&&face<mesh.faceCount,
      "Invalid selected triangle.");
    if(seen.has(face))continue;
    seen.add(face);
    const triangle=mesh.triangle(face);
    let polygon;
    if(mode==="sphere"){
      const a=triangle[0],b=triangle[1],c=triangle[2];
      const u=b.map((v,i)=>v-a[i]),v=c.map((p,i)=>p-a[i]);
      const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],
        u[0]*v[1]-u[1]*v[0]];
      const length=Math.hypot(...n);
      if(length<1e-9)continue;
      const normal=n.map(x=>x/length);
      const distance=normal.reduce((sum,x,i)=>sum+x*(selection.centre[i]-a[i]),0);
      const radiusSquared=selection.radiusMm**2-distance**2;
      if(radiusSquared<=0)continue;
      const projected=selection.centre.map((x,i)=>x-distance*normal[i]);
      polygon=clipPaintTriangleDisc(triangle,projected,normal,Math.sqrt(radiusSquared));
    }else polygon=mode==="disc"?
      clipPaintTriangleDisc(triangle,selection.centre,selection.normal,selection.radiusMm):
      mode==="height"?
      clipPaintTriangleHeight(triangle,selection.minHeightMm,selection.maxHeightMm):
      triangle.map(p=>[...p]);
    if(polygon.length>=3&&triangulatePaintPolygon(polygon).length)
      additions.set(face,polygon);
  }
  if(!additions.size)return state;
  const regions=[];
  let touchedExisting=false;
  for(const region of state.regions){
    const patches=[];
    for(const patch of region.patches){
      const cutter=additions.get(patch.face);
      if(!cutter){patches.push(patch);continue;}
      const fragments=subtractPatch(patch.polygon,cutter);
      if(fragments.length!==1||fragments[0]!==patch.polygon)touchedExisting=true;
      for(const polygon of fragments)patches.push({face:patch.face,polygon});
    }
    if(patches.length)regions.push({...region,patches});
  }
  if(slot!==null)regions.push({slot,patches:[...additions].map(([face,polygon])=>({face,polygon}))});
  if(slot===null&&!touchedExisting)return state;
  const result={...state,regions};
  validatePaintRegions(result,mesh);
  return result;
}
/** Snapshot-friendly undo for additive region edits. */
export function removeLastPaintRegion(state,mesh){
  validatePaintRegions(state,mesh);
  return state.regions.length?{...state,regions:state.regions.slice(0,-1)}:state;
}
