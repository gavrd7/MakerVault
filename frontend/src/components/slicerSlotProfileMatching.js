/** Safe, provider-neutral profile suggestions for loaded printer slots.
 * Only UNIQUE exact-product matches are auto-assigned. Material-only/generic
 * matches are suggestions requiring explicit operator approval.
 * Never infer logical tools or adjust CFS/AMS hardware.
 */
const normal = value => String(value || "").toLowerCase()
  .replace(/([a-z])\+/gi, "$1 plus") // PLA+ and PLA must not be treated as the same product
  .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
  .replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
const materialOf = value => {
  const tokens = normal(value).split(" ");
  // Longest/specific families first: PETG must not collapse into PET.
  return ["petg", "pctg", "pla", "abs", "asa", "tpu", "pva", "hips", "pc", "pa", "pet"]
    .find(kind => tokens.includes(kind)) || "";
};
const productOf = slot => normal(slot?.product_name || slot?.material_name || "");
const brandOf = slot => normal(slot?.manufacturer || slot?.brand || slot?.vendor || "");
const nameOf = profile => normal(String(profile?.name || "").split("@")[0]);
const qualifierOk = (profile, printer) => {
  const suffix = String(profile?.name || "").split("@").slice(1).join("@").trim();
  if (!suffix || /^system$/i.test(suffix)) return true;
  const terms = normal(suffix.replace(/\b\d+(?:\.\d+)?\s*(mm\s*)?nozzle\b/gi, " "))
    .split(" ").filter(v => v && !["all", "series", "combo", "mm"].includes(v));
  if (!terms.length) return true;
  const info = normal([printer?.manufacturer, printer?.brand, printer?.model, printer?.name]
    .filter(Boolean).join(" "));
  return terms.every(t => info.split(" ").includes(t));
};
const core = value => normal(value).replace(/^(generic|creality|bambu lab|bambu|esun|sunlu)\s+/, "");

export function matchLoadedSlotProfiles(slot, profiles, {
  printer = null, engine = "", version = "",
} = {}) {
  const product = productOf(slot);
  const family = materialOf(slot?.material) || materialOf(product);
  const brand = brandOf(slot);
  if (!product || !family) return { level: "unknown", suggestions: [] };
  const valid = (profiles || []).filter(p => p.kind === "filament"
    && p.engine === engine && p.engine_version === version
    && !p.is_dependency && qualifierOk(p, printer)
    && materialOf(String(p.name).split("@")[0]) === family);
  // Product variants (PLA Silk versus PLA Basic, PLA+ versus PLA) are NOT
  // interchangeable. An exact match requires the entire named product.
  const exact = valid.filter(p => {
    const label = nameOf(p);
    const bare = core(label);
    const requested = core(product);
    if (!(bare === requested || label === product)) return false;
    if (!brand || /^(generic|system)$/.test(brand)) return true;
    const profileLabel = normal(p.name);
    // A non-generic manufacturer must actually appear in the native profile
    // when a brand-specific exact match is claimed.
    return profileLabel.includes(brand);
  });
  if (exact.length === 1) return { level: "exact", profile: exact[0], suggestions: exact };
  if (exact.length > 1) return { level: "ambiguous", suggestions: exact };
  const suggested = valid.filter(p => {
    const label = nameOf(p);
    const full = core(product);
    const candidate = core(label);
    return candidate === full || candidate === family || label === "generic " + family;
  });
  return {
    level: suggested.length ? "fallback" : "missing",
    suggestions: suggested.slice(0, 5),
  };
}

export function slotProfileSearchTerm(slot) {
  const product = String(slot?.product_name || "").trim();
  const family = materialOf(slot?.material) || materialOf(product);
  return product.length >= 2 && product.length <= 80 ? product
    : family.toUpperCase();
}
