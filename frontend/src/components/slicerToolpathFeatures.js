/**
 * Stable, semantic G-code line-type colours. Native Orca/Prusa/Cura labels
 * differ, so classify by meaning while retaining the original type label
 * for the legend. Unknown types remain visible, not silently discarded.
 */
export const FEATURE_COLOURS = Object.freeze({
  // High-contrast native-slicer-like palette, independent of engine labels.
  // Structural supports are green, shell walls warm orange, upper skin red.
  support: "#2fd442",
  interface: "#80e75a",
  outer: "#f47a36",
  inner: "#f4bf4d",
  infill: "#cf6799",
  solid: "#8164c9",
  top: "#e94c52",
  bridge: "#4baadf",
  skirt: "#4e84c6",
  other: "#b7c7d7",
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
  if (focus === "outer") return family === "outer";
  if (focus === "support") return family === "support" || family === "interface";
  if (focus === "walls") return family === "outer" || family === "inner";
  if (focus === "shell") return ["outer", "inner", "top", "bridge"].includes(family);
  if (focus === "infill") return ["infill", "solid", "top", "bridge"].includes(family);
  return true;
}

export function hasFeatureFocus(features, focus) {
  return features.some(feature => featureMatchesFocus(feature, focus));
}
