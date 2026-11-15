/**
 * Only list profiles belonging to the exact engine installation currently
 * selected in the slicer. Profiles from other engine versions remain stored
 * and are never deleted or converted automatically.
 */
export function profilesForEngineVersion(profiles, engine, engineVersion, options = {}) {
  const showDependencies = Boolean(options.managing && options.showDependencies);
  return profiles.filter(profile =>
    profile.engine === engine &&
    profile.engine_version === engineVersion &&
    (!profile.is_dependency || showDependencies)
  );
}
