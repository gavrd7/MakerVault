/** Canonical independent non-printing volume storage for build-plate drafts.
 *
 * The interactive editor still accepts an object-local adapter for now.
 * Native serialisation remains fail-closed and never treats a volume as an STL.
 */
export const MAX_PLATE_VOLUMES = 48;
const PER_PRINTABLE = 12;

export function splitPlateVolumes(objects, orphaned = []) {
  const models = [];
  const volumes = [];
  for (const object of objects || []) {
    const {modifier_volumes = [], ...model} = object;
    models.push(model);
    volumes.push(...modifier_volumes);
  }
  // When no printable remains, keep already-detached volumes. The caller
  // must provide an explicit volume deletion action to remove these.
  if (!models.length) volumes.push(...orphaned);
  if (volumes.length > MAX_PLATE_VOLUMES) throw new Error("Too many independent volumes on this plate.");
  const ids = new Set();
  for (const volume of volumes) {
    if (!volume?.id || ids.has(volume.id)) throw new Error("Duplicate or missing independent volume ID.");
    ids.add(volume.id);
  }
  return {models, volumes};
}

export function hydratePlateObjects(plate) {
  const source = plate?.objects || [];
  const models = source.map(row => ({...row, modifier_volumes: [...(row.modifier_volumes || [])]}));
  const separate = plate?.volumes || [];
  if (!separate.length || !models.length) return models;
  const existing = new Set(models.flatMap(row => row.modifier_volumes.map(v => v.id)));
  for (const volume of separate) {
    if (existing.has(volume.id)) continue;
    const candidates = models.filter(row => row.modifier_volumes.length < PER_PRINTABLE);
    candidates.sort((a, b) =>
      Math.hypot(Number(a.x_mm || 0) - Number(volume.x_mm || 0),
                 Number(a.y_mm || 0) - Number(volume.y_mm || 0))
      - Math.hypot(Number(b.x_mm || 0) - Number(volume.x_mm || 0),
                   Number(b.y_mm || 0) - Number(volume.y_mm || 0)));
    if (!candidates.length) throw new Error("Not enough printable models to edit all volumes on this plate.");
    candidates[0].modifier_volumes.push(volume);
    existing.add(volume.id);
  }
  return models;
}

export function canonicalPlate(plate) {
  const {models, volumes} = splitPlateVolumes(plate.objects || [], plate.volumes || []);
  return {...plate, objects: models, volumes};
}
