/**
 * Read-only STL feature detection from a raycast point. Triangle meshes do not
 * preserve original CAD faces or analytic circles: inferred segments and
 * facets must always be labelled as mesh approximations.
 *
 * Cap expensive topology discovery on unusually dense meshes. No geometry is
 * modified, and the returned points are in the same world coordinates as the
 * measurement pins.
 */
import * as THREE from "three";

const MAX_TRIANGLES = 90000;
const CREASE_COSINE = Math.cos(Math.PI / 6);
const PLANAR_COSINE = 0.9999;
const PLANE_TOLERANCE_MM = 0.06;
const MAX_HIGHLIGHT_TRIANGLES = 12000;
const geometryCache = new WeakMap();

const edgeKey = (a, b) => a < b ? a + "|" + b : b + "|" + a;
const pointKey = p => [p.x, p.y, p.z].map(n => Math.round(n * 10000)).join(",");

function indexGeometry(geometry, localPoint, selectedFace) {
  const positions = geometry.getAttribute("position");
  const indices = geometry.getIndex();
  const count = Math.floor((indices ? indices.count : positions?.count || 0) / 3);
  if (!positions || count < 1) return { unavailable: true };
  const localOnly = count > MAX_TRIANGLES;
  // Dense STLs (including common Benchy exports) are searched within a
  // bounded local neighbourhood of the click rather than indexing the whole
  // mesh into a large in-memory graph. Whole-mesh indexes are cached.
  if (!localOnly && geometryCache.has(geometry)) return geometryCache.get(geometry);
  if (localOnly && !localPoint) return { unavailable: true };
  const vertices = [];
  const vertexIds = new Map();
  const faces = [];
  const edges = new Map();
  let included = 0;
  for (let i = 0; i < count; i++) {
    const raw = [];
    for (let j = 0; j < 3; j++) {
      const index = indices ? indices.getX(3 * i + j) : 3 * i + j;
      raw.push(new THREE.Vector3().fromBufferAttribute(positions, index));
    }
    // 25mm local neighbourhood, converted from the hit into unscaled STL
    // coordinates. A partial patch must be labelled as such below.
    if (localOnly && i !== selectedFace &&
        !raw.some(point => point.distanceToSquared(localPoint) <= 25 * 25))
      continue;
    if (++included > MAX_TRIANGLES) return { unavailable: true };
    const corners = [];
    for (let j = 0; j < 3; j++) {
      const p = raw[j];
      const key = pointKey(p);
      if (!vertexIds.has(key)) {
        vertexIds.set(key, vertices.length);
        vertices.push(p);
      }
      corners.push(vertexIds.get(key));
    }
    const [a, b, c] = corners.map(id => vertices[id]);
    const cross = new THREE.Vector3().subVectors(b, a)
      .cross(new THREE.Vector3().subVectors(c, a));
    const normal = cross.clone().normalize();
    faces[i] = { corners, normal };
    for (let j = 0; j < 3; j++) {
      const key = edgeKey(corners[j], corners[(j + 1) % 3]);
      if (!edges.has(key)) edges.set(key, []);
      edges.get(key).push(i);
    }
  }
  const topology = { vertices, faces, edges, localOnly };
  if (!localOnly) geometryCache.set(geometry, topology);
  return topology;
}

export function detectMeshMeasurement(mesh, hit, tolerance = 1.5) {
  if (!mesh?.geometry || !hit?.face || !hit?.point) return null;
  mesh.updateMatrixWorld(true);
  const faceIndex = hit.faceIndex;
  const localPoint = mesh.worldToLocal(hit.point.clone());
  const topology = indexGeometry(mesh.geometry, localPoint, faceIndex);
  if (topology.unavailable || !Number.isInteger(faceIndex) || !topology.faces[faceIndex])
    return { kind: "unavailable", label: "Automatic feature detection is unavailable for this STL. Use two-point measurement." };
  mesh.updateMatrixWorld(true);
  const world = topology.vertices.map(point => point.clone().applyMatrix4(mesh.matrixWorld));
  const face = topology.faces[faceIndex];
  const corners = face.corners;
  const normals = new Map();
  const faceNormal = index => {
    if (!normals.has(index)) {
      const f = topology.faces[index].corners.map(id => world[id]);
      normals.set(index, new THREE.Vector3().subVectors(f[1], f[0])
        .cross(new THREE.Vector3().subVectors(f[2], f[0])).normalize());
    }
    return normals.get(index);
  };
  const candidates = [];
  for (let j = 0; j < 3; j++) {
    const idA = corners[j], idB = corners[(j + 1) % 3];
    const adjacent = topology.edges.get(edgeKey(idA, idB)) || [];
    const isCrease = (!topology.localOnly && adjacent.length === 1) || adjacent.some(id =>
      id !== faceIndex && faceNormal(id).dot(faceNormal(faceIndex)) < CREASE_COSINE);
    if (!isCrease) continue;
    const a = world[idA], b = world[idB];
    const nearest = new THREE.Line3(a, b).closestPointToPoint(hit.point, true, new THREE.Vector3());
    candidates.push({ a, b, nearest, distance: nearest.distanceTo(hit.point) });
  }
  candidates.sort((a, b) => a.distance - b.distance);
  if (candidates[0] && candidates[0].distance <= tolerance) {
    const { a, b, nearest } = candidates[0];
    return {
      kind: "edge",
      label: "Detected sharp mesh edge segment",
      value: a.distanceTo(b),
      unit: "length",
      point: nearest.toArray(),
      start: a.toArray(),
      end: b.toArray(),
    };
  }

  // Flood-fill the clicked triangle's connected, approximately coplanar
  // neighbours to estimate the full planar patch area, not a random facet.
  // Only an explicitly planar patch is reported; curved faces will not be
  // silently advertised as an exact CAD surface.
  const baseNormal = faceNormal(faceIndex);
  const reference = world[corners[0]];
  const visited = new Set([faceIndex]);
  const queue = [faceIndex];
  let area = 0;
  while (queue.length) {
    const id = queue.pop();
    const ids = topology.faces[id].corners;
    const [a, b, c] = ids.map(v => world[v]);
    const cross = new THREE.Vector3().subVectors(b, a)
      .cross(new THREE.Vector3().subVectors(c, a));
    area += cross.length() / 2;
    for (let i = 0; i < 3; i++) {
      const neighbours = topology.edges.get(edgeKey(ids[i], ids[(i + 1) % 3])) || [];
      for (const neighbour of neighbours) {
        if (visited.has(neighbour)) continue;
        const f = topology.faces[neighbour];
        if (faceNormal(neighbour).dot(baseNormal) < PLANAR_COSINE ||
            f.corners.some(v => Math.abs(world[v].clone().sub(reference).dot(baseNormal)) > PLANE_TOLERANCE_MM))
          continue;
        visited.add(neighbour);
        queue.push(neighbour);
      }
    }
  }
  if (visited.size >= 2 && area > 0 && Number.isFinite(area)) {
    // Preserve the exact triangles used for the measurement so the viewport
    // can highlight the measured patch rather than only a single click marker.
    // Coordinates are in world space, matching the existing measurement overlay.
    // Bound the overlay to avoid flooding mobile GPUs with large STL surfaces.
    const highlightPositions = [];
    for (const id of visited) {
      if (highlightPositions.length >= MAX_HIGHLIGHT_TRIANGLES * 9) break;
      const corners = topology.faces[id].corners;
      for (const vertexId of corners) {
        const vertex = world[vertexId];
        highlightPositions.push(vertex.x, vertex.y, vertex.z);
      }
    }
    return {
      kind: "face",
      label: topology.localOnly
        ? "Detected local planar mesh patch (partial area estimate)"
        : "Detected approximately planar mesh patch",
      value: area,
      unit: "area",
      triangles: visited.size,
      partial: topology.localOnly,
      highlightPositions,
      highlightLimited: visited.size > MAX_HIGHLIGHT_TRIANGLES,
      point: hit.point.toArray(),
    };
  }
  return {
    kind: "unavailable",
    label: "No clear sharp edge or connected planar face at this point. Try another position or use two-point measurement.",
  };
}

export function formatDetectedMeasurement(feature, unit = "mm") {
  if (!feature || !Number.isFinite(feature.value)) return "—";
  const inches = unit === "in";
  const converted = feature.unit === "area"
    ? feature.value / (inches ? 25.4 * 25.4 : 1)
    : feature.value / (inches ? 25.4 : 1);
  return converted.toFixed(3) + " " + (inches ? "in" : "mm") + (feature.unit === "area" ? "²" : "");
}
