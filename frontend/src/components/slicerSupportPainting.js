/**
 * Shared v2 clipped-surface selection for support painting.
 * Supports are semantic annotations, not colour/filament slots.
 * This representation is draft-only until a native engine adapter exports it.
 */
import {createPaintRegions, appendPaintRegion, validatePaintRegions} from "./slicerPaintRegions.js";

export const SUPPORT_ENFORCE = 0;
export const SUPPORT_BLOCK = 1;
export const SUPPORT_PALETTE = Object.freeze([
  {color:"#35b779",label:"Enforce supports"},
  {color:"#e56b6f",label:"Block supports"},
]);

export function createSupportPaint(mesh) {
  return createPaintRegions(mesh);
}
export function validateSupportPaint(state,mesh) {
  validatePaintRegions(state,mesh,[SUPPORT_ENFORCE,SUPPORT_BLOCK]);
  return state;
}
export function applySupportPaint(state,mesh,selection,action) {
  validateSupportPaint(state,mesh);
  if (![SUPPORT_ENFORCE,SUPPORT_BLOCK,null].includes(action))
    throw Error("Unknown support painting action.");
  const updated=appendPaintRegion(state,mesh,selection,action);
  return validateSupportPaint(updated,mesh);
}
export function supportPaintPatchCount(state) {
  if (!state?.regions) return 0;
  return state.regions.reduce((n,region)=>n+region.patches.length,0);
}
export function supportPaintPreviewState(state) {
  return {...state,palette:SUPPORT_PALETTE};
}
