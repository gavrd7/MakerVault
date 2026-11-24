/** Plate transfer adapter until native plate-level volume storage is available.
 * Free volumes are not part of a printable model. Never implicitly relocate
 * them when a printable instance is moved to another plate.
 */
export function movePrintablesPreservingVolumes(objects, selectedIds, perModelLimit = 12) {
  const ids = new Set(selectedIds);
  const moving = objects.filter(row => ids.has(row.instance_id));
  if (!moving.length) return {remaining: objects, moving: []};
  const remaining = objects.filter(row => !ids.has(row.instance_id))
    .map(row => ({...row, modifier_volumes: [...(row.modifier_volumes || [])]}));
  const detached = moving.flatMap(row => (row.modifier_volumes || [])
    .filter(volume => volume.coordinate_space === "world"));
  // Canonical plate-level persistence retains detached regions even if every
  // printable leaves the source plate. Rehoming is needed only for the old
  // object-local editor adapter while other printable meshes remain.
  if (remaining.length) for (const volume of detached) {
    const destinations = remaining.filter(row => row.modifier_volumes.length < perModelLimit)
      .sort((a, b) => Math.hypot(Number(a.x_mm) - volume.x_mm, Number(a.y_mm) - volume.y_mm)
        - Math.hypot(Number(b.x_mm) - volume.x_mm, Number(b.y_mm) - volume.y_mm));
    if (!destinations.length) {
      throw new Error("No free volume storage capacity on the original plate; move or delete volumes first.");
    }
    destinations[0].modifier_volumes.push(volume);
  }
  const normalize = rows => {
    const counts = new Map();
    rows.flatMap(row => [row, ...(row.modifier_volumes || [])]).forEach(row => {
      if (row.assembly_id) counts.set(row.assembly_id, (counts.get(row.assembly_id) || 0) + 1);
    });
    const part = row => row.assembly_id && counts.get(row.assembly_id) < 2
      ? {...row, assembly_id: null} : row;
    return rows.map(row => ({
      ...part(row),
      modifier_volumes: (row.modifier_volumes || []).map(part),
    }));
  };
  return {
    remaining: normalize(remaining),
    moving: normalize(moving.map(row => ({...row,
      modifier_volumes: (row.modifier_volumes || []).filter(volume => volume.coordinate_space !== "world")}))),
  };
}
