import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const files = {
  orcaslicer: "public/slicer-engines/orcaslicer.svg",
  crealityprint: "public/slicer-engines/crealityprint.svg",
  bambustudio: "public/slicer-engines/bambustudio.svg",
  prusaslicer: "public/slicer-engines/prusaslicer.svg",
  snapmakerorca: "public/slicer-engines/snapmakerorca.svg",
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
    assert.ok(widget.includes("../assets/slicer-engines/" + engine + ".svg?raw"));
  }
  assert.match(workbench, /<SlicerEngineChoices[^>]*engines=/);
  assert.match(workbench, /mode="install"/);
  assert.match(widget, /data:image\/svg\+xml;charset=utf-8/);
  assert.match(widget, /encodeURIComponent\(svg\)/);
  assert.match(widget, /onError=\{\(\) => setFailed\(true\)\}/);
  assert.doesNotMatch(widget, /loading="lazy"/);
  assert.match(widget, /type="radio"/);
  assert.match(widget, /Installation not yet available/);
});

test("engine installation view links to instructions for existing MakerVault deployments", () => {
  const workbench = fs.readFileSync(path.join(frontend, "src/components/SlicerWorkbench.jsx"), "utf8");
  assert.match(workbench, /Adding the slicer service to an existing MakerVault installation/);
  assert.match(workbench, /slicer\.md#adding-the-slicer-container-to-an-existing-installation/);
  assert.match(workbench, /rel="noopener noreferrer"/);
  assert.match(workbench, /Docker socket access/);
});

test("mobile slicer engine cards keep native radio indicator compact and card tappable", () => {
  const css = fs.readFileSync(path.join(frontend, "src/styles.css"), "utf8");
  const widget = fs.readFileSync(path.join(frontend, "src/components/SlicerEngineChoices.jsx"), "utf8");
  const radio = css.match(/\.slicerEngineChoice input\[type="radio"\]\{([\s\S]*?)\}/);
  assert.ok(radio);
  assert.match(radio[1], /width:18px/);
  assert.match(radio[1], /height:18px/);
  assert.match(radio[1], /min-height:18px/);
  assert.match(css, /@media\(max-width:600px\)\{[\s\S]*?\.slicerEngineChoice\{display:flex;flex-direction:row/);
  assert.match(css, /\.slicerEngineChoice\{display:flex;flex-direction:row[^}]*min-height:64px/);
  assert.match(widget, /<label key=\{engine\.key\} className=/);
  assert.match(widget, /<input type="radio"/);
});
