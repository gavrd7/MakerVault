/** Pure matching rules, independently testable without the bundler. */
const ARTWORK = [
  { manufacturer: "creality", model: "k1",
    excludedVariants: ["max", "c", "se", "pro", "plus"],
    x: 220, y: 220, id: "creality-k1" },
  { manufacturer: "creality", model: "k2",
    excludedVariants: ["plus", "pro", "max", "se", "c"],
    x: 260, y: 260, id: "creality-k2" },
];

export function normalizePrinterArtworkName(name) {
  return String(name || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/\bcombo\b/g, " ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function nativeBedArtworkId(printerName, width, depth) {
  const name = normalizePrinterArtworkName(printerName);
  const x = Number(width), y = Number(depth);
  if (!name || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  const tokens = name.split(" ");
  const match = ARTWORK.find(item =>
    tokens[0] === item.manufacturer && tokens[1] === item.model &&
    !tokens.slice(2).some(token => item.excludedVariants.includes(token)) &&
    Math.abs(x - item.x) < 0.5 && Math.abs(y - item.y) < 0.5);
  return match?.id || null;
}
