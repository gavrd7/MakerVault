import test from "node:test";
import assert from "node:assert/strict";
import {canonicalPlate, hydratePlateObjects, updateCanonicalPlate} from "../src/components/slicerPlateVolumes.js";

const region = (id, coordinate_space = "world") => ({
  id, kind: "negative", coordinate_space, x_mm: 0, y_mm: 0,
});
const model = (...modifier_volumes) => ({
  instance_id: "printable-1", x_mm: 0, y_mm: 0, modifier_volumes,
});

test("world-space regions save independently while legacy parent-local data stays with its mesh", () => {
  const plate = canonicalPlate({
    id: "plate-1", objects: [model(region("old", "local"), region("free"))],
  });
  assert.deepEqual(plate.volumes.map(v => v.id), ["free"]);
  assert.deepEqual(plate.objects[0].modifier_volumes.map(v => v.id), ["old"]);
  const reopened = hydratePlateObjects(plate);
  assert.deepEqual(reopened[0].modifier_volumes.map(v => v.id), ["old", "free"]);
});

test("editing or deleting an independent world volume updates canonical plate storage", () => {
  const plate = canonicalPlate({objects: [model(region("free"))]});
  const changed = updateCanonicalPlate(plate, [model({...region("free"), x_mm: 45})]);
  assert.equal(changed.volumes[0].x_mm, 45);
  const removed = updateCanonicalPlate(changed, [model()]);
  assert.deepEqual(removed.volumes, []);
});

test("detached volumes survive an empty printable plate and reattach after import", () => {
  const volume = region("cut");
  const empty = canonicalPlate({objects: [], volumes: [volume]});
  assert.deepEqual(empty.volumes, [volume]);
  assert.deepEqual(hydratePlateObjects(empty), []);
  const restored = updateCanonicalPlate(empty, [model()]);
  assert.deepEqual(restored.volumes, [volume]);
  assert.deepEqual(hydratePlateObjects(restored)[0].modifier_volumes.map(v => v.id), ["cut"]);
});

test("reopening canonical saved plates does not duplicate independently persisted volumes", () => {
  const saved = {objects: [{instance_id: "one", x_mm: 0, y_mm: 0}], volumes: [region("cut")]};
  const reopened = canonicalPlate(saved);
  assert.equal(reopened.volumes.length, 1);
  const edited = updateCanonicalPlate(reopened, hydratePlateObjects(reopened));
  assert.equal(edited.volumes.length, 1);
});

test("a model-local legacy modifier is never silently migrated to plate coordinates", () => {
  const old = region("old", "local");
  const converted = canonicalPlate({objects: [model(old)], volumes: [region("free")]});
  assert.deepEqual(converted.objects[0].modifier_volumes, [old]);
  assert.deepEqual(converted.volumes.map(v => v.id), ["free"]);
});

test("excess detached volumes are retained rather than dropped when fewer printable hosts exist", () => {
  const many = Array.from({length: 14}, (_, i) => region("free-" + i));
  const stored = canonicalPlate({objects: [], volumes: many});
  const updated = updateCanonicalPlate(stored, [model()]);
  assert.equal(updated.volumes.length, 14);
  assert.equal(hydratePlateObjects(updated)[0].modifier_volumes.length, 12);
});


test("final printable deletion retains orphan volumes but removes explicitly selected regions", () => {
  const assembly = "assembly:test-123";
  const first = {...region("free"), assembly_id: assembly};
  const second = {...region("cut"), assembly_id: assembly};
  const plate = canonicalPlate({objects: [model(first, second)]});
  const retained = updateCanonicalPlate(plate, [], {removedVolumeIds: ["cut"]});
  assert.deepEqual(retained.objects, []);
  assert.deepEqual(retained.volumes.map(v => v.id), ["free"]);
  assert.equal(retained.volumes[0].assembly_id, null);
});

test("adding a printable to an existing saved plate never duplicates or re-parents free volumes", () => {
  const free = {...region("existing-cut"), x_mm: 90, y_mm: 90};
  const saved = canonicalPlate({objects: [model()], volumes: [free]});
  const another = {...model(), instance_id: "printable-2", x_mm: 90, y_mm: 90};
  const edited = updateCanonicalPlate(saved, [...hydratePlateObjects(saved), another]);
  assert.deepEqual(edited.volumes.map(volume => volume.id), ["existing-cut"]);
  const hydrated = hydratePlateObjects(edited);
  assert.deepEqual(hydrated[0].modifier_volumes.map(volume => volume.id), ["existing-cut"]);
  assert.deepEqual(hydrated[1].modifier_volumes, []);
  assert.equal(new Set(edited.volumes.map(volume => volume.id)).size, 1);
  const reopened = canonicalPlate(edited);
  assert.deepEqual(reopened.volumes.map(volume => volume.id), ["existing-cut"]);
});

test("fresh empty plate contains no remnants from an old saved draft", () => {
  const saved = canonicalPlate({objects: [model(region("modifier"))], volumes: [region("negative")]});
  assert.equal(saved.volumes.length, 2);
  const fresh = canonicalPlate({id: "plate-1", objects: [], volumes: []});
  const added = updateCanonicalPlate(fresh, [model()]);
  assert.deepEqual(added.volumes, []);
  assert.deepEqual(hydratePlateObjects(added)[0].modifier_volumes, []);
});
