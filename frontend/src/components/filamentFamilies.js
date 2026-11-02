// Shared filament family identity for catalogue presentation only.
// Source variant records retain their IDs, properties and physical spool references.
const COLOUR_WORDS = new Set(("black white grey gray silver red orange yellow green blue purple pink brown beige " +
  "cyan teal turquoise magenta violet indigo gold bronze copper ivory cream almond aquamarine " +
  "mint lime navy maroon burgundy fuchsia coral peach salmon tan sand khaki olive charcoal " +
  "chocolate coffee lavender lilac amber bone blush forest grass midnight royal electric " +
  "fluorescent metallic translucent transparent natural clear").split(" "));
const norm = value => String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
const cleanEdge = value => String(value || "").replace(/^[\s–—-]+|[\s–—-]+$/g, "").trim();
function isShadePhrase(value) {
  const words = norm(value).replace(/[()]/g, " ").split(/\s+/).filter(Boolean);
  return words.length > 0 && words.length <= 4 && words.every(word => COLOUR_WORDS.has(word));
}
function colourFromName(item) {
  const colour = String(item.color_name || "").trim();
  if (colour) return colour;
  const name = String(item.name || "").trim();
  const split = name.match(/\s+[-–—]\s+([^–—-]+)$/);
  if (split && isShadePhrase(split[1])) return split[1].trim();
  const words = name.split(/\s+/);
  for (let length = Math.min(4, words.length); length >= 1; length--) {
    const tail = words.slice(-length).join(" ");
    if (isShadePhrase(tail)) return tail;
  }
  return isShadePhrase(name) ? name : "";
}
export function filamentFamily(item) {
  const maker = String(item.manufacturer || "").trim();
  const material = String(item.material || "").trim();
  let name = String(item.name || "").trim();
  if (maker && norm(name).startsWith(norm(maker) + " ")) name = cleanEdge(name.slice(maker.length));
  const color = colourFromName(item);
  if (color && norm(name) === norm(color)) name = "";
  else if (color && norm(name).endsWith(norm(color))) {
    name = cleanEdge(name.slice(0, -color.length));
  } else if (color && norm(name).startsWith(norm(color) + " ")) {
    name = cleanEdge(name.slice(color.length));
  }
  // If the source provides only a colour as its name, do not invent a brand
  // product family; group under the known material and retain raw variant.
  name = name || material || "Unclassified";
  return {manufacturer: maker || "Unknown", product: name, material};
}
export function filamentFamilyKey(item) {
  const family = filamentFamily(item);
  return [family.manufacturer, family.product, family.material].map(norm).join("|");
}
export function filamentVariantLabel(item) {
  return String(item.color_name || "").trim() || colourFromName(item) || "";
}
