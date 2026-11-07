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
