// Shared filament family identity for catalogue presentation only.
// Source variant records retain their IDs, properties and physical spool references.
const COLOUR_WORDS = new Set(("black white grey gray silver red orange yellow green blue purple pink brown beige " +
  "cyan teal turquoise magenta violet indigo gold bronze copper ivory cream almond aquamarine " +
  "mint lime navy maroon burgundy fuchsia coral peach salmon tan sand khaki olive charcoal aqua klein military blush " +
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

/**
 * Detect candidate families using the whole catalogue, rather than assuming
 * that a shade always appears at the end of a product name. Matching is
 * display-only: never mutates source variants or their associated spools.
 *
 * Conservative threshold: within the same manufacturer AND material, two
 * names must share at least two significant tokens and differ by exactly one
 * extra token per name. Their shared tokens must comprise >= 2/3 of the
 * longer name. This catches "Line Cherry" / "Lemon Line", but deliberately
 * leaves ambiguous short names as separate products.
 */
const tokens = value => norm(value).match(/[a-z0-9]+(?:[.+-][a-z0-9]+)*/g) || [];
const signature = words => [...words].sort().join("|");
const compatible = (a,b) => norm(a.manufacturer)===norm(b.manufacturer) && norm(a.material)===norm(b.material);
export function buildFilamentFamilyIndex(filaments) {
  const result = new Map();
  const groups = new Map();
  for (const item of filaments) {
    const family = filamentFamily(item);
    const k = filamentFamilyKey(item);
    result.set(String(item.id), {key:k, family, shade:filamentVariantLabel(item)});
    if (!groups.has(k)) groups.set(k,[]);
    groups.get(k).push(item);
  }
  // Canonicalise word order for already-known shade removal.
  const tokenGroups = new Map();
  for(const [key,items] of groups) {
    const family = filamentFamily(items[0]);
    const sig = [norm(family.manufacturer),norm(family.material),signature(tokens(family.product))].join("|");
    if (!tokenGroups.has(sig)) tokenGroups.set(sig,[]);
    tokenGroups.get(sig).push(key);
  }
  for(const keys of tokenGroups.values()) {
    if(keys.length<2) continue;
    const chosen=keys.slice().sort((a,b)=>a.length-b.length || a.localeCompare(b))[0];
    for(const k of keys) for(const item of groups.get(k)) result.get(String(item.id)).key=chosen;
  }
  // Detect previously unknown shade words by agreement across independent
  // product descriptions. The differing word must be different on each side.
  const candidates=new Map();
  for(const [key,items] of groups){
    const f=filamentFamily(items[0]);
    const words=tokens(f.product);
    if(words.length<3) continue;
    for(let i=0;i<words.length;i++){
      const remainder=words.filter((_,n)=>n!==i);
      if(remainder.length<2) continue;
      const sig=[norm(f.manufacturer),norm(f.material),signature(remainder)].join("|");
      if(!candidates.has(sig)) candidates.set(sig,[]);
      candidates.get(sig).push({key,removed:words[i],remainder});
    }
  }
  const assigned=new Set();
  for(const matches of candidates.values()){
    const unique=[...new Map(matches.map(x=>[x.key,x])).values()];
    if(unique.length<2 || new Set(unique.map(x=>x.removed)).size<2) continue;
    // Prevent generic descriptions where changing one token changes the
    // product line. Require distinct exact-colour hex variants as evidence.
    const evidence=new Set(unique.flatMap(x=>groups.get(x.key).map(v=>norm(v.color_hex))).filter(Boolean));
    if(evidence.size<2) continue;
    const keys=unique.map(x=>x.key);
    if(keys.some(k=>assigned.has(k))) continue;
    const representative=unique.slice().sort((a,b)=>a.key.localeCompare(b.key))[0];
    const exemplar=filamentFamily(groups.get(representative.key)[0]);
    const family={...exemplar,product:representative.remainder.join(" ")};
    const canonical=[norm(family.manufacturer),norm(family.product),norm(family.material)].join("|");
    for(const match of unique) {
      assigned.add(match.key);
      for(const item of groups.get(match.key)) {
        const entry=result.get(String(item.id));
        entry.key=canonical; entry.family=family;
        entry.shade=entry.shade || match.removed;
      }
    }
  }
  return result;
}
