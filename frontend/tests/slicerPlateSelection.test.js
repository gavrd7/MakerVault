import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const file = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../src/components/SlicerPlateEditor.jsx");
const source = fs.readFileSync(file, "utf8");

test("auto-arrange clears explicit mesh highlighting without changing the controls", () => {
  assert.ok(source.includes('onChange(result.objects);'));
  assert.ok(source.includes('setSelected("");'));
  assert.ok(source.includes('mesh.material.emissive.set(item.instance_id === selected'));
  assert.ok(!source.includes('chosen?.instance_id || selected'));
  assert.ok(source.includes('|| objects[0] || null'));
});

test("plate movement retains stored preview colours and clears residual emission", () => {
  assert.ok(source.includes("mesh.material.color.set(item.color || PALETTE[0])"));
  assert.ok(source.includes("mesh.material.emissiveIntensity = item.instance_id === selected ? 0.18 : 0"));
});
