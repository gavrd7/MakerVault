/** Parametric printable primitives, shared by Add model and negative-volume editing. */
import * as THREE from "three";
import { resultToStl } from "./slicerSolidOperations.js";

export const PRIMITIVE_TYPES = ["box","cylinder","sphere","cone","torus"];
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
