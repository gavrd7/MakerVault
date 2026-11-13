import * as THREE from "three";
import { createPaintMesh, validatePaint } from "./slicerColourPainting.js";
import { clearPaintRegionOverlay, paintRegionsPreview } from "./slicerPaintRegionsPreview.js";

/** Face-colour visualization is strictly a viewport preview, not slicer output. */
export function paintPreview(mesh, item, fallback = "#58b5e4") {
  if (!mesh?.geometry || !mesh?.material || Array.isArray(mesh.material)) return;
  const state = item?.colour_paint;
  const baseHex = item?.color || fallback;
  const previous = mesh.userData.paintPreviewCache;
  if (previous && previous.state === state && previous.baseHex === baseHex) return;
  if (state?.version === 2) {
    paintRegionsPreview(mesh, state, baseHex);
    mesh.userData.paintPreviewCache = {state, baseHex};
    return;
  }
  clearPaintRegionOverlay(mesh);
  const positions = mesh.geometry.getAttribute("position");
  if (!state || !Object.keys(state.faces || {}).length) {
    if (mesh.material.vertexColors) {
      mesh.material.vertexColors = false;
      mesh.material.needsUpdate = true;
      mesh.geometry.deleteAttribute("color");
    }
    mesh.material.color.set(baseHex);
    mesh.userData.paintPreviewCache = {state, baseHex};
    return;
  }
  if (!mesh.userData.paintMesh) mesh.userData.paintMesh = createPaintMesh(mesh.geometry);
  const palette = state.palette;
  if (!Array.isArray(palette) || palette.length > 64)
    throw new Error("Paint palette is invalid.");
  validatePaint(state, mesh.userData.paintMesh, palette.map((_, i) => i));
  // STLLoader yields non-indexed per-facet vertices. Refuse an indexed mesh
  // rather than bleeding colors onto adjacent triangles that share vertices.
  if (mesh.geometry.getIndex() || positions.count !== mesh.userData.paintMesh.faceCount * 3)
    throw new Error("This mesh cannot display independently coloured facets.");
  const base = new THREE.Color(baseHex);
  const colours = new Float32Array(positions.count * 3);
  for (let face = 0; face < mesh.userData.paintMesh.faceCount; face++) {
    const slot = state.faces[face];
    const hex = slot === undefined ? null : palette[slot]?.color;
    if (hex !== null && hex !== undefined && !/^#[\da-f]{6}$/i.test(hex))
      throw new Error("Invalid paint palette colour.");
    const color = hex ? new THREE.Color(hex) : base;
    for (let corner = 0; corner < 3; corner++) {
      const offset = (face * 3 + corner) * 3;
      colours[offset] = color.r; colours[offset + 1] = color.g; colours[offset + 2] = color.b;
    }
  }
  const existing = mesh.geometry.getAttribute("color");
  if (existing?.array?.length === colours.length) {
    existing.array.set(colours);
    existing.needsUpdate = true;
  } else {
    mesh.geometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
  }
  mesh.material.color.set("#ffffff");
  if (!mesh.material.vertexColors) {
    mesh.material.vertexColors = true;
    mesh.material.needsUpdate = true;
  }
  mesh.userData.paintPreviewCache = {state, baseHex};
}

/** Fast in-progress stroke update: only touched triangles are sent to the GPU.
 * Call paintPreview once when the stroke starts to initialise/validate colours.
 */
export function paintPreviewDelta(mesh, item, faces, slot, palette) {
  const attribute = mesh?.geometry?.getAttribute("color");
  if (!mesh?.material?.vertexColors || !attribute)
    throw new Error("Initialise painted mesh colours before applying a stroke.");
  const hex = slot === null ? (item?.color || "#58b5e4") : palette?.[slot]?.color;
  if (!/^#[0-9a-f]{6}$/i.test(hex || ""))
    throw new Error("Invalid colour paint swatch.");
  const color = new THREE.Color(hex);
  const max = mesh.geometry.getAttribute("position").count / 3;
  for (const face of faces) {
    if (!Number.isInteger(face) || face < 0 || face >= max)
      throw new Error("Invalid updated triangle index.");
    for (let corner=0;corner<3;corner++)
      attribute.setXYZ(face*3+corner,color.r,color.g,color.b);
  }
  attribute.needsUpdate=true;
}
