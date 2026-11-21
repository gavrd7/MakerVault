/** Read the server's exact engine/version capability declaration.
 * Native exporters remain disabled until real worker fixtures verify them.
 */
export const NATIVE_TOOL_FEATURES = Object.freeze({
  paint_colour: "colour_paint",
  paint_support: "support_paint",
  paint_seam: "seam_paint",
  paint_fuzzy: "fuzzy_skin_paint",
  variable_layers: "variable_layer_profile",
});
export const FEATURE_NAMES = Object.freeze({
  colour_paint: "Colour painting",
  support_paint: "Support painting",
  seam_paint: "Seam painting",
  fuzzy_skin_paint: "Selective fuzzy skin painting",
  variable_layer_profile: "Variable layer height",
});
export function engineFeature(engineRecord, version, feature) {
  return engineRecord?.feature_capabilities?.[version]?.[feature] ||
    engineRecord?.feature_capabilities?.default?.[feature] ||
    {status:"unverified",reason:"Native export has not been verified for this engine and version."};
}
export function usedNativeFeatures(plates) {
  const used = new Set();
  for(const plate of plates || []) {
    for(const model of plate?.objects || []) {
      for(const feature of Object.keys(FEATURE_NAMES)) {
        const value = model?.[feature];
        if(value && typeof value === "object" &&
          ["regions","faces","bands"].some(key =>
            Array.isArray(value[key]) ? value[key].length > 0 :
            value[key] && Object.keys(value[key]).length > 0))used.add(feature);
      }
    }
  }
  return [...used].sort();
}
export function engineCompatibilityIssues(engineRecord, version, plates) {
  return usedNativeFeatures(plates).map(feature => ({
    feature, label: FEATURE_NAMES[feature],
    ...engineFeature(engineRecord,version,feature),
  })).filter(entry => entry.status !== "verified");
}
