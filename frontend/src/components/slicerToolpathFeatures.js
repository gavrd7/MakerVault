/**
 * Stable, semantic G-code line-type colours. Native Orca/Prusa/Cura labels
 * differ, so classify by meaning while retaining the original type label
 * for the legend. Unknown types remain visible, not silently discarded.
 */
export const FEATURE_COLOURS = Object.freeze({
  support: "#f59e0b",
  interface: "#fbbf24",
  outer: "#5eead4",
  inner: "#14b8a6",
  infill: "#60a5fa",
  solid: "#818cf8",
  top: "#c4b5fd",
  bridge: "#fb7185",
  skirt: "#9ca3af",
  other: "#cbd5e1",
});

export function featureFamily(feature = "") {
  const name = String(feature).trim().toLowerCase();
  if (/support.*(interface|roof|floor|contact)|interface.*support/.test(name)) return "interface";
  if (/support/.test(name)) return "support";
  if (/bridge|overhang/.test(name)) return "bridge";
  if (/outer wall|external perimeter|external wall|outer perimeter/.test(name)) return "outer";
  if (/inner wall|internal perimeter|inner perimeter|wall/.test(name)) return "inner";
  if (/top surface|top solid|top skin|top fill/.test(name)) return "top";
  if (/solid infill|internal solid|bottom surface|bottom solid/.test(name)) return "solid";
  if (/infill|fill|sparse/.test(name)) return "infill";
  if (/skirt|brim|raft|prime tower|wipe tower/.test(name)) return "skirt";
  return "other";
}

export function featureColour(feature) {
  return FEATURE_COLOURS[featureFamily(feature)];
}

export function featureMatchesFocus(feature, focus = "all") {
  if (focus === "all") return true;
  const family = featureFamily(feature);
  if (focus === "support") return family === "support" || family === "interface";
  if (focus === "walls") return family === "outer" || family === "inner";
  if (focus === "infill") return ["infill", "solid", "top", "bridge"].includes(family);
  return true;
}

export function hasFeatureFocus(features, focus) {
  return features.some(feature => featureMatchesFocus(feature, focus));
}
