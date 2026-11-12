/**
 * Bounded, non-destructive CSG operations for the MakerVault STL plate.
 * Uses unique world-space BufferGeometry so selected rotations and scales are
 * baked into results. The native slicer receives ordinary validated STLs.
 *
 * IMPORTANT: CSG requires closed two-manifold input. Hollow uses a centred,
 * anisotropically scaled inner copy; it is an APPROXIMATE cavity, not a
 * constant-distance normal offset. Caller must explain the limitation.
 */
import * as THREE from "three";
import { Brush, Evaluator, ADDITION, SUBTRACTION, INTERSECTION } from "three-bvh-csg";

export const CSG_MAX_INPUT_TRIANGLES = 80000;
export const CSG_MAX_OUTPUT_TRIANGLES = 350000;
const STL_MAX_BYTES = 32 * 1024 * 1024;
const WELD = 1e-4;

function safeNumber(value, min, max, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < min || number > max)
    throw new Error(label + " must be between " + min + " and " + max + ".");
  return number;
}
function triangles(geometry) {
  const attr = geometry.getAttribute("position");
  if (!attr) throw new Error("STL is missing vertex positions.");
  const count = geometry.index ? geometry.index.count : attr.count;
  if (count % 3 !== 0) throw new Error("STL has incomplete triangles.");
  return count / 3;
}
function normalizedGeometry(input) {
  const geometry = input.clone();
  for (const key of Object.keys(geometry.attributes)) if (!["position", "normal"].includes(key))
    geometry.deleteAttribute(key);
  if (!geometry.getAttribute("normal")) geometry.computeVertexNormals();
  geometry.clearGroups();
  geometry.setDrawRange(0, Infinity);
  return geometry;
}
function brushFor(mesh, maxTriangles = CSG_MAX_INPUT_TRIANGLES) {
  mesh.updateMatrixWorld(true);
  if (triangles(mesh.geometry) > maxTriangles)
    throw new Error("Mesh edit exceeds " + maxTriangles.toLocaleString() +
      " input triangles. This browser limit protects mobile memory; the original is unchanged.");
  const geometry = normalizedGeometry(mesh.geometry);
  geometry.applyMatrix4(mesh.matrixWorld);
  const brush = new Brush(geometry);
  brush.updateMatrixWorld();
  return brush;
}
function primitiveGeometry(geometry, at = [0,0,0]) {
  const material = new THREE.MeshBasicMaterial();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(...at);
  const brush = brushFor(mesh, 100000);
  geometry.dispose();
  material.dispose();
  return brush;
}
function evaluator() {
  const e = new Evaluator();
  e.attributes = ["position", "normal"];
  e.useGroups = false;
  return e;
}
function run(a, b, operation) {
  const engine = evaluator();
  const result = engine.evaluate(a, b, operation);
  if (!result?.geometry || !triangles(result.geometry))
    throw new Error("This operation produced an empty solid. The source has not changed.");
  return result;
}
function bounding(mesh) {
  const bounds = new THREE.Box3().setFromObject(mesh);
  if (bounds.isEmpty()) throw new Error("Model has empty geometry.");
  return bounds;
}
function checkManifold(geometry, maxTriangles) {
  const attr = geometry.getAttribute("position");
  const idx = geometry.getIndex();
  const faces = triangles(geometry);
  if (faces > maxTriangles)
    throw new Error("CSG result has too many triangles to validate or slice.");
  const edges = new Map();
  const key = i => [
    Math.round(attr.getX(i) / WELD),Math.round(attr.getY(i) / WELD),
    Math.round(attr.getZ(i) / WELD),
  ].join(",");
  for (let i = 0; i < faces * 3; i += 3) {
    const v = [0,1,2].map(k => key(idx ? idx.getX(i+k) : i+k));
    if (new Set(v).size !== 3) {
      throw new Error("CSG produced degenerate faces. The original model is unchanged.");
    }
    for (const [a,b] of [[0,1],[1,2],[2,0]]) {
      const id = v[a] < v[b] ? v[a] + "|" + v[b] : v[b] + "|" + v[a];
      edges.set(id,(edges.get(id)||0)+1);
    }
  }
  if ([...edges.values()].some(count=>count!==2))
    throw new Error("Result is not a closed watertight solid. Try a simpler mesh or operation.");
}
/** Convert a world-space CSG result to a 3D-printable, AABB-centred binary STL. */
export function resultToStl(mesh) {
  const g=mesh.geometry, attr=g?.getAttribute("position"), idx=g?.getIndex();
  if (!attr) throw new Error("Result has no mesh geometry.");
  const faceCount=triangles(g);
  const draw=g.drawRange || {start:0,count:Infinity};
  const start=Math.max(0,draw.start||0);
  const count=Math.min(faceCount*3-start,Number.isFinite(draw.count)?draw.count:faceCount*3);
  const len=Math.floor(count/3);
  if (len<1 || len>CSG_MAX_OUTPUT_TRIANGLES || 84+len*50>STL_MAX_BYTES)
    throw new Error("CSG output exceeds validated STL size limits.");
  const geometry=g.clone();
  const subset=geometry.index
    ? geometry.index.array.slice(start,start+len*3)
    : null;
  if (subset) geometry.setIndex(Array.from(subset));
  else {
    const output=geometry.getAttribute("position").array.slice(start*3,(start+len*3)*3);
    geometry.setAttribute("position",new THREE.BufferAttribute(new Float32Array(output),3));
  }
  checkManifold(geometry,len);
  geometry.computeBoundingBox();
  const box=geometry.boundingBox, center=box.getCenter(new THREE.Vector3());
  const size=box.getSize(new THREE.Vector3());
  const offset=new THREE.Vector3(center.x,center.y,box.min.z);
  const buffer=new ArrayBuffer(84+len*50), view=new DataView(buffer);
  view.setUint32(80,len,true);
  const a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3();
  const normal=new THREE.Vector3();
  let cursor=84;
  const write=v=>{view.setFloat32(cursor,v.x,true);view.setFloat32(cursor+4,v.y,true);
    view.setFloat32(cursor+8,v.z,true);cursor+=12;};
  for(let t=0;t<len;t++) {
    const at=component=>{
      const i=geometry.index?geometry.index.getX(t*3+component):t*3+component;
      return new THREE.Vector3().fromBufferAttribute(geometry.getAttribute("position"),i).sub(offset);
    };
    a.copy(at(0));b.copy(at(1));c.copy(at(2));
    normal.copy(b).sub(a).cross(new THREE.Vector3().copy(c).sub(a)).normalize();
    write(normal);write(a);write(b);write(c);cursor+=2;
  }
  geometry.dispose();
  return {buffer,triangles:len,x_mm:center.x,y_mm:center.y,
    z_mm:box.min.z,width:size.x,depth:size.y,height:size.z};
}
export function executeSolidOperation(kind, target, options={}, second=null) {
  if (!["hollow","drill","cut","boolean"].includes(kind))
    throw new Error("Unsupported mesh operation.");
  if (!target?.geometry) throw new Error("Select an STL model first.");
  const first=brushFor(target);
  const bounds=bounding(first);
  const size=bounds.getSize(new THREE.Vector3());
  const mid=bounds.getCenter(new THREE.Vector3());
  const outputs=[];
  let secondary=null;
  try {
    if (kind==="boolean") {
      if (!second || second===target) throw new Error("Select a different second model.");
      secondary=brushFor(second);
      const mode=options.booleanMode||"union";
      if (!["union","difference","intersection"].includes(mode))
        throw new Error("Choose a valid Boolean operation.");
      outputs.push(run(first,secondary,
        mode==="union"?ADDITION:mode==="difference"?SUBTRACTION:INTERSECTION));
    } else if(kind==="drill") {
      const radius=safeNumber(options.radius,0.2,Math.max(size.x,size.y),"Hole radius");
      const x=safeNumber(options.x_mm,-1000,1000,"X coordinate");
      const y=safeNumber(options.y_mm,-1000,1000,"Y coordinate");
      const height=size.z+4;
      const cylinder=new THREE.CylinderGeometry(radius,radius,height,48);
      cylinder.rotateX(Math.PI/2);
      secondary=primitiveGeometry(cylinder,[x,y,mid.z]);
      outputs.push(run(first,secondary,SUBTRACTION));
    } else if(kind==="cut") {
      const axis=options.cutAxis||"z";
      if (!["x","y","z"].includes(axis)) throw new Error("Choose a valid cut axis.");
      const height=safeNumber(options.cutHeight,bounds.min[axis]+0.01,
        bounds.max[axis]-0.01,"Cut "+axis.toUpperCase()+" position");
      const cover=Math.max(size.x,size.y,size.z)*4+20;
      const low=[mid.x,mid.y,mid.z], high=[mid.x,mid.y,mid.z];
      const index={x:0,y:1,z:2}[axis];
      low[index]=height-cover/2;
      high[index]=height+cover/2;
      const bottom=primitiveGeometry(new THREE.BoxGeometry(cover,cover,cover),low);
      const top=primitiveGeometry(new THREE.BoxGeometry(cover,cover,cover),high);
      secondary=bottom;
      const keep=options.keep||"both";
      if(["both","bottom"].includes(keep))outputs.push(run(first,bottom,INTERSECTION));
      if(["both","top"].includes(keep))outputs.push(run(first,top,INTERSECTION));
      top.geometry.dispose();
      if(!["both","bottom","top"].includes(keep)) throw new Error("Choose a valid cut result.");
    } else {
      const wall=safeNumber(options.wall,0.4,Math.min(size.x,size.y,size.z)/2-0.01,"Approximate wall");
      if([size.x,size.y,size.z].some(dim=>dim<=wall*2))
        throw new Error("This model is too thin for the chosen wall.");
      const scaled=normalizedGeometry(first.geometry);
      scaled.translate(-mid.x,-mid.y,-mid.z);
      scaled.scale((size.x-2*wall)/size.x,
        (size.y-2*wall)/size.y,(size.z-2*wall)/size.z);
      scaled.translate(mid.x,mid.y,mid.z);
      secondary=new Brush(scaled);
      secondary.updateMatrixWorld();
      outputs.push(run(first,secondary,SUBTRACTION));
    }
    return outputs.map(resultToStl);
  } finally {
    first.geometry.dispose();
    secondary?.geometry.dispose();
    outputs.forEach(o=>o.geometry?.dispose());
  }
}
