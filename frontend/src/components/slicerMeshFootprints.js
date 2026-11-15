/**
 * Narrow phase for conservative plate AABB collision warnings.
 * Projects the actual printable surface triangles into XY, so openings
 * between separate solids in one STL are not treated as filled rectangles.
 *
 * null = too complex / indeterminate; callers must retain a conservative
 * warning rather than silently treating unknown geometry as collision-free.
 */
import * as THREE from "three";

const MAX_TRIANGLES=12000;
const EPS=1e-6;
const CELL=20;

function triangleCross(a,b,c){
  return (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
}
function trianglesFor(mesh) {
  const attr=mesh.geometry?.getAttribute("position");
  if(!attr)return null;
  const index=mesh.geometry.getIndex();
  const count=index?index.count:attr.count;
  if(count/3>MAX_TRIANGLES)return null;
  mesh.updateMatrixWorld(true);
  const tmp=new THREE.Vector3();
  const tris=[];
  for(let i=0;i+2<count;i+=3) {
    const points=[];
    for(let j=0;j<3;j++){
      const at=index?index.getX(i+j):i+j;
      tmp.fromBufferAttribute(attr,at).applyMatrix4(mesh.matrixWorld);
      points.push({x:tmp.x,y:tmp.y});
    }
    if(Math.abs(triangleCross(...points))<EPS)continue;
    const xs=points.map(p=>p.x),ys=points.map(p=>p.y);
    tris.push({points,minX:Math.min(...xs),maxX:Math.max(...xs),
      minY:Math.min(...ys),maxY:Math.max(...ys)});
  }
  return tris;
}
function overlapsTriangle(a,b){
  if(a.maxX<=b.minX+EPS||b.maxX<=a.minX+EPS||
     a.maxY<=b.minY+EPS||b.maxY<=a.minY+EPS)return false;
  for(const triangle of [a,b]){
    const points=triangle.points;
    for(let i=0;i<3;i++){
      const p=points[i],q=points[(i+1)%3];
      const axisX=q.y-p.y,axisY=p.x-q.x;
      let minA=Infinity,maxA=-Infinity,minB=Infinity,maxB=-Infinity;
      for(const v of a.points){
        const value=v.x*axisX+v.y*axisY;
        minA=Math.min(minA,value);maxA=Math.max(maxA,value);
      }
      for(const v of b.points){
        const value=v.x*axisX+v.y*axisY;
        minB=Math.min(minB,value);maxB=Math.max(maxB,value);
      }
      const tolerance=EPS*Math.hypot(axisX,axisY);
      if(maxA<=minB+tolerance||maxB<=minA+tolerance)return false;
    }
  }
  return true;
}
function range(min,max){
  return [Math.floor(min/CELL),Math.floor(max/CELL)];
}
function buildGrid(triangles){
  const grid=new Map();
  let references=0;
  for(let i=0;i<triangles.length;i++){
    const t=triangles[i],xs=range(t.minX,t.maxX),ys=range(t.minY,t.maxY);
    references+=(xs[1]-xs[0]+1)*(ys[1]-ys[0]+1);
    if(references>250000)return null;
    for(let x=xs[0];x<=xs[1];x++)for(let y=ys[0];y<=ys[1];y++) {
      const key=x+":"+y;
      if(!grid.has(key))grid.set(key,[]);
      grid.get(key).push(i);
    }
  }
  return grid;
}
export function meshesProjectivelyOverlapXY(a,b) {
  if(!a?.geometry||!b?.geometry)return null;
  const first=trianglesFor(a),second=trianglesFor(b);
  if(!first||!second)return null;
  if(!first.length||!second.length)return null;
  const small=first.length<second.length?first:second;
  const large=first.length<second.length?second:first;
  const grid=buildGrid(large);
  if(!grid)return null;
  for(const t of small){
    const xs=range(t.minX,t.maxX),ys=range(t.minY,t.maxY);
    const visited=new Set();
    for(let x=xs[0];x<=xs[1];x++)for(let y=ys[0];y<=ys[1];y++){
      for(const id of grid.get(x+":"+y)||[]){
        if(visited.has(id))continue;
        visited.add(id);
        if(overlapsTriangle(t,large[id]))return true;
      }
    }
  }
  return false;
}
