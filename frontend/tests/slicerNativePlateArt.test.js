import test from "node:test";
import assert from "node:assert/strict";
import { nativeBedArtwork } from "../src/components/slicerNativePlateArt.js";

test("native K1 and K2 artwork requires exact base models and build areas", () => {
  assert.equal(nativeBedArtwork("Creality K1 (0.4 nozzle)", 220, 220),
    "/slicer-bed-art/creality-k1.svg");
  assert.equal(nativeBedArtwork("Creality K2 0.4 nozzle - Custom", 260, 260),
    "/slicer-bed-art/creality-k2.svg");
  for (const machine of ["Creality K1 Max", "Creality K1C", "Creality K2 Plus",
    "Creality K2 Pro", "Creality K2 Combo", "Other K2 0.4 nozzle"]) {
    assert.equal(nativeBedArtwork(machine, 260, 260), null, machine);
  }
  assert.equal(nativeBedArtwork("Creality K2 0.4 nozzle", 220, 220), null);
  assert.equal(nativeBedArtwork("Creality K1 (0.4 nozzle)", 260, 260), null);
  assert.equal(nativeBedArtwork("Creality K2 0.4 nozzle", NaN, 260), null);
});
