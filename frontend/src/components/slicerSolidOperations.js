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

// Match native plate validation; complexity remains constrained by the STL byte cap.
export const CSG_MAX_INPUT_TRIANGLES = 500000;
export const CSG_MAX_OUTPUT_TRIANGLES = 500000;
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
      " input triangles, the current native slicer plate limit. The original is unchanged.");
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
  // Constrained triangulation reduces T-junction artefacts around round holes.
  e.useCDTClipping = true;
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
  const attr=geometry.getAttribute("position"), index=geometry.getIndex();
  const faces=triangles(geometry);
  if (faces>maxTriangles) throw new Error("CSG result is too complex to validate.");
  const vertices=new Map(),edges=new Map();
  function vertex(i) {
    const coords=[attr.getX(i),attr.getY(i),attr.getZ(i)];
    if (coords.some(v=>!Number.isFinite(v))) throw new Error("CSG produced invalid coordinates.");
    const point=coords.map(v=>Math.round(v/WELD));
    const key=point.join(",");
    vertices.set(key,point);
    return key;
  }
  for(let i=0;i<faces*3;i+=3) {
    const v=[0,1,2].map(n=>vertex(index?index.getX(i+n):i+n));
    // A nonzero-area triangle can collapse under 0.0001 mm validation
    // quantisation at near-coplanar CSG seams. It is already screened for
    // physical area in resultToStl; skip just this zero-length welded face
    // rather than failing an otherwise valid printable surface.
    if(new Set(v).size!==3) continue;
    for(const [a,b] of [[0,1],[1,2],[2,0]]) {
      const id=v[a]<v[b]?v[a]+"|"+v[b]:v[b]+"|"+v[a];
      const old=edges.get(id);
      if(old) old.count++;
      else edges.set(id,{a:v[a],b:v[b],count:1});
    }
  }
  const unmatched=[...edges.values()].filter(edge=>edge.count!==2);
  if(!unmatched.length) return;
  if(unmatched.length>20000)
    throw new Error("CSG has too many unmatched mesh edges for safe validation.");
  // CSG may subdivide one side of a watertight edge into multiple collinear
  // segments. Count coverage along the entire quantised line instead of
  // rejecting an otherwise closed T-junction at the original edge endpoints.
  const lines=new Map();
  function gcd(a,b) {a=Math.abs(a);b=Math.abs(b);while(b){const next=a%b;a=b;b=next;}return a;}
  for(const edge of unmatched) {
    const a=vertices.get(edge.a),b=vertices.get(edge.b);
    const d=b.map((value,i)=>value-a[i]);
    const divisor=gcd(gcd(d[0],d[1]),d[2]);
    if(!divisor) throw new Error("Zero-length edge in CSG result.");
    const unit=d.map(value=>value/divisor);
    const sign=unit.find(v=>v!==0)<0?-1:1;
    const dir=unit.map(v=>v*sign);
    const cross=[a[1]*dir[2]-a[2]*dir[1],a[2]*dir[0]-a[0]*dir[2],
      a[0]*dir[1]-a[1]*dir[0]];
    const key=dir.join(",")+"|"+cross.join(",");
    const t1=a.reduce((sum,value,i)=>sum+value*dir[i],0);
    const t2=b.reduce((sum,value,i)=>sum+value*dir[i],0);
    if(!lines.has(key))lines.set(key,[]);
    lines.get(key).push({start:Math.min(t1,t2),end:Math.max(t1,t2),count:edge.count});
  }
  for(const group of lines.values()) {
    const points=[...new Set(group.flatMap(v=>[v.start,v.end]))].sort((a,b)=>a-b);
    for(let i=0;i<points.length-1;i++) {
      const at=(points[i]+points[i+1])/2;
      const coverage=group.reduce((sum,v)=>sum+
        (v.start<at&&v.end>at?v.count:0),0);
      if(coverage!==2)
        throw new Error("Result is not a closed watertight solid. Try a simpler mesh or operation.");
    }
  }
}
/** Convert a world-space CSG result to a 3D-printable, AABB-centred binary STL. */
export function resultToStl(mesh, {allowOpenPreview=false,allowTrustedFontSeams=false}={}) {
  const source=mesh?.geometry;
  const attr=source?.getAttribute("position"),idx=source?.getIndex();
  if (!attr) throw new Error("Result has no mesh geometry.");
  const faceCount=triangles(source);
  const range=source.drawRange || {start:0,count:Infinity};
  const start=Math.max(0,range.start||0);
  const count=Math.min(faceCount*3-start,Number.isFinite(range.count)?range.count:faceCount*3);
  const position=new THREE.Vector3(),a=new THREE.Vector3(),b=new THREE.Vector3(),c=new THREE.Vector3();
  const ab=new THREE.Vector3(),ac=new THREE.Vector3();
  const clean=[];
  const get=(at,out)=>out.fromBufferAttribute(attr,idx?idx.getX(at):at);
  // CSG clipping commonly emits triangles with identical vertices or
  // near-zero area at coplanar seams. They carry no physical surface and
  // should be discarded before the actual watertightness validation.
  let discarded=0;
  for(let i=start;i+2<start+count;i+=3) {
    get(i,a);get(i+1,b);get(i+2,c);
    if(![a,b,c].every(v=>Number.isFinite(v.x)&&Number.isFinite(v.y)&&Number.isFinite(v.z)))
      throw new Error("CSG produced non-finite coordinates.");
    ab.subVectors(b,a);ac.subVectors(c,a);
    if(ab.cross(ac).lengthSq()<1e-14) { discarded++; continue; }
    clean.push(a.x,a.y,a.z,b.x,b.y,b.z,c.x,c.y,c.z);
    if(clean.length/9>CSG_MAX_OUTPUT_TRIANGLES ||
      84+clean.length/9*50>STL_MAX_BYTES)
      throw new Error("CSG output exceeds the native slicing mesh limit.");
  }
  if(!clean.length) throw new Error("The mesh operation produced no printable surface.");
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute(clean,3));
  try {
    let validationWarning="";
    let geometryAdvisory="";
    try {checkManifold(geometry,clean.length/9);}
    catch(error) {
      // An unsafe result may be shown as a temporary ghost, but never applied
      // or sent to native slicing. Other geometry failures still throw.
      const seamIssue=/watertight|unmatched mesh edges/i.test(error.message);
      if(allowTrustedFontSeams && seamIssue){
        // Bundled outline-font triangulation can generate T-junctions and
        // unpaired seams around narrow serif/counter contours. Permit STL
        // export for this generated-text path only; native slicers may
        // need to heal it. Never apply this tolerance to imported meshes.
        geometryAdvisory="Generated font outlines may require slicer repair.";
      } else if(allowOpenPreview && seamIssue){
        validationWarning="Open mesh edges detected; preview only.";
      } else throw error;
    }
    geometry.computeBoundingBox();
    const box=geometry.boundingBox,center=box.getCenter(new THREE.Vector3());
    const size=box.getSize(new THREE.Vector3());
    const offset=new THREE.Vector3(center.x,center.y,box.min.z);
    const faces=clean.length/9;
    const buffer=new ArrayBuffer(84+faces*50),view=new DataView(buffer);
    view.setUint32(80,faces,true);
    let cursor=84;
    const write=v=>{view.setFloat32(cursor,v.x,true);view.setFloat32(cursor+4,v.y,true);
      view.setFloat32(cursor+8,v.z,true);cursor+=12;};
    for(let i=0;i<clean.length;i+=9) {
      a.set(clean[i],clean[i+1],clean[i+2]).sub(offset);
      b.set(clean[i+3],clean[i+4],clean[i+5]).sub(offset);
      c.set(clean[i+6],clean[i+7],clean[i+8]).sub(offset);
      ab.subVectors(b,a);ac.subVectors(c,a);
      position.copy(ab.cross(ac)).normalize();
      write(position);write(a);write(b);write(c);cursor+=2;
    }
    return {buffer,triangles:faces,removedZeroAreaFaces:discarded,validationWarning,geometryAdvisory,
      x_mm:center.x,y_mm:center.y,z_mm:box.min.z,
      width:size.x,depth:size.y,height:size.z};
  } finally {geometry.dispose();}
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
      // Three.js cylinders are Y-aligned; turn the drill along build-plate Z.
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
      const axisScale=["x","y","z"].map(axis=>safeNumber(
        options["cavity_scale_"+axis]??100,20,150,"Cavity "+axis+" scale")/100);
      const angles=["x","y","z"].map(axis=>THREE.MathUtils.degToRad(safeNumber(
        options["cavity_rotation_"+axis]??0,-360,360,"Cavity "+axis+" rotation")));
      const offsets=["x","y","z"].map(axis=>safeNumber(
        options["cavity_"+axis+"_mm"]??0,-500,500,"Cavity "+axis+" offset"));
      scaled.translate(-mid.x,-mid.y,-mid.z);
      scaled.scale((size.x-2*wall)/size.x*axisScale[0],
        (size.y-2*wall)/size.y*axisScale[1],
        (size.z-2*wall)/size.z*axisScale[2]);
      scaled.rotateX(angles[0]);scaled.rotateY(angles[1]);scaled.rotateZ(angles[2]);
      scaled.translate(mid.x+offsets[0],mid.y+offsets[1],mid.z+offsets[2]);
      secondary=new Brush(scaled);
      secondary.updateMatrixWorld();
      outputs.push(run(first,secondary,SUBTRACTION));
    }
    return outputs.map(result=>resultToStl(result,{allowOpenPreview:!!options.allowOpenPreview}));
  } finally {
    first.geometry.dispose();
    secondary?.geometry.dispose();
    outputs.forEach(o=>o.geometry?.dispose());
  }
}
