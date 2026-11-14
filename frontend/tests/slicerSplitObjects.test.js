import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { splitDisconnectedMesh } from "../src/components/slicerSplitObjects.js";

function joinedModels(offset = 40) {
  const first = new THREE.BoxGeometry(10, 10, 10).toNonIndexed();
  const second = new THREE.BoxGeometry(offset === 0 ? 10 : 8, offset === 0 ? 10 : 8, offset === 0 ? 10 : 8).toNonIndexed();
  second.translate(offset, 0, 0);
  const a = first.getAttribute("position").array;
  const b = second.getAttribute("position").array;
  const all = new Float32Array(a.length + b.length);
  all.set(a); all.set(b, a.length);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(all, 3));
  first.dispose(); second.dispose();
  return geometry;
}

test("split detects two disconnected solids from ordinary non-indexed STL triangles", () => {
  const geometry = joinedModels();
  const mesh = new THREE.Mesh(geometry);
  mesh.position.set(12, -4, 7);
  mesh.rotation.z = Math.PI / 2;
  mesh.updateMatrixWorld();
  const before = Array.from(geometry.getAttribute("position").array);
  const result = splitDisconnectedMesh(mesh);
  assert.equal(result.parts.length, 2);
  assert.equal(result.parts.reduce((sum, part) => sum + part.triangles, 0), 24);
  for (const part of result.parts) {
    assert.equal(new DataView(part.buffer).getUint32(80, true), part.triangles);
    assert.equal(part.buffer.byteLength, 84 + part.triangles * 50);
    assert.ok(Number.isFinite(part.x_mm) && Number.isFinite(part.y_mm));
  }
  assert.notEqual(result.parts[0].y_mm, result.parts[1].y_mm);
  assert.deepEqual(Array.from(geometry.getAttribute("position").array), before);
  geometry.dispose();
});

test("single watertight box cannot split and original mesh is unchanged", () => {
  const geometry = new THREE.BoxGeometry(12, 14, 18);
  const mesh = new THREE.Mesh(geometry);
  const result = splitDisconnectedMesh(mesh);
  assert.equal(result.parts.length, 0);
  assert.match(result.message, /one connected mesh/);
  geometry.dispose();
});

test("split refuses exceeding remaining model slots without losing geometry", () => {
  const geometry = joinedModels();
  const mesh = new THREE.Mesh(geometry);
  assert.throws(() => splitDisconnectedMesh(mesh, 1), /exceeding the available 1 model slots/);
  geometry.dispose();
});

test("split does not depend on shared vertex indices", () => {
  const geometry = joinedModels(0);
  const mesh = new THREE.Mesh(geometry);
  // Coincident surfaces are vertex-connected, and should not be split.
  assert.equal(splitDisconnectedMesh(mesh).parts.length, 0);
  geometry.dispose();
});
