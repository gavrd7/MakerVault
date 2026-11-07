import test from "node:test";
import assert from "node:assert/strict";
import { plateEnvelope, plateExtentWarning, plateFootprintsOverlap, autoArrangePlate } from "../src/components/slicerPlateGeometry.js";
const item = { x_mm: 0, y_mm: 0, rotation_deg: 0, scale_percent: 100 };
const box = { width: 40, depth: 20 };
test("centred unrotated footprint", () => {
  assert.deepEqual(plateEnvelope(item, box), { minX: -20, maxX: 20, minY: -10, maxY: 10 });
  assert.equal(plateExtentWarning(item, box, 220, 220), "");
});
test("rotated footprint accounts for scaling and translation", () => {
  const result = plateEnvelope({ ...item, x_mm: 95, rotation_deg: 90, scale_percent: 200 }, box);
  assert.ok(Math.abs(result.minX - 75) < 1e-8);
  assert.ok(Math.abs(result.maxX - 115) < 1e-8);
  assert.equal(plateExtentWarning({ ...item, x_mm: 95, rotation_deg: 90, scale_percent: 200 }, box, 220, 220),
    "Estimated XY footprint extends beyond the displayed plate");
});
test("touching plate boundary is allowed; crossing it warns", () => {
  assert.equal(plateExtentWarning({ ...item, x_mm: 90 }, box, 220, 220), "");
  assert.ok(plateExtentWarning({ ...item, x_mm: 91 }, box, 220, 220));
});
test("invalid transforms never count as known fit", () => {
  assert.equal(plateEnvelope({ ...item, scale_percent: 0 }, box), null);
  assert.ok(plateExtentWarning(item, null, 220, 220));
});

test("automatic arranging separates imported models using actual dimensions", () => {
  const items = ["one", "two", "three", "four"].map(instance_id => ({
    instance_id, ...item, x_mm: 0, y_mm: 0,
  }));
  const sizes = Object.fromEntries(items.map(row => [row.instance_id, { width: 40, depth: 30 }]));
  const result = autoArrangePlate(items, sizes, 120, 120, 5);
  assert.equal(result.error, undefined);
  assert.equal(result.objects.length, 4);
  for (const [index, current] of result.objects.entries()) {
    assert.equal(plateExtentWarning(current, sizes[current.instance_id], 120, 120), "");
    for (const other of result.objects.slice(0, index)) {
      assert.equal(plateFootprintsOverlap(current, sizes[current.instance_id],
        other, sizes[other.instance_id], 5), false);
    }
  }
});
test("auto arrangement respects rotation and scale without modifying native transformations", () => {
  const objects = [
    { ...item, instance_id: "a", rotation_deg: 90, scale_percent: 150 },
    { ...item, instance_id: "b", rotation_deg: 0, scale_percent: 50 },
  ];
  const dimensions = { a: { width: 40, depth: 20 }, b: { width: 40, depth: 20 } };
  const result = autoArrangePlate(objects, dimensions, 100, 100);
  assert.equal(result.error, undefined);
  assert.equal(result.objects[0].rotation_deg, 90);
  assert.equal(result.objects[0].scale_percent, 150);
  assert.equal(result.objects[1].scale_percent, 50);
  assert.equal(plateFootprintsOverlap(result.objects[0], dimensions.a,
    result.objects[1], dimensions.b, 5), false);
});
test("missing geometry and overcrowded plates fail without changing the original", () => {
  const items = Array.from({ length: 6 }, (_, i) => ({
    ...item, instance_id: String(i), x_mm: 0, y_mm: 0,
  }));
  const dimensions = Object.fromEntries(items.map(row => [row.instance_id, { width: 60, depth: 60 }]));
  const before = JSON.stringify(items);
  assert.match(autoArrangePlate(items, {}, 100, 100).error, /loading/);
  assert.match(autoArrangePlate(items, dimensions, 100, 100).error, /free build plate/);
  assert.equal(JSON.stringify(items), before);
});
test("overlap check treats unknown geometry as unavailable rather than safe", () => {
  const a = { ...item, x_mm: 0, y_mm: 0 };
  const b = { ...item, x_mm: 5, y_mm: 5 };
  assert.equal(plateFootprintsOverlap(a, box, b, box, 2), true);
  assert.equal(plateFootprintsOverlap(a, null, b, box, 2), null);
});

test("auto-arrange keeps every model's preview colour and identity unchanged", () => {
  const objects = [
    { ...item, instance_id: "blue", color: "#58b5e4" },
    { ...item, instance_id: "orange", color: "#f59e0b" },
  ];
  const dimensions = {
    blue: { width: 35, depth: 25 },
    orange: { width: 35, depth: 25 },
  };
  const arranged = autoArrangePlate(objects, dimensions, 120, 120, 5);
  assert.equal(arranged.error, undefined);
  assert.deepEqual(arranged.objects.map(model => [model.instance_id, model.color]), [
    ["blue", "#58b5e4"], ["orange", "#f59e0b"],
  ]);
  assert.deepEqual(objects.map(model => [model.x_mm, model.y_mm]), [[0, 0], [0, 0]]);
});
