import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const files = {
  orcaslicer: "public/slicer-engines/orcaslicer.svg",
  crealityprint: "public/slicer-engines/crealityprint.svg",
};

test("official engine SVGs are bundled locally with safe static markup", () => {
  for (const [engine, relative] of Object.entries(files)) {
    const source = fs.readFileSync(path.join(frontend, relative), "utf8");
    assert.match(source, /<svg\b/);
    assert.match(source, /<\/svg>/);
    assert.doesNotMatch(source, /<script\b|<foreignObject\b|onload\s*=|<image\b/i);
    assert.ok(source.length < 20000, engine + " logo should remain lightweight");
  }
});

test("one reusable engine branding component is used by both selection and installation views", () => {
  const widget = fs.readFileSync(path.join(frontend, "src/components/SlicerEngineChoices.jsx"), "utf8");
  const workbench = fs.readFileSync(path.join(frontend, "src/components/SlicerWorkbench.jsx"), "utf8");
  for (const engine of Object.keys(files)) {
    assert.ok(widget.includes(engine));
    assert.ok(widget.includes("/slicer-engines/" + engine + ".svg"));
  }
  assert.match(workbench, /<SlicerEngineChoices[^>]*engines=/);
  assert.match(workbench, /mode="install"/);
  assert.match(widget, /type="radio"/);
  assert.match(widget, /Installation not yet available/);
});
