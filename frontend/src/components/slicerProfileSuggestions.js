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

// Profiles carrying an explicit K1/K2 machine suffix must not be silently
// applied to the other printer. Profiles with no such suffix remain candidates.
const machineSuffixCompatible = (profile, printer) => {
  if (!printer) return true;
  const chosen = words(printer.model || printer.name);
  const native = words(profile.name);
  const suffix = native.match(/\bk[12]\b/g);
  return !suffix || suffix.every(model => chosen.split(" ").includes(model));
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
  return machine || "Creality K1";
}
