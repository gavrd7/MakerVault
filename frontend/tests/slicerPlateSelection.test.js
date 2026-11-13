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
  assert.ok(source.includes('mesh.material.emissive.set(toolMode === "paint_colour" ? "#000000" : conflictIds.has(item.instance_id)'));
  assert.ok(!source.includes('chosen?.instance_id || selected'));
  assert.ok(source.includes('|| objects[0] || null'));
});

test("plate movement retains stored preview colours and clears residual emission", () => {
  assert.ok(source.includes("paintPreview(mesh, item, PALETTE[0])"));
  assert.ok(source.includes("mesh.material.emissiveIntensity = toolMode === \"paint_colour\" ? 0 : conflictIds.has(item.instance_id) ? 0.72 :"));
});

test("plate height follows the model-control rail instead of fixed viewport height", () => {
  const css = fs.readFileSync(path.join(path.dirname(file), "../styles.css"), "utf8");
  assert.match(css, /\.slicerPlateWorkspace\{[^}]*align-items:stretch/);
  assert.match(css, /\.slicerPlateCanvasColumn\{[^}]*display:flex;flex-direction:column/);
  assert.match(css, /\.slicerPlateCanvas\{[^}]*flex:1 1 auto;[^}]*height:auto/);
  assert.match(source, /\{footer && <div className="slicerPlateFooter">/);
});
