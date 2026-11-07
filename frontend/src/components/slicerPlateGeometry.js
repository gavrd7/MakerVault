/** Conservative XY axis-aligned envelope of a centred STL after Z rotation.
 * Preview-only: excludes printer keep-outs, extrusion clearance, supports and Z.
 */
export function plateEnvelope(item, dimensions) {
  const x = Number(item.x_mm), y = Number(item.y_mm);
  const width = Number(dimensions?.width), depth = Number(dimensions?.depth);
  const scale = Number(item.scale_percent) / 100;
  const angle = Number(item.rotation_deg) * Math.PI / 180;
  if (![x,y,width,depth,scale,angle].every(Number.isFinite) ||
      width <= 0 || depth <= 0 || scale <= 0) return null;
  const hx = scale * (Math.abs(Math.cos(angle)) * width + Math.abs(Math.sin(angle)) * depth) / 2;
  const hy = scale * (Math.abs(Math.sin(angle)) * width + Math.abs(Math.cos(angle)) * depth) / 2;
  return { minX: x-hx, maxX: x+hx, minY: y-hy, maxY: y+hy };
}

export function plateExtentWarning(item, dimensions, sizeX, sizeY) {
  const envelope = plateEnvelope(item, dimensions);
  if (!envelope || !Number.isFinite(sizeX) || !Number.isFinite(sizeY) || sizeX <= 0 || sizeY <= 0)
    return "Geometry or plate dimensions unavailable";
  return envelope.minX < -sizeX/2 || envelope.maxX > sizeX/2 ||
    envelope.minY < -sizeY/2 || envelope.maxY > sizeY/2
    ? "Estimated XY footprint extends beyond the displayed plate" : "";
}

/** Non-overlapping conservative 2D footprints, with optional clearance. */
export function plateFootprintsOverlap(a, aDims, b, bDims, clearance = 0) {
  const left = plateEnvelope(a, aDims), right = plateEnvelope(b, bDims);
  if (!left || !right) return null;
  return left.minX < right.maxX + clearance &&
    left.maxX + clearance > right.minX &&
    left.minY < right.maxY + clearance &&
    left.maxY + clearance > right.minY;
}

/** Deterministic shelf-like packing by footprint. No geometry or profile data is modified.
 * All positions are centred on the displayed plate, and rotation/scale are respected.
 * Failure does not change the original arrangement. This is a preview only; native
 * print exclusions, actual polygon and toolhead clearance still need verification.
 */
export function autoArrangePlate(objects, dimensions, bedX, bedY, clearance = 5) {
  if (!Array.isArray(objects) || !Number.isFinite(bedX) || !Number.isFinite(bedY) ||
      bedX <= 0 || bedY <= 0 || !Number.isFinite(clearance) || clearance < 0)
    return { error: "Build plate dimensions are unavailable." };
  const placed = [];
  for (const item of objects) {
    const envelope = plateEnvelope({ ...item, x_mm: 0, y_mm: 0 }, dimensions?.[item.instance_id]);
    if (!envelope) return { error: "Model dimensions are still loading. Try arranging again after the preview appears." };
    const width = envelope.maxX - envelope.minX, depth = envelope.maxY - envelope.minY;
    if (width > bedX || depth > bedY)
      return { error: "A model is larger than the available rectangular build plate." };
    const candidatesX = [-bedX / 2 + width / 2];
    const candidatesY = [-bedY / 2 + depth / 2];
    for (const other of placed) {
      const bounds = plateEnvelope(other, dimensions[other.instance_id]);
      candidatesX.push(bounds.maxX + clearance + width / 2);
      candidatesY.push(bounds.maxY + clearance + depth / 2);
    }
    let found = null;
    // Scan low Y, then X, keeping a deterministic bottom-left arrangement.
    const candidates = [];
    for (const y of candidatesY) for (const x of candidatesX) candidates.push({x, y});
    candidates.sort((a,b) => a.y - b.y || a.x - b.x);
    for (const {x,y} of candidates) {
      const candidate = {...item, x_mm: Math.round(x * 100) / 100, y_mm: Math.round(y * 100) / 100};
      if (plateExtentWarning(candidate, dimensions[item.instance_id], bedX, bedY)) continue;
      if (placed.some(other => plateFootprintsOverlap(candidate, dimensions[item.instance_id],
        other, dimensions[other.instance_id], clearance))) continue;
      found = candidate; break;
    }
    if (!found) return { error: "Not enough free build plate space to arrange all models without overlap." };
    placed.push(found);
  }
  // Centre the packed group on the displayed bed, without changing individual
  // model rotations/scales or the conservative clearance between footprints.
  if (placed.length) {
    const bounds = placed.map(row => plateEnvelope(row, dimensions[row.instance_id]));
    const minX = Math.min(...bounds.map(row => row.minX));
    const maxX = Math.max(...bounds.map(row => row.maxX));
    const minY = Math.min(...bounds.map(row => row.minY));
    const maxY = Math.max(...bounds.map(row => row.maxY));
    const offsetX = -(minX + maxX) / 2;
    const offsetY = -(minY + maxY) / 2;
    const centred = placed.map(row => ({
      ...row,
      x_mm: Math.round((row.x_mm + offsetX) * 100) / 100,
      y_mm: Math.round((row.y_mm + offsetY) * 100) / 100,
    }));
    if (centred.every(row => !plateExtentWarning(row, dimensions[row.instance_id], bedX, bedY)))
      return { objects: centred };
  }
  return { objects: placed };
}
