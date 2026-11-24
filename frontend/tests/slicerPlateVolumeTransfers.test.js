import test from "node:test";
import assert from "node:assert/strict";
import {movePrintablesPreservingVolumes} from "../src/components/slicerPlateVolumeTransfers.js";

const volume = (id, assembly_id = null) =>
  ({id, x_mm: 80, y_mm: 100, assembly_id, kind: "negative", coordinate_space: "world"});
const model = (instance_id, x_mm, volumes = [], assembly_id = null) =>
  ({instance_id, x_mm, y_mm: 100, modifier_volumes: volumes, assembly_id});

test("moving a printable keeps its free volumes on the source plate", () => {
  const before = [
    model("one", 80, [volume("cut"), volume("region")]),
    model("two", 90, []),
  ];
  const {remaining, moving} = movePrintablesPreservingVolumes(before, ["one"]);
  assert.deepEqual(moving.map(row => row.instance_id), ["one"]);
  assert.deepEqual(moving[0].modifier_volumes, []);
  assert.deepEqual(remaining[0].modifier_volumes.map(row => row.id), ["cut", "region"]);
  assert.equal(before[0].modifier_volumes.length, 2, "the original draft must remain unchanged");
});

test("moving the final printable leaves independent volumes in the canonical source plate", () => {
  const source = [model("one", 0, [volume("cut")])];
  const {remaining, moving} = movePrintablesPreservingVolumes(source, ["one"]);
  assert.deepEqual(remaining, []);
  assert.deepEqual(moving[0].modifier_volumes, []);
  // The canonical source plate stores the volume independently, so moving
  // its last printable cannot delete or silently relocate the cutter.
  assert.equal(source[0].modifier_volumes[0].id, "cut");
});

test("reject capacity exhaustion without modifying input or dropping regions", () => {
  const existing = Array.from({length: 12}, (_, i) => volume("old-" + i));
  const source = [model("one", 0, [volume("cut")]), model("two", 0, existing)];
  assert.throws(() => movePrintablesPreservingVolumes(source, ["one"]), /capacity/);
  assert.equal(source[0].modifier_volumes.length, 1);
  assert.equal(source[1].modifier_volumes.length, 12);
});

test("transferred assembly membership cannot leave singleton groups", () => {
  const assembly = "assembly:regression";
  const source = [
    model("one", 0, [volume("cut", assembly)], assembly),
    model("two", 40),
  ];
  const {remaining, moving} = movePrintablesPreservingVolumes(source, ["one"]);
  assert.equal(moving[0].assembly_id, null);
  assert.equal(remaining[0].modifier_volumes[0].assembly_id, null);
});


test("legacy parent-local modifiers travel with their printable instead of becoming free regions", () => {
  const local = {...volume("legacy"), coordinate_space: undefined};
  const source = [model("one", 0, [local]), model("two", 80, [])];
  const {remaining, moving} = movePrintablesPreservingVolumes(source, ["one"]);
  assert.equal(moving[0].modifier_volumes[0].id, "legacy");
  assert.deepEqual(remaining[0].modifier_volumes, []);
});
