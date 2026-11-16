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
  const material=new THREE.MeshBasicMaterial({
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
