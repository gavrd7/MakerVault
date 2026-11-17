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

function BedIllustration({type}){
  const colors = {
    default:["#334155","#94a3b8"],
    cool:["#517895","#cce7f2"],
    engineering:["#424850","#c5cbd0"],
    high_temp:["#777b82","#efefed"],
    textured_pei:["#574f47","#e7b66b"],
    textured_cool:["#46687a","#a7d9e6"],
    supertack:["#625c45","#d4ba68"],
  };
  const [base,highlight]=colors[type]||colors.default;
  const texture=["textured_pei","textured_cool"].includes(type);
  const textureId="plate-"+type;
  return <svg viewBox="0 0 104 70" width="76" height="51" aria-hidden="true" focusable="false">
    <defs>
      <pattern id={textureId} width={texture?5:24} height={texture?5:24}
        patternUnits="userSpaceOnUse">
        {texture?<><circle cx="1.2" cy="1.2" r=".65" fill={highlight} opacity=".65"/>
          <circle cx="3.7" cy="3.7" r=".55" fill={highlight} opacity=".5"/></>:
          <path d="M 0 0 L 24 24 M 24 0 L 0 24" stroke={highlight} opacity=".12" strokeWidth=".7"/>}
      </pattern>
    </defs>
    <path d="M 9 49 L 75 13 L 96 30 L 29 65 Z" fill="#121820" opacity=".7"/>
    <path d="M 9 43 L 74 8 L 95 26 L 29 61 Z" fill={base} stroke={highlight} strokeWidth="1.4"/>
    <path d="M 9 43 L 74 8 L 95 26 L 29 61 Z" fill={"url(#"+textureId+")"}/>
    <path d="M 9 43 L 29 61 L 29 65 L 9 47 Z" fill="#202a31"/>
    <path d="M 29 61 L 95 26 L 95 30 L 29 65 Z" fill="#35414b"/>
    {type==="supertack"&&<path d="M 21 43 L 74 14 L 83 23 L 30 52 Z"
      stroke={highlight} strokeWidth="2" fill="none" opacity=".75"/>}
    {type==="engineering"&&<path d="M 24 40 L 73 14 M 30 48 L 79 22"
      stroke={highlight} strokeWidth=".7" opacity=".6"/>}
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
