/** Conservative XY axis-aligned envelope of a centred STL after Z rotation.
 * Preview-only: excludes printer keep-outs, extrusion clearance, supports and Z.
 */
export function plateEnvelope(item, dimensions) {
  const x = Number(item.x_mm), y = Number(item.y_mm);
  const width = Number(dimensions?.width), depth = Number(dimensions?.depth);
  const legacyScale = Number(item.scale_percent) / 100;
  const xyz = item.scale_xyz_percent;
  const sx = Array.isArray(xyz) ? Number(xyz[0]) / 100 : legacyScale;
  const sy = Array.isArray(xyz) ? Number(xyz[1]) / 100 : legacyScale;
  const angle = Number(item.rotation_deg) * Math.PI / 180;
  if (![x,y,width,depth,sx,sy,angle].every(Number.isFinite) ||
      width <= 0 || depth <= 0 || sx <= 0 || sy <= 0) return null;
  const hx = (Math.abs(Math.cos(angle)) * sx * width + Math.abs(Math.sin(angle)) * sy * depth) / 2;
  const hy = (Math.abs(Math.sin(angle)) * sx * width + Math.abs(Math.cos(angle)) * sy * depth) / 2;
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
  // Packed coordinates are rounded to hundredths and trig operations
  // introduce floating-point error at 90/180 degrees. Treat distances
  // equal to requested clearance as non-overlapping, rather than flagging
  // them as a collision due to sub-micron numeric noise.
  const epsilon = 1e-7;
  return left.minX < right.maxX + clearance - epsilon &&
    left.maxX + clearance > right.minX + epsilon &&
    left.minY < right.maxY + clearance - epsilon &&
    left.maxY + clearance > right.minY + epsilon;
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
    // Start slightly inside the printable edge. Real STL bounds are often
    // fractional millimetres: rounding the first centre to 0.01 mm could
    // otherwise move the object *outside* the plate by a fraction of a mm.
    const inset = 0.02;
    const candidatesX = [-bedX / 2 + width / 2 + inset];
    const candidatesY = [-bedY / 2 + depth / 2 + inset];
    for (const other of placed) {
      const bounds = plateEnvelope(other, dimensions[other.instance_id]);
      candidatesX.push(bounds.maxX + clearance + width / 2 + inset);
      candidatesY.push(bounds.maxY + clearance + depth / 2 + inset);
    }
    let found = null;
    // Scan low Y, then X, keeping a deterministic bottom-left arrangement.
    const candidates = [];
    for (const y of candidatesY) for (const x of candidatesX) candidates.push({x, y});
    candidates.sort((a,b) => a.y - b.y || a.x - b.x);
    for (const {x,y} of candidates) {
      // Snap towards the free (positive) side, never towards the previous
      // model or past the lower plate edge. Floating-point noise is neutralised
      // before rounding to the editor's hundredth-millimetre precision.
      const candidate = {...item,
        x_mm: Math.ceil(x * 100 - 1e-7) / 100,
        y_mm: Math.ceil(y * 100 - 1e-7) / 100,
      };
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
