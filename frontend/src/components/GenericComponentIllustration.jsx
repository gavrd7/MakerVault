import React from "react";
import { componentIllustrationLabel } from "./componentIllustrations";

export default function GenericComponentIllustration({ kind = "component" }) {
  const ink = "#264653", metal = "#718096", body = "#dce7eb", accent = "#e9a94b";
  const wire = (x1, y1, x2, y2) => <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={metal} strokeWidth="3" strokeLinecap="round" />;
  const rect = (x, y, w, h, fill = body, rx = 3) => <rect x={x} y={y} width={w} height={h} rx={rx} fill={fill} stroke={ink} strokeWidth="1.5" />;
  let shape;
  switch (kind) {
    case "resistor": shape = <>{wire(5,32,20,32)}{wire(76,32,91,32)}{rect(20,23,56,18,"#dfc6a3",7)}{[33,44,55,66].map((x,i)=><rect key={x} x={x} y="24" width="4" height="16" fill={["#92400e","#1d4ed8","#92400e","#b08d25"][i]} />)}</>;break;
    case "capacitor": shape = <>{wire(30,40,30,59)}{wire(64,40,64,59)}{rect(24,13,46,29,"#d69b62",6)}{rect(26,15,42,8,"#e9c69d",3)}</>;break;
    case "electrolytic-capacitor": shape = <>{wire(38,45,38,60)}{wire(58,45,58,60)}{rect(32,9,32,39,"#314457",7)}{rect(33,9,30,7,"#9caeb6",4)}{rect(54,17,5,27,"#abbec8",1)}</>;break;
    case "toggle-switch": shape = <>{wire(22,48,22,58)}{wire(72,48,72,58)}{rect(13,35,68,16,"#83949e",4)}<line x1="47" y1="36" x2="35" y2="10" stroke={ink} strokeWidth="7" strokeLinecap="round"/><circle cx="35" cy="10" r="7" fill={accent} stroke={ink}/></>;break;
    case "rocker-switch": shape = <>{rect(17,12,62,40,ink,8)}<path d="M25 22 L69 17 L69 40 L25 44 Z" fill="#475b69" stroke="#b5cad5" strokeWidth="2"/><path d="M48 24 v11" stroke="#e9a94b" strokeWidth="3"/></>;break;
    case "slide-switch": shape = <>{rect(13,22,70,28,"#889aa5",4)}{rect(20,28,56,16,"#344956",2)}{rect(41,14,17,30,accent,3)}{wire(24,50,24,58)}{wire(72,50,72,58)}</>;break;
    case "dip-switch": shape = <>{rect(18,12,60,43,"#a83c30",4)}{[0,1,2,3].map(i=><g key={i}>{rect(25+i*13,20,9,25,"#fafafa",1)}{rect(26+i*13,24+(i%2)*9,7,11,"#263947",1)}</g>)}</>;break;
    case "rotary-switch": shape = <>{rect(16,17,64,39,"#526b78",8)}<circle cx="48" cy="35" r="18" fill="#dce7eb" stroke={ink} strokeWidth="2"/><path d="M48 35 L57 20" stroke={ink} strokeWidth="5" strokeLinecap="round"/>{[24,48,72].map(x=><circle key={x} cx={x} cy="13" r="2" fill={accent}/>)}</>;break;
    case "button": shape = <>{rect(19,27,58,27,"#455966",5)}{rect(31,15,34,22,accent,5)}{wire(25,54,25,60)}{wire(71,54,71,60)}</>;break;
    case "switch": shape = <>{wire(14,42,32,42)}{wire(67,42,83,42)}<circle cx="32" cy="42" r="4" fill={ink}/><circle cx="67" cy="42" r="4" fill={ink}/><path d="M32 42 L63 22" stroke={ink} strokeWidth="4" strokeLinecap="round"/></>;break;
    case "potentiometer": shape = <>{rect(17,26,62,26,"#4b7c76",5)}<circle cx="48" cy="28" r="18" fill="#9cadb4" stroke={ink} strokeWidth="2"/><path d="M48 28 L57 17" stroke={ink} strokeWidth="3"/>{[30,48,66].map(x=>wire(x,52,x,60))}</>;break;
    case "diode": shape = <>{wire(10,32,33,32)}{wire(62,32,86,32)}{rect(33,23,29,18,"#a94b4b",6)}{rect(53,24,5,16,"#ded9cf",1)}</>;break;
    case "transistor": shape = <>{rect(30,9,36,39,ink,6)}{rect(33,12,30,27,"#455d6b",3)}{[36,48,60].map(x=>wire(x,48,x,60))}</>;break;
    case "connector": shape = <>{rect(16,16,64,35,"#f1f4f5",4)}{[28,41,54,67].map(x=><g key={x}>{rect(x-4,25,8,14,metal,1)}{wire(x,51,x,59)}</g>)}</>;break;
    case "led": shape = <>{wire(39,44,39,60)}{wire(57,44,57,60)}<path d="M30 37 a18 18 0 0 1 36 0 v9 H30 Z" fill="#e56a58" stroke={ink} strokeWidth="2"/><path d="M53 16 L60 7 M65 25 L77 19" stroke={accent} strokeWidth="3"/></>;break;
    case "relay": shape = <>{rect(18,14,60,39,"#437ea0",4)}{rect(25,21,46,23,"#5b91b0",2)}{[27,68].map(x=>wire(x,53,x,61))}</>;break;
    default: shape = <>{rect(27,12,42,40,"#4a6977",5)}{[20,33,46,59,72].map(x=><g key={x}>{wire(24,x,16,x)}{wire(72,x,80,x)}</g>)}<circle cx="48" cy="32" r="8" fill={accent}/></>;
  }
  return <svg viewBox="0 0 96 64" width="100%" height="100%" role="img" aria-label={componentIllustrationLabel(kind) + " generic illustration"} xmlns="http://www.w3.org/2000/svg">{shape}</svg>;
}
