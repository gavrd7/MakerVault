/** Conservative surface-contact support check for the Move tool. */
import * as THREE from "three";
const TOL = 0.35;
function xyOverlap(a,b,margin=0) {
  return a.min.x < b.max.x-margin && a.max.x > b.min.x+margin &&
    a.min.y < b.max.y-margin && a.max.y > b.min.y+margin;
}
function contacts(top, below) {
  if (!xyOverlap(top.box,below.box) || Math.abs(top.box.min.z-below.box.max.z)>TOL) return false;
  const attr=top.mesh.geometry.getAttribute("position");
  if (!attr) return false;
  const ray=new THREE.Raycaster();
  ray.far=2*TOL+0.05;
  const p=new THREE.Vector3(), origin=new THREE.Vector3();
  const down=new THREE.Vector3(0,0,-1);
  top.mesh.updateMatrixWorld(true);
  const samples=[];
  const step=Math.max(1,Math.floor(attr.count/5000));
  for(let i=0;i<attr.count;i+=step) {
    p.fromBufferAttribute(attr,i).applyMatrix4(top.mesh.matrixWorld);
    if(Math.abs(p.z-top.box.min.z)<=TOL) samples.push(p.clone());
  }
  if(!samples.length) return false;
  const average=samples.reduce((sum,v)=>sum.add(v),new THREE.Vector3()).divideScalar(samples.length);
  samples.push(average);
  const stride=Math.max(1,Math.ceil(samples.length/48));
  for(let i=0;i<samples.length;i+=stride) {
    origin.copy(samples[i]);origin.z+=TOL;
    ray.set(origin,down);
    const hit=ray.intersectObject(below.mesh,false)[0];
    if(hit && Math.abs(hit.point.z-samples[i].z)<=TOL) return true;
  }
  return false;
}
/** Returns a strict verdict. Never infers physical support from box overlap. */
export function validateStackPlacement(objects, meshes, selectedId, bedX, bedY, allowIntersections = false) {
  const list=objects.map(row=>{
    const mesh=meshes.get(row.instance_id);
    if(!mesh) return null;
    mesh.updateMatrixWorld(true);
    return {row,mesh,box:new THREE.Box3().setFromObject(mesh)};
  });
  if(list.some(x=>!x)) return {valid:false,reason:"Model preview is still loading."};
  for(const a of list) {
    const b=a.box;
    if(b.isEmpty() || ![b.min.x,b.max.x,b.min.y,b.max.y,b.min.z,b.max.z].every(Number.isFinite))
      return {valid:false,reason:"Model dimensions are unavailable."};
    if(b.min.x < -bedX/2-0.01 || b.max.x > bedX/2+0.01 ||
       b.min.y < -bedY/2-0.01 || b.max.y > bedY/2+0.01 || b.min.z < -0.05)
      return {valid:false,reason:"Model extends outside the build plate."};
  }
  for(let i=0;i<list.length;i++)for(let j=i+1;j<list.length;j++){
    const a=list[i].box,b=list[j].box;
    if(!allowIntersections && xyOverlap(a,b,0.1) && a.min.z < b.max.z-0.1 && a.max.z > b.min.z+0.1)
      return {valid:false,reason:"Models intersect in three dimensions."};
  }
  const visited=new Set(),active=new Set();
  function reachesPlate(top) {
    const id=top.row.instance_id;
    if(visited.has(id)) return true;
    if(active.has(id)) return false;
    if(top.box.min.z<=TOL) {visited.add(id);return true;}
    active.add(id);
    const ok=list.some(below=>below!==top && below.box.min.z<top.box.min.z-TOL &&
      contacts(top,below) && reachesPlate(below));
    active.delete(id);
    if(ok) visited.add(id);
    return ok;
  }
  if(!list.every(reachesPlate))
    return {valid:false,reason:"Move rejected: no continuous contact path to the build plate."};
  return {valid:true,reason:""};
}
