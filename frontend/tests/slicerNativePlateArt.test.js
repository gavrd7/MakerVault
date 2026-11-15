import test from "node:test";
import assert from "node:assert/strict";
import { nativeBedArtworkId, normalizePrinterArtworkName } from "../src/components/slicerNativePlateMatcher.js";
import fs from "node:fs";

test("Combo is a removable whole-word descriptor in any position", () => {
  assert.equal(normalizePrinterArtworkName("Creality K2 COMBO 0.4 nozzle - Custom"), "creality k2 0 4 nozzle custom");
  assert.equal(normalizePrinterArtworkName("Creality Combo K2"), "creality k2");
  assert.equal(normalizePrinterArtworkName("Creality K2 Combobox"), "creality k2 combobox");
});

test("base K1 and K2 artwork applies to Combo and nozzle/profile variants", () => {
  for (const name of ["Creality K2", "Creality K2 Combo", "Creality K2 COMBO 0.4 nozzle - Custom", "Creality Combo K2"]) {
    assert.equal(nativeBedArtworkId(name, 260, 260), "creality-k2", name);
  }
  assert.equal(nativeBedArtworkId("Creality K1 (0.4 nozzle)", 220, 220), "creality-k1");
  assert.equal(nativeBedArtworkId("Creality K1 Combo", 220, 220), "creality-k1");
});

test("distinct model variants never inherit base model artwork", () => {
  for (const name of ["Creality K2 Pro", "Creality K2 Plus", "Creality K2 Max",
    "Creality K2 SE", "Creality K2 Pro Combo", "Creality K2 Combo Plus"]) {
    assert.equal(nativeBedArtworkId(name, 260, 260), null, name);
  }
  for (const name of ["Creality K1 Max", "Creality K1C", "Creality K1 SE", "Creality K1 Pro"]) {
    assert.equal(nativeBedArtworkId(name, 220, 220), null, name);
  }
});

test("manufacturer and build volume still have to match validated assets", () => {
  assert.equal(nativeBedArtworkId("Creality K2 Combo", 300, 300), null);
  assert.equal(nativeBedArtworkId("Creality K2 Combo", 260, 260.8), null);
  assert.equal(nativeBedArtworkId("Other K2 Combo", 260, 260), null);
  assert.equal(nativeBedArtworkId("Creality K2 Combo", NaN, 260), null);
  assert.equal(nativeBedArtworkId("Creality K1", 260, 260), null);
});

test("native plate texture assets are bundled in the Vite module, never loaded from root-relative paths", () => {
  const src = fs.readFileSync(new URL("../src/components/slicerNativePlateArt.js", import.meta.url), "utf8");
  assert.ok(src.includes('creality-k1.svg?raw'));
  assert.ok(src.includes('creality-k2.svg?raw'));
  assert.ok(src.includes('data:image/svg+xml'));
  assert.ok(!src.includes('asset: "/slicer-bed-art/'));

});

test("failed official artwork keeps the user's toggle selected and reports a useful fallback", () => {
  const editor = fs.readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");
  assert.ok(!editor.includes("setShowNativeArtwork(false)"));
  assert.ok(editor.includes("setNativeArtworkError("));
  assert.ok(editor.includes("profileArtwork && bundledArtwork"));
  assert.ok(editor.includes('role="status" className="integrationError"'));
});

test("native official artwork uses high-resolution SVG rasterisation and shows a 3D plate", () => {
  const editor = fs.readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");
  assert.match(editor, /canvas.width = 2048/);
  assert.match(editor, /canvas.height = 2048/);
  assert.match(editor, /const canvas = bedTexture\.image/);
  assert.doesNotMatch(editor, /bedArtwork = new THREE\.Mesh/);
  assert.match(editor, /new THREE.CanvasTexture\(canvas\)/);
  assert.match(editor, /texture.anisotropy/);
  assert.match(editor, /bevelEnabled: true/);
  assert.match(editor, /const drawReferenceGrid = !showNativeArtwork/);
  assert.match(editor, /plateBody.visible = false/);
  assert.match(editor, /artworkTextureController\?\.abort\(\)/);
  assert.match(editor, /nativeBedMesh\.userData\.decorativeBed = true/);
});

test("fallback 3D plate includes authentic bundled MakerVault logo without a broken URL", () => {
  const editor = fs.readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");
  const logo = fs.readFileSync(new URL("../src/assets/slicer-bed-art/makervault-official-logo.svg", import.meta.url), "utf8");
  assert.match(editor, /makervault-official-logo\.svg\?raw/);
  assert.match(editor, /encodeURIComponent\(makerVaultLogoSvg\)/);
  assert.doesNotMatch(editor, /logo\.src = "\/slicer-bed-art\//);
  assert.match(editor, /new THREE\.ExtrudeGeometry\(plateShape/);
  assert.match(editor, /bevelEnabled: true/);
  assert.ok(logo.includes("<svg"));
  assert.ok(logo.includes("data:image/png;base64,"));
});


test("official art is default and the print sheet sits over a separate wider machine bed", () => {
  const editor = fs.readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");
  assert.match(editor, /useState\(true\)/);
  assert.match(editor, /const artworkPath = showNativeArtwork/);
  assert.match(editor, /plateBody\.scale\.set\(1\.035, 1\.035, 1\)/);
  assert.match(editor, /plateRim\.position\.z = -2\.1/);
  assert.match(editor, /plateBody\.position\.z = -plateDepth/);
  assert.match(editor, /polygonOffset: true/);
  assert.match(editor, /plateBody\.material\.forEach\(material => material\.dispose\(\)\)/);
});


test("MakerVault fallback logo is composited without a white rectangular badge", () => {
  const editor = fs.readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(editor, /ctx\.fillRect\(361, 875, 302, 109\)/);
  assert.match(editor, /iconCtx\.getImageData/);
  assert.match(editor, /pixels\[index \* 4 \+ 3\] = 0/);
  assert.match(editor, /ctx\.drawImage\(iconCanvas, 371, 890, 78, 87\)/);
  assert.match(editor, /ctx\.fillText\("Maker", labelStart, labelTop\)/);
  assert.match(editor, /ctx\.fillText\("Vault", labelStart \+ ctx\.measureText\("Maker"\)\.width, labelTop\)/);
});


test("fallback build plate grid is continuous through the logo's transparent area", () => {
  const editor = fs.readFileSync(new URL("../src/components/SlicerPlateEditor.jsx", import.meta.url), "utf8");
  assert.match(editor, /if \(inside\(x, \(y \+ yy\) \/ 2\)\) target\.push/);
  assert.match(editor, /if \(inside\(\(x \+ xx\) \/ 2, y\)\) target\.push/);
  assert.doesNotMatch(editor, /useMakerVaultBed &&\s*\(x \+ bedX \/ 2\)/);
  assert.doesNotMatch(editor, /useMakerVaultBed &&\s*\(y \+ bedY \/ 2\)/);
});
