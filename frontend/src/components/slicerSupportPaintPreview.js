import * as THREE from "three";
import {createPaintMesh} from "./slicerColourPainting.js";
import {validateSupportPaint,SUPPORT_PALETTE} from "./slicerSupportPainting.js";
import {triangulatePaintPolygon} from "./slicerPaintSurfaceGeometry.js";

/** Separate, non-raycastable support overlay. Never changes printable geometry. */
export function clearSupportPaintPreview(mesh) {
  const overlay=mesh?.userData?.supportPaintOverlay;
  if(!overlay)return;
  mesh.remove(overlay);
  overlay.geometry.dispose();
  overlay.material.dispose();
  delete mesh.userData.supportPaintOverlay;
}
export function supportPaintPreview(mesh,state) {
  if (!mesh?.geometry) return;
  clearSupportPaintPreview(mesh);
  if(!state?.regions?.length)return;
  if(!mesh.userData.paintMesh)mesh.userData.paintMesh=createPaintMesh(mesh.geometry);
  validateSupportPaint(state,mesh.userData.paintMesh);
  const positions=[],colors=[];
  for(const region of state.regions){
    const color=new THREE.Color(SUPPORT_PALETTE[region.slot].color);
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
    vertexColors:true,side:THREE.DoubleSide,transparent:true,opacity:.85,
    depthTest:true,depthWrite:false,polygonOffset:true,
    polygonOffsetFactor:-3,polygonOffsetUnits:-3,
  });
  const overlay=new THREE.Mesh(geometry,material);
  overlay.name="MakerVault support annotations (preview only)";
  overlay.raycast=()=>{};
  overlay.renderOrder=mesh.renderOrder+2;
  mesh.add(overlay);
  mesh.userData.supportPaintOverlay=overlay;
}
