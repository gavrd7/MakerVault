import test from "node:test";
import assert from "node:assert/strict";
import { plateEnvelope, plateExtentWarning } from "../src/components/slicerPlateGeometry.js";
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
