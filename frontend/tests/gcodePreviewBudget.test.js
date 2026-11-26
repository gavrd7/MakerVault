import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { progressiveLayerBatchSize } from "../src/utils/gcodePreviewBudget.js";

describe("progressive full-model G-code preview sizing", () => {
  it("preserves the normal 64-layer request on small prints", () => {
    assert.equal(progressiveLayerBatchSize(99, 120000), 64);
  });
  it("shrinks heavy requests rather than dropping later layers", () => {
    assert.equal(progressiveLayerBatchSize(240, 12000000), 2);
    assert.equal(progressiveLayerBatchSize(3, 9000000), 1);
  });
  it("handles unknown source size conservatively", () => {
    assert.equal(progressiveLayerBatchSize(0, 0), 1);
    assert.equal(progressiveLayerBatchSize(240, undefined), 64);
  });
});
