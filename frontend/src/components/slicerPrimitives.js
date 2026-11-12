/** Parametric printable primitives, shared by Add model and negative-volume editing. */
import * as THREE from "three";
import { SVGLoader } from "three/addons/loaders/SVGLoader.js";
import { FontLoader } from "three/addons/loaders/FontLoader.js";
import { TextGeometry } from "three/addons/geometries/TextGeometry.js";
import helvetikerRegular from "../assets/slicer-fonts/helvetiker_regular.typeface.json" with { type: "json" };
import helvetikerBold from "../assets/slicer-fonts/helvetiker_bold.typeface.json" with { type: "json" };
import optimerRegular from "../assets/slicer-fonts/optimer_regular.typeface.json" with { type: "json" };
import gentilisRegular from "../assets/slicer-fonts/gentilis_regular.typeface.json" with { type: "json" };

// Permissively licensed MgOpen-based typefaces shipped with three.js.
// The original block face remains available for backward compatibility.
export const TEXT_FONTS = [
  {id:"block",name:"Block · original"},
  {id:"sans",name:"Sans · regular"},
  {id:"sans-bold",name:"Sans · bold"},
  {id:"optimer",name:"Optimer · serif"},
  {id:"gentilis",name:"Gentilis · classic"},
];
const FONT_DATA = {"sans":helvetikerRegular,"sans-bold":helvetikerBold,
  "optimer":optimerRegular,"gentilis":gentilisRegular};
const FONT_LOADER = new FontLoader();
const PARSED_FONTS = new Map();

import { resultToStl } from "./slicerSolidOperations.js";

export const PRIMITIVE_TYPES = ["box","cylinder","sphere","cone","disc","torus"];
function finite(value,min,max,label) {
  const n=Number(value);
  if(!Number.isFinite(n)||n<min||n>max) throw new Error(label+" must be "+min+"–"+max+" mm.");
  return n;
}
export function createPrimitiveGeometry(options={}) {
  const type=options.primitiveType||"box";
  if(!PRIMITIVE_TYPES.includes(type)) throw new Error("Unsupported primitive shape.");
  const w=finite(options.width,0.5,500,"Width");
  const d=finite(options.depth,0.5,500,"Depth");
  const h=finite(options.height,0.5,500,"Height");
  let geometry;
  switch(type) {
    case "box":geometry=new THREE.BoxGeometry(w,d,h);break;
    case "cylinder":
      geometry=new THREE.CylinderGeometry(w/2,w/2,h,64);
      geometry.rotateX(Math.PI/2);
      // Orientation gives a cylinder standing on Z. Width is the diameter.
      geometry.scale(1,d/w,1);
      break;
    case "disc":
      geometry=new THREE.CylinderGeometry(w/2,w/2,h,64);
      geometry.rotateX(Math.PI/2);
      geometry.scale(1,d/w,1);
      break;
    case "cone":
      geometry=new THREE.CylinderGeometry(0,w/2,h,64);
      geometry.rotateX(Math.PI/2);
      geometry.scale(1,d/w,1);
      break;
    case "sphere":
      geometry=new THREE.SphereGeometry(1,48,32);
      geometry.scale(w/2,d/2,h/2);
      break;
    case "torus": {
      const radius=Math.min(w,d)/2-h/2;
      if(radius<=0.2)throw new Error("Torus ring width and depth must exceed its tube thickness.");
      geometry=new THREE.TorusGeometry(radius,h/2,20,64);
      geometry.scale(w/Math.min(w,d),d/Math.min(w,d),1);
      break;
    }
    default:throw new Error("Unsupported primitive.");
  }
  if(!geometry.getAttribute("normal"))geometry.computeVertexNormals();
  return geometry;
}
/** Create a locally centred solid with a bottom face at z=0 by default. */
export function createPrimitiveMesh(options={}, at=null) {
  const geometry=createPrimitiveGeometry(options);
  geometry.computeBoundingBox();
  const box=geometry.boundingBox;
  const centre=box.getCenter(new THREE.Vector3());
  geometry.translate(-centre.x,-centre.y,-box.min.z);
  const radians = ["rotation_x","rotation_y","rotation_z"].map(key =>
    finite(options[key] ?? 0,-360,360,key)*Math.PI/180);
  geometry.rotateX(radians[0]);geometry.rotateY(radians[1]);geometry.rotateZ(radians[2]);
  geometry.computeBoundingBox();
  const transformed=geometry.boundingBox;
  const centreAfter=transformed.getCenter(new THREE.Vector3());
  geometry.translate(-centreAfter.x,-centreAfter.y,-transformed.min.z);
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));
  const position=at || [0,0,0];
  mesh.position.set(...position);
  mesh.updateMatrixWorld(true);
  return mesh;
}
export function createPrimitiveStl(options={}) {
  const mesh=createPrimitiveMesh(options);
  try {
    // Bake geometry in the local STL; resulting instance is placed separately.
    return resultToStl(mesh);
  } finally {mesh.geometry.dispose();mesh.material.dispose();}
}

function normalizeBounds(geometry,width,depth,height) {
  geometry.computeBoundingBox();
  if (!geometry.boundingBox || geometry.boundingBox.isEmpty())
    throw new Error("Shape has no printable geometry.");
  const size=geometry.boundingBox.getSize(new THREE.Vector3());
  if (![size.x,size.y,size.z].every(v=>v>0)) throw new Error("Shape is missing thickness.");
  geometry.scale(width/size.x,depth/size.y,height/size.z);
  geometry.computeBoundingBox();
  const box=geometry.boundingBox;
  geometry.translate(-(box.min.x+box.max.x)/2,-(box.min.y+box.max.y)/2,-box.min.z);
  return geometry;
}
function applyPrintableRotation(geometry,options={}) {
  const radians=["rotation_x","rotation_y","rotation_z"].map(key=>
    finite(options[key]??0,-360,360,key)*Math.PI/180);
  geometry.rotateX(radians[0]);
  geometry.rotateY(radians[1]);
  geometry.rotateZ(radians[2]);
  geometry.computeBoundingBox();
  const box=geometry.boundingBox;
  geometry.translate(-(box.min.x+box.max.x)/2,
    -(box.min.y+box.max.y)/2,-box.min.z);
  return geometry;
}
// Original, minimal 5x7 geometric block alphabet. The bitmap is procedural
// geometry rather than a bundled font file or a network-loaded typeface.
const GLYPHS={
A:["01110","10001","10001","11111","10001","10001","10001"],
B:["11110","10001","10001","11110","10001","10001","11110"],
C:["01111","10000","10000","10000","10000","10000","01111"],
D:["11110","10001","10001","10001","10001","10001","11110"],
E:["11111","10000","10000","11110","10000","10000","11111"],
F:["11111","10000","10000","11110","10000","10000","10000"],
G:["01111","10000","10000","10111","10001","10001","01111"],
H:["10001","10001","10001","11111","10001","10001","10001"],
I:["11111","00100","00100","00100","00100","00100","11111"],
J:["00111","00010","00010","00010","10010","10010","01100"],
K:["10001","10010","10100","11000","10100","10010","10001"],
L:["10000","10000","10000","10000","10000","10000","11111"],
M:["10001","11011","10101","10101","10001","10001","10001"],
N:["10001","11001","10101","10011","10001","10001","10001"],
O:["01110","10001","10001","10001","10001","10001","01110"],
P:["11110","10001","10001","11110","10000","10000","10000"],
Q:["01110","10001","10001","10001","10101","10010","01101"],
R:["11110","10001","10001","11110","10100","10010","10001"],
S:["01111","10000","10000","01110","00001","00001","11110"],
T:["11111","00100","00100","00100","00100","00100","00100"],
U:["10001","10001","10001","10001","10001","10001","01110"],
V:["10001","10001","10001","10001","10001","01010","00100"],
W:["10001","10001","10001","10101","10101","10101","01010"],
X:["10001","10001","01010","00100","01010","10001","10001"],
Y:["10001","10001","01010","00100","00100","00100","00100"],
Z:["11111","00001","00010","00100","01000","10000","11111"],
"0":["01110","10011","10101","10101","11001","10001","01110"],
"1":["00100","01100","00100","00100","00100","00100","01110"],
"2":["01110","10001","00001","00010","00100","01000","11111"],
"3":["11110","00001","00001","00110","00001","00001","11110"],
"4":["00010","00110","01010","10010","11111","00010","00010"],
"5":["11111","10000","10000","11110","00001","00001","11110"],
"6":["01111","10000","10000","11110","10001","10001","01110"],
"7":["11111","00001","00010","00100","01000","01000","01000"],
"8":["01110","10001","10001","01110","10001","10001","01110"],
"9":["01110","10001","10001","01111","00001","00001","11110"],
"-":["00000","00000","00000","11111","00000","00000","00000"],
".":["00000","00000","00000","00000","00000","01100","01100"],
":":["00000","01100","01100","00000","01100","01100","00000"],
" ":["00000","00000","00000","00000","00000","00000","00000"],
};
function blockTextGeometry(value,height) {
  const upper=value.toUpperCase();
  const active=new Set();
  let cursor=0;
  for(const character of upper) {
    const rows=GLYPHS[character];
    if(!rows) throw new Error("Text supports A–Z, digits, spaces, periods, hyphens and colons.");
    rows.forEach((row,r)=>{for(let x=0;x<5;x++)
      if(row[x]==="1")active.add((cursor+x)+","+(6-r));});
    cursor+=6;
  }
  if(!active.size)throw new Error("Enter visible text to extrude.");
  // Bitmap glyph diagonals can touch at a single vertical edge, producing
  // four-face non-manifold junctions. Bridge those isolated diagonal contacts
  // before extrusion so every connected pixel cluster is a printable solid.
  // This is preferable to silently disabling the watertightness check.
  for(let pass=0;pass<8;pass++) {
    const bridges=new Set();
    for(const key of active) {
      const [x,y]=key.split(",").map(Number);
      for(const dy of [-1,1]) {
        const diagonal=(x+1)+","+(y+dy);
        const right=(x+1)+","+y;
        const vertical=x+","+(y+dy);
        if(active.has(diagonal) && !active.has(right) && !active.has(vertical))
          bridges.add(right);
      }
    }
    if(!bridges.size)break;
    bridges.forEach(key=>active.add(key));
  }
  if(active.size>950)throw new Error("Text is too complex for local extrusion.");
  const array=[];
  const quad=(a,b,c,d)=>{array.push(...a,...b,...c,...a,...c,...d);};
  for(const key of active) {
    const [x,y]=key.split(",").map(Number);
    const a=[x,y,0],b=[x+1,y,0],c=[x+1,y+1,0],d=[x,y+1,0];
    const e=[x,y,height],f=[x+1,y,height],g=[x+1,y+1,height],h=[x,y+1,height];
    quad(e,f,g,h);quad(d,c,b,a);
    if(!active.has(x+","+(y-1)))quad(a,b,f,e);
    if(!active.has((x+1)+","+y))quad(b,c,g,f);
    if(!active.has(x+","+(y+1)))quad(c,d,h,g);
    if(!active.has((x-1)+","+y))quad(d,a,e,h);
  }
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute(array,3));
  geometry.computeVertexNormals();
  return geometry;
}
export function createTextStl(options={}) {
  const value=String(options.text||"").trim().slice(0,40);
  if(!value)throw new Error("Enter text to create a model.");
  const width=finite(options.width,0.5,500,"Width");
  const depth=finite(options.depth,0.5,500,"Depth");
  const height=finite(options.height,0.5,100,"Thickness");
  const fontId=String(options.font||"block");
  if(fontId!=="block" && !FONT_DATA[fontId])
    throw new Error("Choose a supported text font.");
  let geometry;
  if(fontId==="block") {
    geometry=blockTextGeometry(value,height);
  } else {
    if(!PARSED_FONTS.has(fontId)) PARSED_FONTS.set(fontId,
      FONT_LOADER.parse(FONT_DATA[fontId]));
    geometry=new TextGeometry(value,{
      font:PARSED_FONTS.get(fontId),size:10,depth:height,
      curveSegments:8,bevelEnabled:false,
    });
  }
  normalizeBounds(geometry,width,depth,height);
  applyPrintableRotation(geometry,options);
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());
  try{return resultToStl(mesh,{allowTrustedFontSeams:fontId!=="block"});}
  finally{geometry.dispose();mesh.material.dispose();}
}
export function createSvgStl(options={}) {
  const xml=String(options.svgData||"");
  if (!xml || xml.length>500000 || !/^\s*<svg\b/i.test(xml) ||
    /<script\b|<foreignObject\b|\bon\w+\s*=|\bhref\s*=|url\s*\(/i.test(xml))
    throw new Error("Choose a small, self-contained SVG with no scripts or external references.");
  const width=finite(options.width,0.5,500,"Width");
  const depth=finite(options.depth,0.5,500,"Depth");
  const height=finite(options.height,0.5,100,"Thickness");
  const loader=new SVGLoader();
  const data=loader.parse(xml);
  const shapes=data.paths.flatMap(path=>path.toShapes(true));
  if (!shapes.length || shapes.length>80) throw new Error("SVG needs one to 80 closed filled shapes.");
  const geometry=new THREE.ExtrudeGeometry(shapes,{depth:height,steps:1,bevelEnabled:false,curveSegments:8});
  if (geometry.getAttribute("position").count>150000) {
    geometry.dispose();throw new Error("SVG outlines are too complex to extrude locally.");
  }
  geometry.scale(1,-1,1);
  normalizeBounds(geometry,width,depth,height);
  applyPrintableRotation(geometry,options);
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());
  try {return resultToStl(mesh);}
  finally {geometry.dispose();mesh.material.dispose();}
}
