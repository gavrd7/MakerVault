/**
 * MakerVault facet-colour painting core.
 *
 * The durable representation is a sparse face-index -> palette-slot map.
 * Slots are logical slicer slots, NOT physical CFS positions or G-code tools.
 * A mesh fingerprint and face count are required before replaying edits:
 * changing/reordering geometry must never silently recolour wrong faces.
 */
const MAX_FACES = 500000;
const MAX_SLOTS = 64;
const QUANTISE = 10000;

function meshPositions(geometry) {
  const position = geometry?.getAttribute?.("position");
  const index = geometry?.getIndex?.();
  const corners = index ? index.count : (position?.count || 0);
  if (!position || corners % 3 || corners < 3 || corners / 3 > MAX_FACES)
    throw new Error("Painting requires a valid mesh with at most 500,000 triangles.");
  const point = corner => {
    const i = index ? index.getX(corner) : corner;
    const v = [position.getX(i), position.getY(i), position.getZ(i)];
    if (!v.every(Number.isFinite)) throw new Error("Invalid mesh coordinates.");
    return v;
  };
  return { point, faces: corners / 3 };
}

const vertexKey = v => v.map(n => Math.round(n * QUANTISE)).join(",");
const edgeKey = (a, b) => [vertexKey(a), vertexKey(b)].sort().join("|");
const vector = (a, b) => a.map((x, i) => x - b[i]);
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a.reduce((sum, x, i) => sum + x * b[i], 0);
const magnitude = a => Math.sqrt(dot(a, a));
const distance = (a, b) => magnitude(vector(a, b));
function validateSlot(slot) {
  if (!Number.isInteger(slot) || slot < 0 || slot >= MAX_SLOTS)
    throw new Error("Invalid logical paint slot.");
}
function validateFace(face, count) {
  if (!Number.isInteger(face) || face < 0 || face >= count)
    throw new Error("Invalid painted face index.");
}

/** Indexed and non-indexed STL meshes share the same face order. */
export function createPaintMesh(geometry) {
  const { point, faces } = meshPositions(geometry);
  const centres = new Array(faces), normals = new Array(faces);
  const heights = new Array(faces), neighbours = Array.from({ length: faces }, () => new Set());
  const edges = new Map();
  let fingerprint = 2166136261;
  for (let f = 0; f < faces; f++) {
    const v = [point(f * 3), point(f * 3 + 1), point(f * 3 + 2)];
    centres[f] = [0, 1, 2].map(axis => (v[0][axis] + v[1][axis] + v[2][axis]) / 3);
    heights[f] = centres[f][2];
    const n = cross(vector(v[1], v[0]), vector(v[2], v[0]));
    const length = magnitude(n);
    normals[f] = length ? n.map(value => value / length) : [0, 0, 0];
    for (const p of v) for (const coordinate of p) {
      const rounded = Math.round(coordinate * QUANTISE);
      fingerprint = Math.imul(fingerprint ^ rounded, 16777619) >>> 0;
    }
    for (let i = 0; i < 3; i++) {
      const key = edgeKey(v[i], v[(i + 1) % 3]);
      const owners = edges.get(key);
      if (owners) owners.push(f);
      else edges.set(key, [f]);
    }
  }
  for (const owners of edges.values()) {
    // Non-manifold edges are connected to every adjacent face.
    for (let i = 0; i < owners.length; i++)
      for (let j = i + 1; j < owners.length; j++) {
        neighbours[owners[i]].add(owners[j]);
        neighbours[owners[j]].add(owners[i]);
      }
  }
  return { faceCount: faces, signature: faces + ":" + fingerprint.toString(16),
    centres, normals, heights, neighbours: neighbours.map(s => [...s]),
    triangle: face => [point(face*3),point(face*3+1),point(face*3+2)] };
}

export function selectPaintFaces(mesh, { mode, face, radiusMm = 2, angleDeg = 30,
  minHeightMm = 0, maxHeightMm = Infinity, centre = null, surfaceNormal = null } = {}) {
  const count = mesh?.faceCount;
  if (!Number.isInteger(count) || count < 1 || count > MAX_FACES)
    throw new Error("Invalid painting mesh.");
  if (mode === "height") {
    if (!Number.isFinite(minHeightMm) || !(Number.isFinite(maxHeightMm) || maxHeightMm === Infinity) ||
        minHeightMm > maxHeightMm) throw new Error("Invalid height selection.");
    return mesh.heights.flatMap((h, i) => h >= minHeightMm && h <= maxHeightMm ? [i] : []);
  }
  validateFace(face, count);
  if (mode === "facet") return [face];
  if (mode === "brush") {
    if (!Number.isFinite(radiusMm) || radiusMm <= 0 || radiusMm > 1000)
      throw new Error("Invalid brush radius.");
    return mesh.centres.flatMap((centre, i) =>
      distance(centre, mesh.centres[face]) <= radiusMm ? [i] : []);
  }
  if (mode === "sphere" || mode === "circle") {
    if (!Number.isFinite(radiusMm) || radiusMm <= 0 || radiusMm > 1000)
      throw new Error("Invalid paint radius.");
    const origin = centre || mesh.centres[face];
    if (!Array.isArray(origin) || origin.length !== 3 || !origin.every(Number.isFinite))
      throw new Error("Invalid paint origin.");
    const radius2 = radiusMm * radiusMm;
    const normal = surfaceNormal || mesh.normals[face];
    if (!Array.isArray(normal) || normal.length !== 3 || !normal.every(Number.isFinite))
      throw new Error("Invalid circular brush direction.");
    const unitLength = magnitude(normal);
    const unit = unitLength ? normal.map(n=>n/unitLength) : [0,0,1];
    return mesh.centres.flatMap((point, i) => {
      const delta = vector(point, origin);
      if (mode === "sphere") return dot(delta,delta) <= radius2 ? [i] : [];
      // The disc follows the face being painted rather than the printer's XY
      // plane. Avoid colouring hidden/back surfaces across the entire mesh.
      const depth = dot(delta,unit);
      const projectedSquared = Math.max(0,dot(delta,delta)-depth*depth);
      // Face-centre-only inclusion creates a triangular stamp when a circle
      // overlaps a coarse triangle. Include any face whose projected edge
      // intersects the disc; still restrict paint to the clicked surface.
      if (Math.abs(depth) > Math.max(.12,radiusMm*.15) ||
          dot(mesh.normals[i],unit) < Math.cos(12*Math.PI/180)) return [];
      if(projectedSquared <= radius2) return [i];
      const triangle=mesh.triangle?.(i);
      if(!triangle) return [];
      const near=triangle.some(v=>{
        const dv=vector(v,origin);
        const h=dot(dv,unit);
        return Math.abs(h)<=Math.max(.12,radiusMm*.15) &&
          dot(dv,dv)-h*h<=radius2;
      });
      if(near)return [i];
      const nearEdge=triangle.some((v,j)=>{
        const w=triangle[(j+1)%3];
        const va=vector(v,origin),vb=vector(w,origin);
        const ha=dot(va,unit),hb=dot(vb,unit);
        const aa=va.map((x,k)=>x-ha*unit[k]),bb=vb.map((x,k)=>x-hb*unit[k]);
        const edge=vector(bb,aa);
        const denom=dot(edge,edge);
        const fraction=denom>0?Math.max(0,Math.min(1,-dot(aa,edge)/denom)):0;
        const closest=aa.map((x,k)=>x+fraction*edge[k]);
        return dot(closest,closest)<=radius2;
      });
      return nearEdge?[i]:[];
    });
  }
  if (mode === "fill" || mode === "smart_fill") {
    if (!Number.isFinite(angleDeg) || angleDeg < 0 || angleDeg > 180)
      throw new Error("Invalid fill angle.");
    // Neither fill mode may flood the entire connected STL shell.
    // Ordinary Fill is a conservative seed-plane flood (roof, floor, wall);
    // Smart Fill permits a configurable seed-normal angle but does not
    // accumulate small bends until it wraps around the whole object.
    const selected = new Set([face]), queue = [face];
    const threshold = Math.cos((mode === "fill" ? 5 : angleDeg) * Math.PI / 180);
    const stepThreshold = Math.cos((mode === "fill" ? 8 : Math.min(45, angleDeg)) * Math.PI / 180);
    const seedNormal = mesh.normals[face];
    const seedCentre = mesh.centres[face];
    const planarToleranceMm = mode === "fill" ? 0.22 : Infinity;
    for (let head = 0; head < queue.length; head++) {
      const current = queue[head];
      for (const neighbour of mesh.neighbours[current]) {
        if (selected.has(neighbour)) continue;
        if (dot(seedNormal, mesh.normals[neighbour]) < threshold ||
            dot(mesh.normals[current], mesh.normals[neighbour]) < stepThreshold ||
            Math.abs(dot(vector(mesh.centres[neighbour],seedCentre),seedNormal)) > planarToleranceMm)
          continue;
        selected.add(neighbour);
        queue.push(neighbour);
      }
    }
    return [...selected].sort((a, b) => a - b);
  }
  throw new Error("Unknown colour painting tool.");
}

/** Immutable edit; null slot erases painted facets back to base material. */
export function applyPaint(state, mesh, faces, slot) {
  if (slot !== null) validateSlot(slot);
  if (state && (state.version !== 1 || state.signature !== mesh.signature))
    throw new Error("The model geometry changed; painted faces cannot be safely replayed.");
  if (!Array.isArray(faces) || faces.length > mesh.faceCount)
    throw new Error("Invalid painted face selection.");
  const byFace = { ...(state?.faces || {}) };
  for (const face of faces) {
    validateFace(face, mesh.faceCount);
    if (slot === null) delete byFace[face];
    else byFace[face] = slot;
  }
  return { version: 1, signature: mesh.signature, faces: byFace };
}

export function validatePaint(state, mesh, allowedSlots) {
  if (!state || state.version !== 1 || state.signature !== mesh.signature ||
      !state.faces || typeof state.faces !== "object" || Array.isArray(state.faces))
    throw new Error("Invalid or stale face painting data.");
  const allowed = new Set(allowedSlots);
  for (const [index, slot] of Object.entries(state.faces)) {
    if (!/^(0|[1-9][0-9]*)$/.test(index)) throw new Error("Invalid painted face key.");
    validateFace(Number(index), mesh.faceCount);
    validateSlot(slot);
    if (!allowed.has(slot)) throw new Error("Painted slot is not available in this palette.");
  }
  return state;
}
