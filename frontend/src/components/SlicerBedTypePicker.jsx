import React from "react";

/** Generic artwork for native Orca/Bambu-family build-plate categories.
 * The illustration is decorative, not the official manufacturer's artwork.
 * The calling editor supplies only plates enabled by the imported printer.
 */
const LABELS = {
  default:"Native / profile default",
  cool:"Smooth Cool Plate",
  engineering:"Engineering Plate",
  high_temp:"Smooth High Temp Plate",
  textured_pei:"Textured PEI Plate",
  textured_cool:"Textured Cool Plate",
  supertack:"SuperTack Plate",
};

export function BedIllustration({type,small=false}){
  // Orthographic top-down plate. Shared geometry echoes MakerVault's
  // fallback bed: square steel sheet, thin border, understated grid,
  // and a small integrated lower-edge brand mark (not a pull tab).
  const coating = {
    default: ["#293543", "#8196a5", "plain"],
    cool: ["#58758a", "#c5e5ef", "smooth"],
    engineering: ["#454b50", "#a9bac2", "satin"],
    high_temp: ["#72777b", "#e4e5e2", "smooth"],
    textured_pei: ["#645847", "#d5aa6c", "grain"],
    textured_cool: ["#4a6976", "#add2df", "grain"],
    supertack: ["#6e6445", "#dccb74", "adhesive"],
  };
  const [base,accent,finish]=coating[type]||coating.default;
  const id="bed-finish-"+type;
  return <svg viewBox="0 0 80 80" width={small?39:60} height={small?39:60}
    role="img" aria-label={type.replaceAll("_"," ")+" build plate illustration"}>
    <defs>
      <pattern id={id} width={finish==="grain"?4:12} height={finish==="grain"?4:12}
        patternUnits="userSpaceOnUse">
        {finish==="grain" ?
          <><circle cx="1.2" cy="1.2" r=".55" fill={accent} opacity=".75"/>
            <circle cx="3" cy="3" r=".35" fill={accent} opacity=".5"/></>
          : finish==="satin" ?
          <path d="M0 4 H12 M0 8 H12" stroke={accent} strokeWidth=".55" opacity=".2"/>
          : finish==="adhesive" ?
          <path d="M0 0 L12 12 M12 0 L0 12" stroke={accent} strokeWidth=".65" opacity=".17"/>
          : <path d="M0 0 H12 V12" stroke={accent} fill="none" strokeWidth=".6" opacity=".09"/>}
      </pattern>
    </defs>
    <rect x="4" y="4" width="72" height="72" rx="3" fill="#17212c" stroke="#5c7081" strokeWidth="1.4"/>
    <rect x="7" y="7" width="66" height="66" rx="1.8" fill={base} stroke={accent} strokeWidth="1.15"/>
    <rect x="7" y="7" width="66" height="66" rx="1.8" fill={"url(#"+id+")"}/>
    <g stroke={accent} strokeWidth=".6" opacity=".23">
      <path d="M23 8 V72 M40 8 V72 M57 8 V72 M8 23 H72 M8 40 H72 M8 57 H72"/>
    </g>
    <path d="M8 14 V8 H14 M66 8 H72 V14 M72 66 V72 H66 M14 72 H8 V66"
      stroke={accent} strokeWidth="1.35" fill="none"/>
    <path d="M23 62 H57" stroke={accent} opacity=".4" strokeWidth=".6"/>
    <text x="40" y="68.5" fill={accent} fontSize="5.2" fontWeight="600"
      letterSpacing=".65" textAnchor="middle">MAKERVAULT</text>
  </svg>;
}

export default function SlicerBedTypePicker({value,onChange,options,disabled=false,compact=false}){
  const entries=(options||[]).filter(([key])=>key in LABELS);
  return <div role="group" aria-label="Build plate type" className="slicerBedTypePicker"
    style={{display:"flex",flexWrap:compact?"nowrap":"wrap",gap:8,
      maxWidth:"100%",overflowX:compact?"auto":"visible",padding:"3px 2px 6px"}}>
    {entries.map(([key,label])=><button key={key} type="button" disabled={disabled}
      aria-pressed={value===key} title={label||LABELS[key]}
      onClick={()=>onChange(key)}
      style={{flex:"0 0 auto",minWidth:compact?168:182,maxWidth:compact?185:206,
        padding:"7px 9px",display:"flex",alignItems:"center",flexDirection:"row",gap:8,
        border:"1px solid "+(value===key?"#9685f5":"var(--border, #374151)"),
        borderRadius:10,background:value===key?"rgba(120,100,235,.12)":"transparent",
        color:"inherit",cursor:disabled?"not-allowed":"pointer",
        boxShadow:value===key?"inset 0 0 0 1px #9685f5":"none"}}>
      <BedIllustration type={key}/>
      <span style={{fontSize:11,lineHeight:1.3,textAlign:"left",flex:1}}>{label||LABELS[key]}</span>
    </button>)}
  </div>;
}
