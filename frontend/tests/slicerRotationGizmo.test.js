import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { snapRotationDegrees, dragAngleFromRay, unwrapRotationDelta } from "../src/components/slicerRotationGizmo.js";

test("slow dragging uses 1 degree steps and faster gestures snap to 5 or 45 degrees", () => {
  assert.equal(snapRotationDegrees(43), 43);
  assert.equal(snapRotationDegrees(17), 17);
  assert.equal(snapRotationDegrees(-80), -80);
  assert.equal(snapRotationDegrees(43, false, 300), 45);
  assert.equal(snapRotationDegrees(17, false, 300), 15);
  assert.equal(snapRotationDegrees(18, false, 150), 20);
  assert.equal(snapRotationDegrees(18.4, true, 600), 18);
});

test("rotating about a local axis uses signed radial displacement", () => {
  const center = new THREE.Vector3(0, 0, 0);
  const axis = new THREE.Vector3(0, 0, 1);
  const start = new THREE.Vector3(1, 0, 0);
  const ray = new THREE.Ray(new THREE.Vector3(0, 1, 10), new THREE.Vector3(0, 0, -1));
  assert.ok(Math.abs(dragAngleFromRay(ray, center, axis, start) - Math.PI / 2) < 1e-8);
  const reverse = new THREE.Ray(new THREE.Vector3(0, -1, 10), new THREE.Vector3(0, 0, -1));
  assert.ok(Math.abs(dragAngleFromRay(reverse, center, axis, start) + Math.PI / 2) < 1e-8);
});

test("ray parallel to selected plane preserves the last angle", () => {
  const ray = new THREE.Ray(new THREE.Vector3(0, 0, 5), new THREE.Vector3(1, 0, 0));
  assert.equal(dragAngleFromRay(ray, new THREE.Vector3(), new THREE.Vector3(0, 0, 1),
    new THREE.Vector3(1, 0, 0), 0.123), 0.123);
});

test("drag angle can cross ±180 degrees without jumping backwards", () => {
  const before = THREE.MathUtils.degToRad(179);
  const after = THREE.MathUtils.degToRad(-178);
  assert.ok(Math.abs(THREE.MathUtils.radToDeg(unwrapRotationDelta(after, before)) - 3) < 1e-8);
  assert.ok(Math.abs(THREE.MathUtils.radToDeg(unwrapRotationDelta(before, after)) + 3) < 1e-8);
});
