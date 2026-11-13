/** Strict Orca/Prusa-style layer-boundary parser for explicit G-code insertion.
 *
 * Preview segments are sampled, so they cannot determine a safe text offset.
 * Only the original complete source's native layer markers may be used.
 * Never infer a layer from a travel Z move, comment-only header, or line count.
 */
const MARKER = /^[ \t]*;[ \t]*(?:LAYER_CHANGE|LAYER:[ \t]*\d+)[ \t]*\r?$/gm;
const Z_MARKER = /^[ \t]*;[ \t]*Z:[ \t]*([-+]?\d+(?:\.\d+)?)[ \t]*\r?$/im;
const MAX_CODE_CHARS = 2048;
const MAX_CODE_LINES = 20;

export function layerBoundaries(source) {
  if (typeof source !== "string" || source.includes("\0")) throw new Error("G-code must be complete plain text.");
  const markers = Array.from(source.matchAll(MARKER));
  return markers.map((marker, index) => {
    const start = marker.index;
    const end = index + 1 < markers.length ? markers[index + 1].index : source.length;
    // Z must be part of this layer's metadata block, not a later
    // travel command or unrelated slicer header setting.
    const block = source.slice(start, Math.min(end, start + 1024)).split(/\r?\n/).slice(0, 12).join("\n");
    const zMatch = block.match(Z_MARKER);
    if (!zMatch) return null;
    const z = Number(zMatch[1]);
    return Number.isFinite(z) && z >= 0 ? { z, offset: start } : null;
  }).filter(Boolean);
}

export function insertGcodeAfterLayer(source, selectedZ, nextZ, commands) {
  if (typeof source !== "string" || !source || source.length > 32 * 1024 * 1024)
    throw new Error("The complete G-code exceeds the 32 MiB editing limit.");
  if (!Number.isFinite(selectedZ) || !Number.isFinite(nextZ) || nextZ <= selectedZ)
    throw new Error("Select a layer before the final layer.");
  if (typeof commands !== "string" || !commands.trim() ||
      commands.length > MAX_CODE_CHARS || commands.split(/\r?\n/).length > MAX_CODE_LINES ||
      /[\0\x01-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(commands))
    throw new Error("Enter up to 20 lines (2,048 characters) of plain-text G-code.");
  const boundaries = layerBoundaries(source);
  if (boundaries.length < 2)
    throw new Error("This G-code has no verifiable native layer markers; insertion is disabled.");
  const tolerance = 0.002;
  const matching = boundaries.map((item, index) => ({ ...item, index }))
    .filter(item => Math.abs(item.z - selectedZ) < tolerance);
  if (matching.length !== 1)
    throw new Error("Selected layer Z cannot be matched uniquely to complete G-code.");
  const selected = matching[0];
  const next = boundaries[selected.index + 1];
  if (!next || Math.abs(next.z - nextZ) >= tolerance)
    throw new Error("The next G-code layer does not match the visualiser; no edit was made.");
  const newline = source.includes("\r\n") ? "\r\n" : "\n";
  const clean = commands.trim().replace(/\r?\n/g, newline);
  const inserted = [
    "; MakerVault manual G-code insertion: after layer Z " + selected.z.toFixed(3),
    clean,
    "; End MakerVault manual insertion",
    "",
  ].join(newline);
  const output = source.slice(0, next.offset) + inserted + source.slice(next.offset);
  return { text: output, before: next.offset, code: inserted,
    line: source.slice(0, next.offset).split(/\r?\n/).length,
    selectedZ: selected.z, nextZ: next.z };
}
