/** Engine-native plate families; availability is always printer-profile scoped. */
export const ORCA_PLATE_TYPES = [
  ["default", "Native / profile default"],
  ["cool", "Smooth Cool Plate"],
  ["engineering", "Engineering Plate"],
  ["high_temp", "Smooth High Temp Plate"],
  ["textured_pei", "Textured PEI Plate"],
  ["textured_cool", "Textured Cool Plate"],
  ["supertack", "SuperTack Plate"],
];

/** Never advertise unknown plate types as supported by a selected printer. */
export function plateOptions(engine, bedTypes) {
  if (!["orcaslicer", "crealityprint"].includes(engine)) return ORCA_PLATE_TYPES.slice(0, 1);
  const supported = Array.isArray(bedTypes?.supported) ? bedTypes.supported : null;
  if (supported?.length)
    return ORCA_PLATE_TYPES.filter(([key]) => supported.includes(key));
  // Explicitly loaded but incomplete/custom profile: expose manual choices,
  // never describe them as confirmed physical hardware capabilities. The
  // backend still validates the selected filament's bed temperature.
  if (bedTypes && !bedTypes.default && engine === "orcaslicer")
    return ORCA_PLATE_TYPES.slice(1);
  return ORCA_PLATE_TYPES.slice(0, 1);
}
