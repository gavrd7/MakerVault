import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { evaluateAutoOrient, AUTO_ORIENT_GOALS } from "../src/components/slicerAutoOrient.js";

const tallModel = () => {
  const geometry = new THREE.BoxGeometry(12, 14, 70);
  geometry.translate(0, 0, 35);
  return geometry;
};
const instance = {
  instance_id: "tower", asset_id: "test", x_mm: 0, y_mm: 0,
  rotation_deg: 0, rotation_xyz_deg: [0, 0],
  scale_percent: 100, scale_xyz_percent: [100, 100, 100],
};
const dims = { tower: { width: 12, depth: 14, height: 70 } };

test("auto-orient offers three distinct strategies and finite rankable mesh proxies", () => {
  const geometry = tallModel();
  const result = evaluateAutoOrient(geometry, instance, 220, 220, [instance], dims);
  geometry.dispose();
  assert.ok(!result.error, result.error);
  assert.deepEqual(Object.keys(AUTO_ORIENT_GOALS), ["balanced", "supports", "speed"]);
  for (const goal of ["balanced", "supports", "speed"]) {
    assert.ok(result.choices[goal].length >= 2);
    assert.ok(result.choices[goal].every(candidate =>
      Number.isFinite(candidate.score) && Number.isFinite(candidate.metrics.height) &&
      candidate.orientation.rotation_xyz_deg.length === 2));
    assert.ok(result.choices[goal][0].score <= result.choices[goal].at(-1).score);
  }
  assert.match(result.warning, /not predicted by a native slicer/);
});

test("speed mode prefers shorter layer height for a tall rectangular model", () => {
  const geometry = tallModel();
  const result = evaluateAutoOrient(geometry, instance, 220, 220, [instance], dims);
  geometry.dispose();
  assert.ok(!result.error, result.error);
  const recommended = result.choices.speed[0];
  assert.ok(recommended.metrics.height < 20,
    "Fastest heuristic should put a 70mm tall tower on its side");
  assert.notEqual(recommended.orientation.rotation_xyz_deg.join(","), "0,0");
});

test("candidate poses stay within the plate and avoid other objects", () => {
  const geometry = tallModel();
  const obstructing = {
    instance_id: "block", x_mm: 0, y_mm: 0,
    rotation_deg: 0, scale_percent: 100,
  };
  const blocked = evaluateAutoOrient(geometry, instance, 220, 220,
    [instance, obstructing], { ...dims, block: { width: 220, depth: 220, height: 10 } });
  assert.match(blocked.error, /No candidate orientation fits/);
  const tooSmall = evaluateAutoOrient(geometry, instance, 5, 5, [instance], dims);
  assert.match(tooSmall.error, /No candidate orientation fits/);
  geometry.dispose();
});

test("orientation analysis never mutates source item or its STL geometry", () => {
  const geometry = tallModel();
  const before = JSON.stringify(instance);
  const original = geometry.attributes.position.array.slice();
  evaluateAutoOrient(geometry, instance, 220, 220, [instance], dims);
  assert.equal(JSON.stringify(instance), before);
  assert.deepEqual([...geometry.attributes.position.array], [...original]);
  geometry.dispose();
});

test("two candidates preserve genuine proportional differences instead of forced 0/100 scores", () => {
  const geometry = tallModel();
  const result = evaluateAutoOrient(geometry, instance, 220, 220, [instance], dims);
  assert.ok(!result.error, result.error);
  for (const key of ["time", "material", "support", "failure"]) {
    const values = result.choices.balanced.map(candidate => candidate.relative[key]);
    assert.ok(values.every(value => Number.isFinite(value.absolute) && Number.isFinite(value.score)));
    for (const value of values) {
      assert.ok(value.score >= 0 && value.score < 1, "proportional scores should not become binary extrema");
      assert.ok(value.percent === null || value.percent >= 0);
    }
  }
  const times = result.choices.balanced.map(candidate => candidate.relative.time);
  const min = Math.min(...times.map(value => value.absolute));
  for (const value of times) {
    assert.equal(value.percent, Math.round(((value.absolute - min) / min) * 1000) / 10);
  }
  geometry.dispose();
});
