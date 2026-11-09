/** Reviewed, local-only native build-plate art assets.
 * Add new manufacturers/models only after auditing source, licence,
 * native dimensions and intended orientation. Never derive a resource URL
 * from a profile name or load arbitrary profile-provided external paths.
 */
const ARTWORK = [
  {
    model: /^creality\s+k1\b(?!\s*(?:max|c|se)\b)/i,
    x: 220, y: 220,
    asset: "/slicer-bed-art/creality-k1.svg",
    source: "OrcaSlicer 2.4.2 / Creality K1",
  },
  {
    model: /^creality\s+k2\b(?!\s*(?:plus|pro|max|se|combo)\b)/i,
    x: 260, y: 260,
    asset: "/slicer-bed-art/creality-k2.svg",
    source: "OrcaSlicer 2.4.2 / Creality K2",
  },
];

export function nativeBedArtwork(printerName, width, depth) {
  const name = String(printerName || "").trim();
  if (!Number.isFinite(Number(width)) || !Number.isFinite(Number(depth))) return null;
  const matched = ARTWORK.find(item =>
    item.model.test(name) &&
    Math.abs(Number(width) - item.x) < 0.5 &&
    Math.abs(Number(depth) - item.y) < 0.5
  );
  return matched?.asset || null;
}
