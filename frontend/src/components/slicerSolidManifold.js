/**
 * Deterministic, local WebAssembly Boolean kernel for printable STL edits.
 *
 * three-bvh-csg can return open seams on ordinary cube cuts and drilling.
 * Manifold rejects non-manifold input and guarantees closed operation output;
 * MakerVault still performs its independent watertight STL check afterwards.
 */
import * as THREE from "three";
import createManifold from "manifold-3d";

// Keep the WebAssembly binary inside the Vite-generated JavaScript asset.
// Deployed MakerVault instances can serve assets behind a URL prefix or a
// protected route, so asking Emscripten to fetch /assets/manifold.wasm can
// return an HTML login/fallback page instead of WebAssembly. Explicit inline
// bundling avoids that second fetch entirely and requires no CDN or cloud.
// Node's unit tests continue to use the package's ordinary local WASM loader.
const browserWasm = typeof window === "undefined"
  ? null
  : (await import("manifold-3d/manifold.wasm?url&inline")).default;
if (browserWasm !== null &&
    !/^data:[^,]*;base64,/.test(browserWasm))
  throw new Error("The local Manifold WebAssembly asset is not embedded.");
const wasmBinary = browserWasm === null ? null : Uint8Array.from(
  atob(browserWasm.slice(browserWasm.indexOf(",") + 1)),
  byte => byte.charCodeAt(0),
);
const wasm = await createManifold(
  wasmBinary ? { wasmBinary } : undefined,
);
wasm.setup();
const { Manifold, Mesh } = wasm;
const MAX_FACES = 500000;

function toManifold(brush) {
  const geometry = brush.geometry;
  const attr = geometry.getAttribute("position");
  const index = geometry.getIndex();
  if (!attr) throw new Error("Solid edit has no vertex coordinates.");
  const faceCount = index ? index.count / 3 : attr.count / 3;
  if (!Number.isInteger(faceCount) || faceCount < 4 || faceCount > MAX_FACES)
    throw new Error("Solid edit input exceeds safe face limits.");
  const vertices = [];
  const triangles = new Uint32Array(faceCount * 3);
  const lookup = new Map();
  for (let i = 0; i < faceCount * 3; i++) {
    const at = index ? index.getX(i) : i;
    const xyz = [attr.getX(at), attr.getY(at), attr.getZ(at)];
    if (!xyz.every(Number.isFinite))
      throw new Error("Solid edit contains non-finite coordinates.");
    const key = xyz.map(n => Math.round(n * 100000)).join(",");
    let id = lookup.get(key);
    if (id === undefined) {
      id = vertices.length / 3;
      lookup.set(key, id);
      vertices.push(...xyz);
    }
    triangles[i] = id;
  }
  if (vertices.length / 3 > MAX_FACES * 3)
    throw new Error("Solid edit has too many distinct vertices.");
  return new Manifold(new Mesh({
    numProp: 3,
    vertProperties: new Float32Array(vertices),
    triVerts: triangles,
  }));
}

export function runWatertightBoolean(a, b, operation) {
  let left, right, output;
  try {
    left = toManifold(a);
    right = toManifold(b);
    if (operation === "add") output = left.add(right);
    else if (operation === "subtract") output = left.subtract(right);
    else if (operation === "intersect") output = left.intersect(right);
    else throw new Error("Unsupported solid operation.");
    if (output.isEmpty() || output.numTri() < 4 || output.numTri() > MAX_FACES)
      throw new Error("Solid edit produced an empty or oversized mesh.");
    const mesh = output.getMesh();
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(mesh.vertProperties), mesh.numProp));
    geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(mesh.triVerts), 1));
    geometry.computeVertexNormals();
    return new THREE.Mesh(geometry);
  } finally {
    output?.delete();
    right?.delete();
    left?.delete();
  }
}
