/**
 * Filled cross sections for the interactive plate renderer only.
 * The source STL and native slicing geometry are never modified.
 * Reconstruct intersection loops and triangulate actual occupied regions;
 * nested loops are treated as holes instead of falsely filling cavities.
 */
import * as THREE from "three";

const EPS=1e-5;
const SNAP=1e-3;

function signedArea(points) {
  let area=0;
  for(let i=0;i<points.length;i++) {
    const a=points[i],b=points[(i+1)%points.length];
    area+=a.x*b.y-b.x*a.y;
  }
  return area/2;
}
function contains(polygon,point) {
  let inside=false;
  for(let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
    const a=polygon[i],b=polygon[j];
    if((a.y>point.y)!==(b.y>point.y) &&
      point.x<(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x)inside=!inside;
  }
  return inside;
}
function normalizedLoop(points) {
  const result=[];
  for(let i=0;i<points.length;i++) {
    const a=points[(i+points.length-1)%points.length],p=points[i],
      b=points[(i+1)%points.length];
    const cross=(p.x-a.x)*(b.y-p.y)-(p.y-a.y)*(b.x-p.x);
    if(Math.abs(cross)>1e-7)result.push(p);
  }
  return result.length>=3?result:[];
}
function pathFrom(points,ctor) {
  const path=new ctor();
  path.moveTo(points[0].x,points[0].y);
  for(let i=1;i<points.length;i++)path.lineTo(points[i].x,points[i].y);
  path.closePath();
  return path;
}

export function buildSectionCapGeometry(mesh,worldPlane,maxTriangles=150000) {
  const source=mesh?.geometry,attr=source?.getAttribute("position");
  if(!attr)return null;
  const index=source.getIndex();
  const vertexCount=index?index.count:attr.count;
  if(vertexCount/3>maxTriangles)return null;
  mesh.updateMatrixWorld(true);
  const normal=worldPlane.normal.clone().normalize();
  const origin=worldPlane.coplanarPoint(new THREE.Vector3());
  const reference=Math.abs(normal.z)>0.9
    ?new THREE.Vector3(0,1,0):new THREE.Vector3(0,0,1);
  const u=new THREE.Vector3().crossVectors(reference,normal).normalize();
  const v=new THREE.Vector3().crossVectors(normal,u).normalize();
  const nodes=new Map(),edges=[],unique=new Set();
  const world=[new THREE.Vector3(),new THREE.Vector3(),new THREE.Vector3()];
  const distance=[0,0,0];
  function addNode(p) {
    const projected=new THREE.Vector2(p.clone().sub(origin).dot(u),
      p.clone().sub(origin).dot(v));
    const key=Math.round(projected.x/SNAP)+":"+Math.round(projected.y/SNAP);
    if(!nodes.has(key))nodes.set(key,{point:projected,neighbors:new Set()});
    return key;
  }
  const temp=new THREE.Vector3();
  for(let offset=0;offset+2<vertexCount;offset+=3) {
    for(let j=0;j<3;j++) {
      const vertex=index?index.getX(offset+j):offset+j;
      world[j].fromBufferAttribute(attr,vertex).applyMatrix4(mesh.matrixWorld);
      distance[j]=worldPlane.distanceToPoint(world[j]);
    }
    if(distance.every(d=>d>EPS)||distance.every(d=>d< -EPS))continue;
    // Coplanar triangles do not contribute a contour segment.
    if(distance.every(d=>Math.abs(d)<=EPS))continue;
    const points=[];
    for(let j=0;j<3;j++) {
      const k=(j+1)%3,da=distance[j],db=distance[k];
      if(Math.abs(da)<=EPS)points.push(world[j].clone());
      if((da>EPS&&db< -EPS)||(da< -EPS&&db>EPS)) {
        const factor=da/(da-db);
        points.push(temp.copy(world[j]).lerp(world[k],factor).clone());
      }
    }
    const hits=[];
    for(const point of points)if(!hits.some(other=>other.distanceToSquared(point)<SNAP*SNAP))
      hits.push(point);
    if(hits.length<2)continue;
    // At a vertex exactly on the plane there can be three hit candidates.
    let best=[hits[0],hits[1]],max=best[0].distanceToSquared(best[1]);
    for(let i=0;i<hits.length;i++)for(let j=i+1;j<hits.length;j++) {
      const length=hits[i].distanceToSquared(hits[j]);
      if(length>max){max=length;best=[hits[i],hits[j]];}
    }
    if(max<SNAP*SNAP)continue;
    const a=addNode(best[0]),b=addNode(best[1]);
    if(a===b)continue;
    const id=a<b?a+"|"+b:b+"|"+a;
    if(unique.has(id))continue;
    unique.add(id);
    nodes.get(a).neighbors.add(b);
    nodes.get(b).neighbors.add(a);
    edges.push([a,b]);
  }
  if(!edges.length)return null;
  const remaining=new Set(unique),loops=[];
  for(const [start,next] of edges) {
    const edgeId=start<next?start+"|"+next:next+"|"+start;
    if(!remaining.has(edgeId))continue;
    const keys=[start];
    let previous=start,current=next,closed=false;
    for(let step=0;step<=edges.length;step++) {
      keys.push(current);
      const id=previous<current?previous+"|"+current:current+"|"+previous;
      remaining.delete(id);
      if(current===start){closed=true;break;}
      const neighbors=[...nodes.get(current).neighbors].filter(id=>id!==previous);
      if(neighbors.length!==1)break; // open/non-manifold cut; do not invent a cap
      previous=current;current=neighbors[0];
    }
    if(!closed)continue;
    keys.pop(); // closing endpoint
    const points=normalizedLoop(keys.map(key=>nodes.get(key).point));
    if(points.length>=3&&Math.abs(signedArea(points))>1e-5)
      loops.push({points,area:Math.abs(signedArea(points))});
  }
  if(!loops.length)return null;
  // Classify contours by enclosure. An outer polygon may contain a cavity,
  // which itself may contain another printable island.
  const classified=loops.map((loop,i)=>{
    const inside=loops.map((other,j)=>j!==i&&other.area>loop.area+1e-4&&
      contains(other.points,loop.points[0])?j:-1).filter(j=>j>=0);
    return {...loop,depth:inside.length,containers:inside};
  });
  const shapes=[];
  for(let i=0;i<classified.length;i++) {
    const loop=classified[i];
    if(loop.depth%2)continue;
    const shape=pathFrom(loop.points,THREE.Shape);
    for(const child of classified)if(child.depth===loop.depth+1&&
      child.containers.includes(i))shape.holes.push(pathFrom(child.points,THREE.Path));
    shapes.push(shape);
  }
  if(!shapes.length)return null;
  const geometry=new THREE.ShapeGeometry(shapes);
  const matrix=new THREE.Matrix4().makeBasis(u,v,normal);
  geometry.applyMatrix4(matrix);
  geometry.translate(origin.x,origin.y,origin.z);
  geometry.computeVertexNormals();
  return geometry;
}
