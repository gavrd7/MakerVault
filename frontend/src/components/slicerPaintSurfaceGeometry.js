/**
 * Non-destructive surface painting geometry primitives.
 *
 * Pure, deterministic clipping for the future paint v2 overlay and shared
 * support-painting selector. Original STL triangles must remain unchanged.
 * A v1 face-index colour map cannot serialize the clipped boundaries; don't
 * display these as a persisted region until v2 draft validation exists.
 */
const EPS=1e-8;
const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const subtract=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const cross=(a,b)=>[
  a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]
];
const norm=a=>Math.sqrt(dot(a,a));
const unit=a=>{const n=norm(a);if(n<=EPS)throw Error("Invalid clipping direction.");return a.map(v=>v/n);};
const lerp=(a,b,t)=>a.map((x,i)=>x+(b[i]-x)*t);
const finite3=a=>Array.isArray(a)&&a.length===3&&a.every(Number.isFinite);

/** Sutherland–Hodgman convex polygon clipping against a half-space:
 * dot(normal, point) <= offset. Returns a NEW vertex list. */
export function clipPaintPolygon(polygon,normal,offset){
  if(!Array.isArray(polygon)||polygon.length>128||!polygon.every(finite3)||
     !finite3(normal)||!Number.isFinite(offset))throw Error("Invalid surface polygon.");
  if(polygon.length<3)return [];
  const out=[];
  let from=polygon[polygon.length-1];
  let dFrom=dot(normal,from)-offset;
  for(const to of polygon){
    const dTo=dot(normal,to)-offset;
    const fromIn=dFrom<=EPS,toIn=dTo<=EPS;
    if(fromIn!==toIn){
      const ratio=dFrom/(dFrom-dTo);
      out.push(lerp(from,to,Math.max(0,Math.min(1,ratio))));
    }
    if(toIn)out.push([...to]);
    from=to;dFrom=dTo;
  }
  // Remove consecutive coincident intersections to avoid zero-area faces.
  return out.filter((p,i,arr)=>norm(subtract(p,arr[(i+arr.length-1)%arr.length]))>EPS);
}
/** Exact intersection of an original triangle with the Z interval.
 * The returned polygon retains the original triangle's plane. */
export function clipPaintTriangleHeight(triangle,fromZ,toZ){
  if(!Array.isArray(triangle)||triangle.length!==3||!triangle.every(finite3)||
    !Number.isFinite(fromZ)||!Number.isFinite(toZ)||fromZ>toZ)
    throw Error("Invalid height paint region.");
  const lower=clipPaintPolygon(triangle,[0,0,-1],-fromZ);
  return lower.length>=3?clipPaintPolygon(lower,[0,0,1],toZ):[];
}
/** Clip a triangle to a circle projected onto the clicked surface plane.
 * Polygon approximates the circle to a configurable number of segments,
 * while the result stays exactly on the original triangle surface.
 * Caller must perform visibility/connectivity filtering first.
 */
export function clipPaintTriangleDisc(triangle,origin,normal,radius,{segments=48}={}){
  if(!Array.isArray(triangle)||triangle.length!==3||!triangle.every(finite3)||
     !finite3(origin)||!finite3(normal)||!Number.isFinite(radius)||
     radius<=0||radius>1000||!Number.isInteger(segments)||
     segments<12||segments>96)throw Error("Invalid paint disc.");
  const n=unit(normal);
  const helper=Math.abs(n[2])<.9?[0,0,1]:[0,1,0];
  const right=unit(cross(n,helper)),up=cross(n,right);
  // The halfspaces are tangents to an inscribed regular polygon.
  const inscribed=radius*Math.cos(Math.PI/segments);
  let vertices=triangle.map(v=>[...v]);
  for(let i=0;i<segments&&vertices.length>=3;i++){
    const angle=2*Math.PI*(i+.5)/segments;
    const direction=right.map((v,j)=>v*Math.cos(angle)+up[j]*Math.sin(angle));
    vertices=clipPaintPolygon(vertices,direction,dot(direction,origin)+inscribed);
  }
  return vertices;
}
/** Fan triangulation of a convex clipped polygon, skipping degenerate faces. */
export function triangulatePaintPolygon(vertices){
  if(!Array.isArray(vertices)||vertices.length<3||vertices.length>128)return [];
  const triangles=[];
  for(let i=1;i<vertices.length-1;i++){
    const tri=[vertices[0],vertices[i],vertices[i+1]];
    if(norm(cross(subtract(tri[1],tri[0]),subtract(tri[2],tri[0])))>EPS)
      triangles.push(tri.map(v=>[...v]));
  }
  return triangles;
}
