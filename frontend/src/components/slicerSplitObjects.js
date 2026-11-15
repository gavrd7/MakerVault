/**
 * Split an STL preview into edge/vertex-connected triangle components.
 * Geometry is welded by coordinates (STL is normally non-indexed); source
 * orientation and scale are baked into independent, bed-resting STL files.
 * This is NOT a plane cut and cannot split touching/overlapping solids.
 */
import * as THREE from "three";

// Match the current native 3MF plate triangle ceiling. This cap also prevents
// unbounded geometry allocations on mobile browsers.
const MAX_TRIANGLES = 500000;
const WELD_MM = 0.0001;
const MAX_STL_BYTES = 32 * 1024 * 1024;

export function splitDisconnectedMesh(mesh, maxParts = 12) {
  const position = mesh?.geometry?.getAttribute("position");
  const index = mesh?.geometry?.getIndex();
  const vertexCount = index ? index.count : (position?.count || 0);
  const triangleCount = vertexCount / 3;
  if (!position || !Number.isInteger(triangleCount) || triangleCount < 1)
    throw new Error("The selected model has no valid triangles.");
  if (triangleCount > MAX_TRIANGLES)
    throw new Error("This STL exceeds the current 500,000-triangle slicing limit. Split requires a smaller mesh or a higher validated native export limit.");
  const parent = new Int32Array(triangleCount);
  for (let i = 0; i < triangleCount; i++) parent[i] = i;
  const find = id => {
    while (parent[id] !== id) {
      parent[id] = parent[parent[id]];
      id = parent[id];
    }
    return id;
  };
  const join = (a, b) => {
    a = find(a); b = find(b);
    if (a !== b) parent[Math.max(a, b)] = Math.min(a, b);
  };
  const vertexOwner = new Map();
  const vertex = n => {
    const v = index ? index.getX(n) : n;
    return [position.getX(v), position.getY(v), position.getZ(v)];
  };
  const key = coords => coords.map(n => Math.round(n / WELD_MM)).join(":");
  for (let face = 0; face < triangleCount; face++) {
    for (let corner = 0; corner < 3; corner++) {
      const coordinates = vertex(face * 3 + corner);
      if (!coordinates.every(Number.isFinite))
        throw new Error("This STL contains invalid coordinates.");
      const id = key(coordinates);
      const owner = vertexOwner.get(id);
      if (owner === undefined) vertexOwner.set(id, face);
      else join(face, owner);
    }
  }
  const groups = new Map();
  for (let face = 0; face < triangleCount; face++) {
    const root = find(face);
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root).push(face);
  }
  if (groups.size <= 1)
    return { parts: [], message: "The selected STL is one connected mesh. No separate objects were found." };
  if (groups.size > maxParts)
    throw new Error("This STL has " + groups.size + " separate pieces, exceeding the available " +
      maxParts + " model slots. Remove other objects or use an external mesh editor.");
  mesh.updateMatrixWorld(true);
  const matrix = mesh.matrixWorld.clone();
  const parts = [...groups.values()].sort((a, b) => b.length - a.length).map((faces, partIndex) => {
    // Two bounded passes avoid retaining three THREE.Vector3 objects per
    // triangle. Even high-detail 500k-face STLs stay well below the memory
    // footprint of building a second full in-memory mesh.
    const min = new THREE.Vector3(Infinity, Infinity, Infinity);
    const max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
    const transformed = new THREE.Vector3();
    for (const face of faces) {
      for (let corner = 0; corner < 3; corner++) {
        const coords = vertex(face * 3 + corner);
        transformed.set(...coords).applyMatrix4(matrix);
        min.min(transformed); max.max(transformed);
      }
    }
    const centre = min.clone().add(max).multiplyScalar(0.5);
    const offset = new THREE.Vector3(centre.x, centre.y, min.z);
    const size = max.clone().sub(min);
    const bytes = 84 + faces.length * 50;
    if (bytes > MAX_STL_BYTES)
      throw new Error("Split object " + (partIndex + 1) + " exceeds the 32 MiB STL upload limit.");
    const buffer = new ArrayBuffer(bytes);
    const view = new DataView(buffer);
    view.setUint32(80, faces.length, true);
    let cursor = 84;
    const writeVector = v => {
      view.setFloat32(cursor, v.x, true);
      view.setFloat32(cursor + 4, v.y, true);
      view.setFloat32(cursor + 8, v.z, true);
      cursor += 12;
    };
    for (const face of faces) {
      const corners = [0, 1, 2].map(corner =>
        transformed.set(...vertex(face * 3 + corner)).applyMatrix4(matrix)
          .clone().sub(offset));
      const normal = corners[1].clone().sub(corners[0])
        .cross(corners[2].clone().sub(corners[0])).normalize();
      writeVector(normal);
      corners.forEach(writeVector);
      cursor += 2; // binary STL attribute bytes
    }
    return {
      buffer, triangles: faces.length,
      x_mm: centre.x, y_mm: centre.y,
      width: size.x, depth: size.y, height: size.z,
      index: partIndex + 1,
    };
  });
  return { parts, message: parts.length + " separate mesh components detected." };
}
