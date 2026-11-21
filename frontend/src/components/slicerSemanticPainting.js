/** Semantic surface paint, separate from colour or support tool slots.
 * v2 clipped polygons are editable and reversible; native Orca 3MF export
 * must be implemented and tested before any painted area affects G-code.
 */
import {createPaintRegions,appendPaintRegion,validatePaintRegions} from "./slicerPaintRegions.js";
export const SEMANTIC_PALETTES=Object.freeze({
  seam:Object.freeze([
    {color:"#e58a58",label:"Enforce seam"},
    {color:"#537ccf",label:"Block seam"},
  ]),
  fuzzy:Object.freeze([{color:"#c69cde",label:"Paint fuzzy skin"}]),
});
export const semanticField=kind=>kind==="seam"?"seam_paint":kind==="fuzzy"?"fuzzy_skin_paint":null;
export function createSemanticPaint(mesh){return createPaintRegions(mesh);}
export function validateSemanticPaint(state,mesh,kind){
  if(!SEMANTIC_PALETTES[kind])throw Error("Invalid semantic paint kind.");
  validatePaintRegions(state,mesh,SEMANTIC_PALETTES[kind].map((_,i)=>i));
  return state;
}
export function applySemanticPaint(state,mesh,kind,selection,slot) {
  validateSemanticPaint(state,mesh,kind);
  if(slot!==null && (!Number.isInteger(slot)||slot<0||slot>=SEMANTIC_PALETTES[kind].length))
    throw Error("Invalid semantic paint action.");
  return validateSemanticPaint(appendPaintRegion(state,mesh,selection,slot),mesh,kind);
}
