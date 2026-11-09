/** Reviewed, local-only native build-plate artwork.
 * Reuse artwork only for the same base printer and validated bed size.
 * New artwork must have its source, licence and orientation reviewed.
 */
const ARTWORK = [
  {
    manufacturer: "creality", model: "k1",
    excludedVariants: ["max", "c", "se", "pro", "plus"],
    x: 220, y: 220,
    asset: "/slicer-bed-art/creality-k1.svg",
    source: "OrcaSlicer 2.4.2 / Creality K1",
  },
  {
    manufacturer: "creality", model: "k2",
    excludedVariants: ["plus", "pro", "max", "se", "c"],
    x: 260, y: 260,
    asset: "/slicer-bed-art/creality-k2.svg",
    source: "OrcaSlicer 2.4.2 / Creality K2",
  },
];

/** "Combo" denotes a bundled material system, not a different build plate.
 * Remove it as a complete word anywhere in the profile name, but never
 * remove model variants such as Pro, Plus, Max, C or SE.
 */
export function normalizePrinterArtworkName(name) {
  return String(name || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/\bcombo\b/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function nativeBedArtwork(printerName, width, depth) {
  const name = normalizePrinterArtworkName(printerName);
  const x = Number(width), y = Number(depth);
  if (!name || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  const tokens = name.split(" ");
  const matched = ARTWORK.find(item => {
    const prefix = [item.manufacturer, item.model];
    if (tokens[0] !== prefix[0] || tokens[1] !== prefix[1]) return false;
    // Do not let K2 Pro / K2 Plus (etc.) inherit base K2 artwork,
    // including profiles with nozzle/process suffixes.
    if (tokens.slice(2).some(token => item.excludedVariants.includes(token))) return false;
    return Math.abs(x - item.x) < 0.5 && Math.abs(y - item.y) < 0.5;
  });
  return matched?.asset || null;
}
