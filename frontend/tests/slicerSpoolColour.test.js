import test from "node:test";
import assert from "node:assert/strict";
import { slicerSpoolHex, recolorUnmodifiedPlate } from "../src/components/slicerSpoolColour.js";

test("only validated recorded hex colours are accepted", () => {
  assert.equal(slicerSpoolHex({ color_hex: " #a1B2c3 " }), "#A1B2C3");
  assert.equal(slicerSpoolHex({ color_name: "Grey" }), null);
  assert.equal(slicerSpoolHex({ color_hex: "red" }), null);
  assert.equal(slicerSpoolHex({ color_hex: "#fff" }), null);
});
test("spool selection preserves manually edited object colours", () => {
  const models = [{ instance_id: "a", color: "#000000" }, { instance_id: "b", color: "#F59E0B" }];
  assert.deepEqual(recolorUnmodifiedPlate(models, "#AABBCC", new Set(["b"])), [
    { instance_id: "a", color: "#AABBCC" }, { instance_id: "b", color: "#F59E0B" },
  ]);
  assert.equal(recolorUnmodifiedPlate(models, null), models);
});
