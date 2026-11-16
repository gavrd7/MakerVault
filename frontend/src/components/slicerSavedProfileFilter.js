/** Native profile names and metadata are left intact for the engine.
 * Only the presentation and selectable lists are simplified here.
 */
export function isInternalNativeProfile(profile) {
  if (profile?.is_dependency) return true;
  // Orca parent presets frequently end in @base or @BBL base even when no
  // imported child currently references them. These aren't user presets.
  const name = String(profile?.name || "");
  return /@\s*(?:(?:[\w.-]+(?:\s+[\w.-]+)*)\s+)?base\s*$/i.test(name);
}

export function readableNativeProfile(profile) {
  const name = String(profile?.name || "");
  if (isInternalNativeProfile(profile)) {
    return { name: name.replace(/\s*@\s*[^@]*\bbase\s*$/i,"").trim() || name,
      type: "Parent preset", internal: true };
  }
  if (/@\s*System\s*$/i.test(name)) {
    return { name: name.replace(/\s*@\s*System\s*$/i,"").trim(),
      type: "Generic preset", internal: false };
  }
  return { name, type: /@/.test(name) ? "Printer-specific preset" : "Preset",
    internal: false };
}

/** Show profiles for the exact worker engine/version. Base and inherited parent
 * profiles stay accessible only through the explicit management toggle.
 */
export function profilesForEngineVersion(profiles, engine, engineVersion, options = {}) {
  const showDependencies = Boolean(options.managing && options.showDependencies);
  return profiles.filter(profile =>
    profile.engine === engine &&
    profile.engine_version === engineVersion &&
    (!isInternalNativeProfile(profile) || showDependencies)
  );
}
