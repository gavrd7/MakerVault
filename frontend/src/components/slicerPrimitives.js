/** Parametric printable primitives, shared by Add model and negative-volume editing. */
import * as THREE from "three";
import { FontLoader } from "three/addons/loaders/FontLoader.js";
import { TextGeometry } from "three/addons/geometries/TextGeometry.js";
import { SVGLoader } from "three/addons/loaders/SVGLoader.js";
import helvetiker from "three/examples/fonts/helvetiker_regular.typeface.json";
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

const font=new FontLoader().parse(helvetiker);
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
export function createTextStl(options={}) {
  const value=String(options.text||"").trim().slice(0,40);
  if (!value) throw new Error("Enter text to create a model.");
  const width=finite(options.width,0.5,500,"Width");
  const depth=finite(options.depth,0.5,500,"Depth");
  const height=finite(options.height,0.5,100,"Thickness");
  const geometry=new TextGeometry(value,{
    font,size:20,depth:height,curveSegments:8,bevelEnabled:false,
  });
  normalizeBounds(geometry,width,depth,height);
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());
  try {return resultToStl(mesh);}
  finally {geometry.dispose();mesh.material.dispose();}
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
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());
  try {return resultToStl(mesh);}
  finally {geometry.dispose();mesh.material.dispose();}
}
