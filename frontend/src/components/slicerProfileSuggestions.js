/** Safe workbench suggestions: engine/version scoped, never assert that
 * matching a name proves an engine-native preset is compatible for slicing.
 */
export function spoolMaterial(spool) {
  const text = String(spool?.material || "").toUpperCase().trim();
  for (const family of ["PETG", "PLA", "ABS", "ASA", "TPU", "PCTG", "PC", "PA", "PET", "PVA", "HIPS"]) {
    if (new RegExp("(^|[^A-Z])" + family + "([^A-Z]|$)").test(text)) return family;
  }
  return "";
}

const words = text => String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const profileMatchesMaterial = (profile, material) => {
  if (!material) return true;
  const text = words(profile.name).toUpperCase();
  return new RegExp("(^| )" + material + "( |$)").test(text);
};

// A native process/filament profile may carry a machine qualifier after @.
// Never infer compatibility from K1/K2 names alone; treat ANY explicit machine
// qualifier as requiring a match with the selected printer's identity.
const machineSuffixCompatible = (profile, printer) => {
  if (!printer) return true;
  const raw = String(profile.name || "");
  const at = raw.indexOf("@");
  if (at === -1) return true; // Generic material/process profile, still unverified.
  const qualifier = raw.slice(at + 1)
    .replace(/\b\d+(?:\.\d+)?\s*(?:mm\s*)?nozzle\b/gi, " ");
  const expected = words(qualifier).split(" ")
    .filter(t => t && !["all", "nozzle", "mm", "series", "combo"].includes(t));
  if (!expected.length) return true;
  const available = new Set(words([
    printer.manufacturer, printer.brand, printer.model, printer.name,
  ].filter(Boolean).join(" ")).split(" "));
  return expected.every(t => available.has(t));
};

const printerMatch = (profile, printer, nozzle) => {
  if (!printer) return true;
  const model = words(printer.model || printer.name);
  if (!model) return true;
  const label = words(profile.name);
  const terms = model.split(" ").filter(word => word.length >= 2 && !["creality", "bambu", "prusa", "printer", "series", "combo", "cfs"].includes(word));
  const matchModel = terms.length > 0 && terms.every(word => label.split(" ").includes(word));
  if (!matchModel) return false;
  const nativeNozzle = String(profile.name).match(/\b([0-9]+(?:\.[0-9]+)?)\s*(?:mm\s*)?nozzle\b/i);
  const size = Number(nozzle);
  return !nativeNozzle || !Number.isFinite(size) || Math.abs(Number(nativeNozzle[1]) - size) < 0.001;
};

export function chooseSuggestedProfile(profiles, jobs, { engine, version, kind, printer = null, nozzle = "0.4", material = "" }) {
  const choices = profiles.filter(p => p.engine === engine && p.engine_version === version && p.kind === kind);
  const filtered = choices.filter(p => kind === "filament"
    ? profileMatchesMaterial(p, material) && machineSuffixCompatible(p, printer)
    : kind === "printer" ? printerMatch(p, printer, nozzle)
    : machineSuffixCompatible(p, printer));
  if (!filtered.length) return null;
  const explicit = filtered.find(p => p.is_default);
  if (explicit) return { profile: explicit, reason: "default" };
  const last = (jobs || []).find(job =>
    job.engine === engine && job.engine_version === version &&
    (!printer || String(job.printer?.id || "") === String(printer.id)) &&
    filtered.some(p => p.id === job[kind + "_profile_id"])
  );
  if (last) {
    const prior = filtered.find(p => p.id === last[kind + "_profile_id"]);
    if (prior) return { profile: prior, reason: "last used" };
  }
  if (kind === "process") {
    const standard = filtered.find(p => /(?:^|\D)0[.]20\s*mm|0[.]2\s*mm/i.test(p.name) && /standard|quality|normal/i.test(p.name))
      || filtered.find(p => /(?:^|\D)0[.]20\s*mm|0[.]2\s*mm/i.test(p.name));
    if (standard) return { profile: standard, reason: "0.20 mm starter" };
  }
  if (kind === "filament" && material) {
    const generic = filtered.find(p => /generic/i.test(p.name));
    if (generic) return { profile: generic, reason: material + " match" };
    return { profile: filtered[0], reason: material + " match" };
  }
  if (kind === "printer" && printer && filtered.length === 1) return { profile: filtered[0], reason: "printer match" };
  return null;
}

export function defaultOfficialSearch(kind, { printer, spool, nozzle } = {}) {
  if (kind === "filament") return spoolMaterial(spool) || "Generic PLA";
  if (kind === "process") return "0.20mm";
  const machine = String(printer?.model || printer?.name || "").trim().slice(0, 80);
  return machine || "0.4 nozzle";
}

/** Suggest an upstream catalogue only from a recognizable printer identity.
 * The operator must still review native profile compatibility. */
export function suggestOfficialVendor(printer, vendors = []) {
  if (!Array.isArray(vendors) || !vendors.length) return "";
  if (vendors.length === 1) return vendors[0].id;
  const tokens = [
    printer?.manufacturer, printer?.brand, printer?.model, printer?.name,
  ].filter(Boolean).map(value => String(value).toLowerCase());
  const aliases = { bbl: ["bambu", "bambulab"], flsun: ["flsun"], ratrig: ["rat rig", "ratrig"] };
  const match = vendors.find(v => {
    const id = String(v.id || "").toLowerCase();
    const forms = [id, ...(aliases[id] || [])];
    return forms.some(alias => tokens.some(t => t === alias ||
      t.startsWith(alias + " ") || t.startsWith(alias + "-")));
  });
  return match?.id || vendors.find(v => v.id === "Custom")?.id || vendors[0].id;
}
