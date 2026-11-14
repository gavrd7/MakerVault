/**
 * Preview-only approximation of OrcaSlicer 2.5.0's analytic RGB/HSV
 * FlushVolCalc fallback (not the optional learned FlushVolPredictor dataset).
 * Nozzle dead volume, material minimum purge, support handling and physical
 * bay-to-tool mapping are NOT inferable from colours. Do not send these
 * estimates to a printer or silently save as native values.
 */
const rgb = hex => {
  if (typeof hex !== "string" || !/^#[0-9a-f]{6}$/i.test(hex)) return null;
  return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
};
const hsv = ([r,g,b]) => {
  const mx=Math.max(r,g,b), mn=Math.min(r,g,b), dif=mx-mn;
  let h=0;
  if(dif>0){
    if(mx===r)h=((g-b)/dif+6)%6;
    else if(mx===g)h=(b-r)/dif+2;
    else h=(r-g)/dif+4;
    h*=60;
  }
  return [h,mx?dif/mx:0,mx];
};
const luminance=([r,g,b])=>r*.3+g*.59+b*.11;
export function estimateColourFlush(fromHex,toHex){
  const from=rgb(fromHex), to=rgb(toHex);
  if(!from||!to)return null;
  const [h1,s1,v1]=hsv(from),[h2,s2,v2]=hsv(to);
  const a=h1*Math.PI/180,b=h2*Math.PI/180;
  let hs=Math.min(1.2,Math.hypot(
    Math.cos(a)*s1*v1-Math.cos(b)*s2*v2,
    Math.sin(a)*s1*v1-Math.sin(b)*s2*v2
  ));
  const l1=luminance(from),l2=luminance(to);
  let brightness;
  if(l2>=l1)brightness=Math.pow(l2-l1,.7)*560;
  else{
    brightness=(l1-l2)*80;
    hs=Math.min(.67*v2+.33*v1,hs);
  }
  const colour=Math.max(60,Math.sqrt(
    (230*hs)**2+brightness**2+230*hs*brightness
  ));
  // No printer minimum is available here; the result is an unqualified
  // colour contribution, NOT a completed flushing volume.
  return Math.max(60,Math.trunc(colour));
}
const family=v=>{
  const m=String(v||"").toUpperCase();
  if(/PETG/.test(m))return "PETG";
  if(/PLA/.test(m))return "PLA";
  if(/ABS/.test(m))return "ABS";
  if(/ASA/.test(m))return "ASA";
  if(/TPU/.test(m))return "TPU";
  if(/PA|NYLON/.test(m))return "PA";
  return null;
};
export function slotMaterialCompatibility(from,to){
  const a=family(from?.material),b=family(to?.material);
  return !a||!b ? "unknown" : a===b ? "same" : "mixed";
}
export function estimateSlotFlush(from,to,{allowMixed=false}={}){
  const compatibility=slotMaterialCompatibility(from,to);
  if(compatibility==="unknown" || (compatibility==="mixed" && !allowMixed))return null;
  return estimateColourFlush(from?.color_hex,to?.color_hex);
}
export function multiplyFlushEstimate(base,multiplier=1){
  if(base==null||!Number.isFinite(multiplier)||multiplier<.1||multiplier>3)return null;
  return Math.min(20000,Math.max(0,Math.round(base*multiplier)));
}
