/** Three.js Euler XYZ rotation matrix, also used by the native 3MF exporter. */
export function plateRotationMatrix(item) {
  const [rx, ry] = (item?.rotation_xyz_deg || [0, 0]).map(v => Number(v) * Math.PI / 180);
  const rz = Number(item?.rotation_deg || 0) * Math.PI / 180;
  const [cx, sx, cy, sy, cz, sz] = [
    Math.cos(rx), Math.sin(rx), Math.cos(ry), Math.sin(ry), Math.cos(rz), Math.sin(rz),
  ];
  return [
    [cy * cz, -cy * sz, sy],
    [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
    [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
  ];
}

/** Conservative oriented cuboid envelope including tilts around X/Y.
 * STL source geometry is centred in X/Y and rests on local Z=0.
 * Preview-only: excludes printer keep-outs, extrusion clearance and supports.
 */
export function plateEnvelope(item, dimensions) {
  const x = Number(item.x_mm), y = Number(item.y_mm);
  const width = Number(dimensions?.width), depth = Number(dimensions?.depth);
  const hasHeight = dimensions?.height != null;
  const height = hasHeight ? Number(dimensions.height) : 0;
  const tilt = item.rotation_xyz_deg || [0, 0];
  if (!hasHeight && tilt.some(v => Math.abs(Number(v)) > 1e-7)) return null;
  const legacy = Number(item.scale_percent) / 100;
  const xyz = item.scale_xyz_percent;
  const scale = Array.isArray(xyz) ? xyz.map(v => Number(v) / 100) : [legacy, legacy, legacy];
  const rot = plateRotationMatrix(item);
  if (![x, y, width, depth, height, ...scale, ...rot.flat()].every(Number.isFinite) ||
      width <= 0 || depth <= 0 || height < 0 || scale.some(v => v <= 0)) return null;
  const half = [width * scale[0] / 2, depth * scale[1] / 2, height * scale[2] / 2];
  const centre = [x + rot[0][2] * half[2], y + rot[1][2] * half[2]];
  const hx = rot[0].reduce((total, v, i) => total + Math.abs(v) * half[i], 0);
  const hy = rot[1].reduce((total, v, i) => total + Math.abs(v) * half[i], 0);
  return { minX: centre[0]-hx, maxX: centre[0]+hx, minY: centre[1]-hy, maxY: centre[1]+hy };
}

/** Read-only preview measurement of the selected STL after saved XYZ scale and
 * Z rotation. Dimensions are derived from the mesh's local bounds; XY values
 * are a conservative rectangular envelope, not precise face/edge metrology.
 * No scene state, imported meshes or slicing settings are changed.
 */
export function plateModelMeasurement(item, dimensions) {
  const footprint = plateEnvelope(item, dimensions);
  const rawHeight = Number(dimensions?.height);
  const xyz = item?.scale_xyz_percent;
  const zScale = Array.isArray(xyz) ? Number(xyz[2]) / 100 :
    Number(item?.scale_percent) / 100;
  if (!footprint || !Number.isFinite(rawHeight) || rawHeight <= 0 ||
      !Number.isFinite(zScale) || zScale <= 0) return null;
  const rotation = plateRotationMatrix(item);
  const rawWidth = Number(dimensions?.width), rawDepth = Number(dimensions?.depth);
  const sx = Array.isArray(xyz) ? Number(xyz[0]) / 100 : Number(item?.scale_percent) / 100;
  const sy = Array.isArray(xyz) ? Number(xyz[1]) / 100 : Number(item?.scale_percent) / 100;
  const height = Math.abs(rotation[2][0]) * rawWidth * sx +
    Math.abs(rotation[2][1]) * rawDepth * sy +
    Math.abs(rotation[2][2]) * rawHeight * zScale;
  if (!Number.isFinite(height)) return null;
  return {
    width: footprint.maxX - footprint.minX,
    depth: footprint.maxY - footprint.minY,
    height,
    ...footprint,
  };
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

/** Place one new copy without rearranging any existing objects.
 * Candidate centres include gaps beside every occupied footprint, not only
 * free space in the source model's row. Complexity is capped to 200 entries.
 */
export function findFreeDuplicatePosition(item,objects,dimensions,bedX,bedY,clearance=3) {
  const dims=dimensions[item.instance_id];
  const footprint=plateEnvelope({...item,x_mm:0,y_mm:0},dims);
  if(!footprint)return null;
  const w=footprint.maxX-footprint.minX,d=footprint.maxY-footprint.minY;
  const margin=0.06;
  const xs=[-bedX/2+w/2+margin,0,bedX/2-w/2-margin];
  const ys=[-bedY/2+d/2+margin,0,bedY/2-d/2-margin];
  for(const other of objects) {
    const envelope=plateEnvelope(other,dimensions[other.instance_id]);
    if(!envelope) return null;
    xs.push(envelope.minX-w/2-clearance-margin,envelope.maxX+w/2+clearance+margin);
    ys.push(envelope.minY-d/2-clearance-margin,envelope.maxY+d/2+clearance+margin);
  }
  const candidates=[];
  for(const y of ys)for(const x of xs) {
    if(!Number.isFinite(x)||!Number.isFinite(y))continue;
    const candidate={...item,x_mm:Math.round(x*100)/100,y_mm:Math.round(y*100)/100};
    if(plateExtentWarning(candidate,dims,bedX,bedY))continue;
    const dist=(x-item.x_mm)**2+(y-item.y_mm)**2;
    candidates.push({candidate,dist});
  }
  candidates.sort((a,b)=>a.dist-b.dist||a.candidate.y_mm-b.candidate.y_mm||a.candidate.x_mm-b.candidate.x_mm);
  for(const {candidate} of candidates)
    if(objects.every(other=>plateFootprintsOverlap(candidate,dims,other,
      dimensions[other.instance_id],clearance)===false))return candidate;
  return null;
}

/** Prefer a compact, centred rectangular cluster over a long edge-hugging
 * shelf. Try different numbers of models per row, retain each model's current
 * rotation/scale and validate the same conservative envelopes as the editor.
 * If no regular layout fits, the legacy free-space search remains available.
 */
function compactCentredLayout(objects, dimensions, bedX, bedY, clearance) {
  if (!objects.length || objects.length > 200) return null;
  const shapes = [];
  for (const item of objects) {
    const zero = plateEnvelope({ ...item, x_mm: 0, y_mm: 0 }, dimensions?.[item.instance_id]);
    if (!zero) return null;
    const width = zero.maxX - zero.minX, depth = zero.maxY - zero.minY;
    if (width > bedX || depth > bedY) return null;
    shapes.push({ item, width, depth,
      offsetX: (zero.minX + zero.maxX) / 2,
      offsetY: (zero.minY + zero.maxY) / 2 });
  }
  let best = null;
  // A small positive placement tolerance keeps 0.01 mm rounding from eroding
  // the requested inter-model gap. It is not an added printer-specific margin.
  const gap = clearance + 0.04;
  const margin = Math.min(2, Math.max(0.05, Math.min(bedX, bedY) * 0.005));
  for (let count = 1; count <= shapes.length; count++) {
    const rows = [];
    for (let i = 0; i < shapes.length; i += count) {
      const parts = shapes.slice(i, i + count);
      rows.push({ parts,
        width: parts.reduce((sum, shape) => sum + shape.width, 0) + gap * (parts.length - 1),
        depth: Math.max(...parts.map(shape => shape.depth)) });
    }
    const spanX = Math.max(...rows.map(row => row.width));
    const spanY = rows.reduce((sum, row) => sum + row.depth, 0) + gap * (rows.length - 1);
    if (spanX + 2 * margin > bedX || spanY + 2 * margin > bedY) continue;
    const placed = [];
    let y = -spanY / 2;
    for (const row of rows) {
      let x = -row.width / 2;
      for (const shape of row.parts) {
        const proposedX = x + shape.width / 2 - shape.offsetX;
        const proposedY = y + row.depth / 2 - shape.offsetY;
        placed.push({ ...shape.item,
          x_mm: Math.round(proposedX * 100) / 100,
          y_mm: Math.round(proposedY * 100) / 100 });
        x += shape.width + gap;
      }
      y += row.depth + gap;
    }
    if (placed.some(model => plateExtentWarning(model, dimensions[model.instance_id], bedX, bedY)))
      continue;
    let overlaps = false;
    for (let i = 0; i < placed.length && !overlaps; i++)
      for (let j = 0; j < i; j++)
        if (plateFootprintsOverlap(placed[i], dimensions[placed[i].instance_id],
          placed[j], dimensions[placed[j].instance_id], clearance) !== false) {
          overlaps = true;
          break;
        }
    if (overlaps) continue;
    // Minimise the longest occupied span relative to the available bed,
    // then favour less overall area. This promotes a 2×2 group of Benchies
    // over an excessively long 1×4 row or column without assuming that
    // every heated bed has a particular temperature map.
    const ratioX = spanX / bedX, ratioY = spanY / bedY;
    const score = Math.max(ratioX, ratioY) + 0.2 * ratioX * ratioY +
      0.025 * Math.abs(ratioX - ratioY);
    if (!best || score < best.score - 1e-9)
      best = { score, objects: placed };
  }
  return best?.objects || null;
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
  const compact = compactCentredLayout(objects, dimensions, bedX, bedY, clearance);
  if (compact) return { objects: compact };
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


/** Euclidean 3D distance between two picked surface points (STL units: mm). */
export function measurementDistance(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== 3 || b.length !== 3 ||
      ![...a, ...b].every(Number.isFinite)) return null;
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** 3D circumcircle through three explicitly selected non-collinear points.
 * A three-point construction is not equivalent to automatic CAD circle
 * recognition, nor does it establish whether the mesh contains a true circle.
 */
export function measurementCircle(a, b, c) {
  const ab = measurementDistance(a, b), bc = measurementDistance(b, c);
  const ca = measurementDistance(c, a);
  if (ab === null || bc === null || ca === null) return null;
  const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
  const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
  const cross = [
    uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx,
  ];
  const area2 = Math.hypot(...cross);
  if (!Number.isFinite(area2) || area2 <= 1e-7 * Math.max(ab * bc, bc * ca, ca * ab, 1))
    return null;
  const radius = ab * bc * ca / (2 * area2);
  if (!Number.isFinite(radius) || radius > 1e7) return null;
  return { radius, diameter: radius * 2, circumference: 2 * Math.PI * radius };
}

export function measurementFormat(mm, unit = "mm") {
  if (!Number.isFinite(mm)) return "—";
  return (unit === "in" ? mm / 25.4 : mm).toFixed(3) + " " + (unit === "in" ? "in" : "mm");
}
