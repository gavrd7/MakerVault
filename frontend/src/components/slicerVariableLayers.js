/** MakerVault variable-layer draft bands in model-local build Z (mm).
 * Native Orca layer_height_profile conversion remains a separate, tested step.
 */
export function validateVariableLayerBands(bands) {
  if (!Array.isArray(bands)||bands.length>80)throw Error("Too many variable-layer bands.");
  const sorted=[...bands].sort((a,b)=>a.from_mm-b.from_mm);
  for(let i=0;i<sorted.length;i++){
    const b=sorted[i];
    if(!b || Object.keys(b).sort().join(",")!=="from_mm,layer_mm,to_mm" ||
       ![b.from_mm,b.to_mm,b.layer_mm].every(Number.isFinite) ||
       b.from_mm<0 || b.to_mm>1000 || b.to_mm<=b.from_mm ||
       b.layer_mm<0.05 || b.layer_mm>0.5)
      throw Error("Invalid variable-layer range or height.");
    if(i && b.from_mm<sorted[i-1].to_mm-1e-7)throw Error("Variable-layer ranges overlap.");
  }
  return sorted;
}
export function addVariableLayerBand(bands,from_mm,to_mm,layer_mm) {
  return validateVariableLayerBands([...bands,{from_mm,to_mm,layer_mm}]);
}
