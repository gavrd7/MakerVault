import * as THREE from "three";
import {createPaintMesh} from "./slicerColourPainting.js";
import {validateSemanticPaint,SEMANTIC_PALETTES} from "./slicerSemanticPainting.js";
import {triangulatePaintPolygon} from "./slicerPaintSurfaceGeometry.js";

export function clearSemanticPaintPreview(mesh,kind){
  const key=kind==="seam"?"seamPaintOverlay":"fuzzyPaintOverlay";
  const overlay=mesh?.userData?.[key];
  if(!overlay)return;
  mesh.remove(overlay);
  overlay.geometry.dispose();
  overlay.material.dispose();
  delete mesh.userData[key];
}
export function semanticPaintPreview(mesh,state,kind){
  if(!mesh?.geometry)return;
  clearSemanticPaintPreview(mesh,kind);
  if(!state?.regions?.length)return;
  if(!mesh.userData.paintMesh)mesh.userData.paintMesh=createPaintMesh(mesh.geometry);
  validateSemanticPaint(state,mesh.userData.paintMesh,kind);
  const positions=[],colors=[];
  for(const region of state.regions){
    const color=new THREE.Color(SEMANTIC_PALETTES[kind][region.slot].color);
    for(const patch of region.patches)
      for(const triangle of triangulatePaintPolygon(patch.polygon))
        for(const vertex of triangle){
          positions.push(...vertex);
          colors.push(color.r,color.g,color.b);
        }
  }
  if(!positions.length)return;
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute("color",new THREE.Float32BufferAttribute(colors,3));
  // Fuzzy skin is a surface treatment, not a filament colour. Render a
  // screen-space stipple so the underlying model material stays visible and
  // the marked region is recognisable at any camera distance. No STL
  // displacement or printable geometry is created by this preview.
  const material=kind==="fuzzy" ? new THREE.ShaderMaterial({
    uniforms:{uColor:{value:new THREE.Color("#f6c76b")}},
    vertexShader:`
      void main() {
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);
      }
    `,
    fragmentShader:`
      uniform vec3 uColor;
      void main() {
        vec2 cell = mod(gl_FragCoord.xy, vec2(7.0));
        if(distance(cell,vec2(3.5)) > 1.6) discard;
        gl_FragColor = vec4(uColor,0.92);
      }
    `,
    side:THREE.DoubleSide,transparent:true,depthTest:true,depthWrite:false,
    polygonOffset:true,polygonOffsetFactor:-4,polygonOffsetUnits:-4,
  }) : new THREE.MeshBasicMaterial({
    vertexColors:true,side:THREE.DoubleSide,transparent:true,opacity:.83,
    depthTest:true,depthWrite:false,polygonOffset:true,
    polygonOffsetFactor:-4,polygonOffsetUnits:-4,
  });
  const overlay=new THREE.Mesh(geometry,material);
  overlay.name="MakerVault "+kind+" painting (draft preview)";
  overlay.raycast=()=>{};
  overlay.renderOrder=mesh.renderOrder+3;
  mesh.add(overlay);
  mesh.userData[kind==="seam"?"seamPaintOverlay":"fuzzyPaintOverlay"]=overlay;
}
