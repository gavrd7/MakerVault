import test from "node:test";
import assert from "node:assert/strict";
import { findSlicedRequirement } from "../src/utils/gcodeMapping.js";

test("a single used slicer filament 3 still resolves to PLA for slot validation", () => {
  const used = [{ tool_index: 2, material: "PLA", color_hex: "#ffffff" }];
  const requirement = findSlicedRequirement(used, 2);
  assert.equal(requirement?.material, "PLA");
  assert.equal(requirement?.color_hex, "#ffffff");
  assert.equal(findSlicedRequirement(used, 0), undefined);
});

test("sparse multicolour tool IDs are looked up by identity, not array position", () => {
  const used = [
    { tool_index: 0, material: "PLA", color_hex: "#ffffff" },
    { tool_index: 3, material: "PETG", color_hex: "#000000" },
  ];
  assert.equal(findSlicedRequirement(used, 3)?.material, "PETG");
  assert.equal(findSlicedRequirement(used, 1), undefined);
});
