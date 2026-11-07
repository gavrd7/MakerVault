/** Physical spool colours are a visual default, never a native filament preset.
 * Accept only known canonical hex values; never guess from colour names.
 */
export function slicerSpoolHex(spool) {
  const raw = spool?.color_hex;
  if (typeof raw !== "string") return null;
  const value = raw.trim();
  return /^#[0-9a-fA-F]{6}$/.test(value) ? value.toUpperCase() : null;
}

export function recolorUnmodifiedPlate(objects, hex, manuallyEdited = new Set()) {
  if (!hex) return objects;
  return objects.map(object => manuallyEdited.has(object.instance_id)
    ? object : { ...object, color: hex });
}
