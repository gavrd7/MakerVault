import * as THREE from "three";
import {createPaintMesh} from "./slicerColourPainting.js";
import {validatePaintRegions} from "./slicerPaintRegions.js";
import {triangulatePaintPolygon} from "./slicerPaintSurfaceGeometry.js";

/** Paint v2 is rendered as non-destructive clipped geometry on top of the STL.
 * Never mutate printable model vertices or imply the resulting patch is slicer G-code.
 */
export function clearPaintRegionOverlay(mesh) {
  const overlay=mesh?.userData?.paintRegionOverlay;
  if(!overlay)return;
  mesh.remove(overlay);
  overlay.geometry.dispose();
  overlay.material.dispose();
  delete mesh.userData.paintRegionOverlay;
}
export function paintRegionsPreview(mesh,state,baseHex="#58b5e4") {
  if(!mesh?.geometry||!mesh?.material||Array.isArray(mesh.material))
    throw Error("Invalid v2 paint preview mesh.");
  if(!mesh.userData.paintMesh)mesh.userData.paintMesh=createPaintMesh(mesh.geometry);
  const palette=state.palette;
  if(!Array.isArray(palette)||palette.length>64)
    throw Error("Invalid painting palette.");
  validatePaintRegions(state,mesh.userData.paintMesh,palette.map((_,i)=>i));
  const positions=[],colours=[];
  // Ordered regions allow later edits to overlay earlier ones.
  for(const region of state.regions){
    const hex=palette[region.slot]?.color;
    if(!/^#[0-9a-f]{6}$/i.test(hex||""))
      throw Error("Invalid paint colour.");
    const colour=new THREE.Color(hex);
    for(const patch of region.patches)
      for(const tri of triangulatePaintPolygon(patch.polygon))
        for(const point of tri){
          positions.push(...point);
          colours.push(colour.r,colour.g,colour.b);
        }
  }
  clearPaintRegionOverlay(mesh);
  if(mesh.material.vertexColors){
    mesh.material.vertexColors=false;
    mesh.material.needsUpdate=true;
    mesh.geometry.deleteAttribute("color");
  }
  mesh.material.color.set(baseHex);
  if(!positions.length)return;
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute("color",new THREE.Float32BufferAttribute(colours,3));
  const material=new THREE.MeshBasicMaterial({
    vertexColors:true,side:THREE.DoubleSide,depthTest:true,depthWrite:false,
    polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2
  });
  const overlay=new THREE.Mesh(geometry,material);
  overlay.name="MakerVault v2 paint preview (not printable geometry)";
  overlay.raycast=()=>{}; // never intercept model selection or painting hits
  overlay.renderOrder=mesh.renderOrder+1;
  mesh.add(overlay);
  mesh.userData.paintRegionOverlay=overlay;
}
