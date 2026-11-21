import test from "node:test";
import assert from "node:assert/strict";
import { plateEnvelope, plateExtentWarning, plateFootprintsOverlap, autoArrangePlate, findFreeDuplicatePosition, plateModelMeasurement, measurementDistance, measurementCircle, measurementFormat } from "../src/components/slicerPlateGeometry.js";
const item = { x_mm: 0, y_mm: 0, rotation_deg: 0, scale_percent: 100 };
const box = { width: 40, depth: 20 };
test("lay-on-face tilt changes footprint and effective model height", () => {
  const upright = { ...item, rotation_xyz_deg: [0, 0] };
  const lying = { ...item, rotation_xyz_deg: [90, 0] };
  const dims = { width: 30, depth: 12, height: 50 };
  const oldBox = plateEnvelope(upright, dims);
  const newBox = plateEnvelope(lying, dims);
  assert.ok(Math.abs(oldBox.maxY - oldBox.minY - 12) < 1e-8);
  assert.ok(Math.abs(newBox.maxY - newBox.minY - 50) < 1e-8);
  const measurement = plateModelMeasurement(lying, dims);
  assert.ok(Math.abs(measurement.height - 12) < 1e-8);
  // Without a loaded STL height, rotated placement must not invent bounds.
  assert.equal(plateEnvelope(lying, { width: 30, depth: 12 }), null);
});

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

test("independent XY scale is applied before rotation and keeps conservative clearance", () => {
  const transformed = { ...item, rotation_deg: 90, scale_xyz_percent: [150, 50, 200] };
  const bounds = plateEnvelope(transformed, box);
  assert.ok(Math.abs(bounds.minX + 5) < 1e-8);
  assert.ok(Math.abs(bounds.maxX - 5) < 1e-8);
  assert.ok(Math.abs(bounds.minY + 30) < 1e-8);
  assert.ok(Math.abs(bounds.maxY - 30) < 1e-8);
  assert.equal(plateExtentWarning({ ...transformed, x_mm: 106 }, box, 220, 220),
    "Estimated XY footprint extends beyond the displayed plate");
});

test("two Benchy-sized fractional STL bounds fit on a 220 mm plate", () => {
  // STL bounding boxes seldom end on exact hundredth-millimetre boundaries.
  // Previously the first candidate could round just outside X/Y=-110 and
  // incorrectly announce that the entire bed was full.
  const models = [
    { ...item, instance_id: "benchy-1", x_mm: -24, y_mm: 21 },
    { ...item, instance_id: "benchy-2", x_mm: 28, y_mm: -69 },
  ];
  const sizes = {
    "benchy-1": { width: 61.223, depth: 32.197 },
    "benchy-2": { width: 61.223, depth: 32.197 },
  };
  const result = autoArrangePlate(models, sizes, 220, 220, 5);
  assert.equal(result.error, undefined);
  assert.equal(result.objects.length, 2);
  for (const model of result.objects) {
    assert.equal(plateExtentWarning(model, sizes[model.instance_id], 220, 220), "");
  }
  assert.equal(plateFootprintsOverlap(result.objects[0], sizes["benchy-1"],
    result.objects[1], sizes["benchy-2"], 5), false);
  assert.deepEqual(models.map(v => [v.x_mm, v.y_mm]), [[-24, 21], [28, -69]]);
});

test("fractional footprint dimensions never round the first model outside the bed", () => {
  for (const [width, depth] of [
    [61.223, 32.197], [55.001, 44.009], [60.337, 61.223],
    [30.019, 79.991], [48.225, 48.225],
  ]) {
    const object = { ...item, instance_id: "one", x_mm: 0, y_mm: 0 };
    const result = autoArrangePlate([object], { one: { width, depth } }, 220, 220);
    assert.equal(result.error, undefined, "unexpected packing failure for " + width + " × " + depth);
    assert.equal(plateExtentWarning(result.objects[0], { width, depth }, 220, 220), "");
  }
});

test("measurement includes mesh height, independent XYZ scale and translated envelope", () => {
  const result = plateModelMeasurement({
    x_mm: 15, y_mm: -20, rotation_deg: 0, scale_percent: 100,
    scale_xyz_percent: [150, 50, 200],
  }, { width: 40, depth: 20, height: 12 });
  assert.deepEqual(result, {
    width: 60, depth: 10, height: 24,
    minX: -15, maxX: 45, minY: -25, maxY: -15,
  });
});
test("measurement swaps a rectangular XY footprint after quarter turn", () => {
  const result = plateModelMeasurement({
    x_mm: 0, y_mm: 0, rotation_deg: 90, scale_percent: 100,
  }, { width: 40, depth: 20, height: 25 });
  assert.ok(Math.abs(result.width - 20) < 1e-8);
  assert.ok(Math.abs(result.depth - 40) < 1e-8);
  assert.equal(result.height, 25);
});
test("measurement waits for a measured STL and rejects nonfinite height", () => {
  assert.equal(plateModelMeasurement(item, { width: 30, depth: 20 }), null);
  assert.equal(plateModelMeasurement(item, { width: 30, depth: 20, height: Infinity }), null);
});

test("two surface pins measure 3D Euclidean distance, not just XY", () => {
  assert.equal(measurementDistance([0, 0, 0], [3, 4, 12]), 13);
  assert.equal(measurementDistance([0, 0, 0], [3, 4, Infinity]), null);
  assert.equal(measurementDistance([0, 0], [3, 4, 12]), null);
});
test("unit toggle converts measurements without changing underlying millimetres", () => {
  assert.equal(measurementFormat(25.4, "in"), "1.000 in");
  assert.equal(measurementFormat(25.4, "mm"), "25.400 mm");
  assert.equal(measurementFormat(-12.7, "in"), "-0.500 in");
});
test("three non-collinear surface pins construct a 3D circle", () => {
  const result = measurementCircle([10, 0, 3], [0, 10, 3], [-10, 0, 3]);
  assert.ok(Math.abs(result.radius - 10) < 1e-8);
  assert.ok(Math.abs(result.diameter - 20) < 1e-8);
  assert.ok(Math.abs(result.circumference - 20 * Math.PI) < 1e-8);
  const upright = measurementCircle([0, 0, 10], [0, 10, 0], [0, 0, -10]);
  assert.ok(Math.abs(upright.radius - 10) < 1e-8);
});
test("collinear or repeated points must not be reported as circles", () => {
  assert.equal(measurementCircle([0, 0, 0], [1, 0, 0], [2, 0, 0]), null);
  assert.equal(measurementCircle([0, 0, 0], [0, 0, 0], [1, 2, 3]), null);
});

test("duplicate placement fills nearby free 2D slots without relocating originals",()=>{
  const dims={
    a:{width:20,depth:20,height:20},
    b:{width:20,depth:20,height:20},
    copy:{width:20,depth:20,height:20},
  };
  const a={instance_id:"a",x_mm:0,y_mm:0,rotation_deg:0,scale_percent:100};
  const b={...a,instance_id:"b",x_mm:23,y_mm:0};
  const copy={...a,instance_id:"copy"};
  const result=findFreeDuplicatePosition(copy,[a,b],dims,100,100,3);
  assert.ok(result,"a free slot exists off the central row");
  assert.equal(plateFootprintsOverlap(result,dims.copy,a,dims.a,3),false);
  assert.equal(plateFootprintsOverlap(result,dims.copy,b,dims.b,3),false);
  assert.equal(a.x_mm,0);
  assert.equal(b.x_mm,23);
});

test("four Benchies auto-arrange into a compact centred group rather than a long row", () => {
  const models = ["black", "blue", "white", "pink"].map((instance_id, index) => ({
    ...item, instance_id, x_mm: index * 50, y_mm: -75,
    color: ["#000000", "#628ca6", "#ffffff", "#db2b80"][index],
    material_slot: {printer_id: "k2", slot_id: "bay-" + index, slot_index: index},
  }));
  const dimensions = Object.fromEntries(models.map(row => [
    row.instance_id, {width: 61.223, depth: 32.197, height: 48},
  ]));
  const before = JSON.stringify(models);
  const result = autoArrangePlate(models, dimensions, 260, 260, 5);
  assert.equal(result.error, undefined);
  const envelopes = result.objects.map(model => plateEnvelope(model, dimensions[model.instance_id]));
  const minX = Math.min(...envelopes.map(row => row.minX));
  const maxX = Math.max(...envelopes.map(row => row.maxX));
  const minY = Math.min(...envelopes.map(row => row.minY));
  const maxY = Math.max(...envelopes.map(row => row.maxY));
  assert.ok(maxX - minX < 140, "compact group width rather than four-across");
  assert.ok(maxY - minY < 100, "compact group depth rather than four-deep");
  assert.ok(Math.abs((minX + maxX) / 2) < 1);
  assert.ok(Math.abs((minY + maxY) / 2) < 1);
  result.objects.forEach((model, i) => {
    assert.equal(model.instance_id, models[i].instance_id);
    assert.equal(model.color, models[i].color);
    assert.deepEqual(model.material_slot, models[i].material_slot);
    assert.equal(plateExtentWarning(model, dimensions[model.instance_id], 260, 260), "");
    for (let j = 0; j < i; j++)
      assert.equal(plateFootprintsOverlap(model, dimensions[model.instance_id],
        result.objects[j], dimensions[result.objects[j].instance_id], 5), false);
  });
  assert.equal(JSON.stringify(models), before, "arrangement must not mutate saved draft input");
  assert.deepEqual(autoArrangePlate(models, dimensions, 260, 260, 5), result,
    "packing must be deterministic");
});

test("auto-arrange falls back safely when a compact regular grid does not fit", () => {
  const models = ["a", "b", "c"].map(instance_id => ({ ...item, instance_id }));
  const sizes = {
    a: {width: 95, depth: 20},
    b: {width: 20, depth: 95},
    c: {width: 15, depth: 15},
  };
  const before = JSON.stringify(models);
  const result = autoArrangePlate(models, sizes, 125, 125, 5);
  if (!result.error) {
    result.objects.forEach((model, i) => {
      assert.equal(plateExtentWarning(model, sizes[model.instance_id], 125, 125), "");
      for (let j = 0; j < i; j++)
        assert.equal(plateFootprintsOverlap(model, sizes[model.instance_id],
          result.objects[j], sizes[result.objects[j].instance_id], 5), false);
    });
  }
  assert.equal(JSON.stringify(models), before);
});
