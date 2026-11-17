import {plateEnvelope} from "./slicerPlateGeometry";

/** Preview-only footprint: Orca computes the exact depth after slicing.
 * XY are native Orca lower-left anchors in millimetres, not bed-centred model coordinates.
 */
export function towerFits(position, objects, dimensions, bedX, bedY, width=35, depth=35, clearance=4) {
  if (!position || ![position.x,position.y,bedX,bedY,width,depth].every(Number.isFinite))
    return false;
  const {x,y}=position;
  if (x<clearance || y<clearance || x+width>bedX-clearance || y+depth>bedY-clearance)
    return false;
  const left=x-bedX/2-clearance, right=x+width-bedX/2+clearance;
  const front=y-bedY/2-clearance, back=y+depth-bedY/2+clearance;
  return objects.every(item=>{
    const bounds=plateEnvelope(item,dimensions[item.instance_id]);
    return bounds && (right<=bounds.minX || left>=bounds.maxX ||
      back<=bounds.minY || front>=bounds.maxY);
  });
}

/** Deterministic central/rear preference, then progressively search the bed.
 * Incomplete mesh dimensions must not silently produce a colliding placement.
 */
export function autoPrimeTowerPosition(objects, dimensions, bedX, bedY, width=35, depth=35) {
  if (![bedX,bedY,width,depth].every(Number.isFinite) ||
      width+8>bedX || depth+8>bedY) return null;
  if (objects.some(item=>!plateEnvelope(item,dimensions[item.instance_id])))return null;
  const candidates=[];
  for(let y=bedY-depth-5;y>=5;y-=5)
    for(let x=5;x<=bedX-width-5;x+=5)
      candidates.push({x,y});
  candidates.sort((a,b)=> {
    // Prefer the back, but prefer the middle over edge-hugging placements.
    const score=point=>Math.abs(point.x+width/2-bedX/2)*1.4+
      (bedY-depth-5-point.y)*0.45;
    return score(a)-score(b) || b.y-a.y || a.x-b.x;
  });
  return candidates.find(candidate=>towerFits(candidate,objects,dimensions,bedX,bedY,width,depth))||null;
}
