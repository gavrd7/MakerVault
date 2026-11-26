import { describe, expect, it } from "vitest";
import { progressiveLayerBatchSize } from "../src/utils/gcodePreviewBudget";

describe("progressive full-model G-code preview sizing", () => {
  it("preserves the normal 64-layer request on small prints", () => {
    expect(progressiveLayerBatchSize(99, 120000)).toBe(64);
  });
  it("shrinks heavy requests rather than dropping later layers", () => {
    expect(progressiveLayerBatchSize(240, 12000000)).toBe(15);
    expect(progressiveLayerBatchSize(3, 9000000)).toBe(1);
  });
  it("handles unknown source size conservatively", () => {
    expect(progressiveLayerBatchSize(0, 0)).toBe(1);
    expect(progressiveLayerBatchSize(240, undefined)).toBe(64);
  });
});
