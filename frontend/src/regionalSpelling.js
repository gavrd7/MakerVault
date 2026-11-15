/**
 * Presentation-only spelling, based on the timezone selected during setup.
 * Never rewrite API values, saved records, presets, CSS, or technical keys.
 * Default is British English. The North American zone list is explicit so
 * America/Sao_Paulo and America/Bogota are not mistaken for North America.
 */
const NORTH_AMERICAN_ZONES = new Set([
  "America/New_York","America/Detroit","America/Kentucky/Louisville",
  "America/Indiana/Indianapolis","America/Chicago","America/Denver",
  "America/Phoenix","America/Los_Angeles","America/Anchorage",
  "America/Adak","America/Boise","America/Juneau","America/Nome",
  "America/Sitka","America/Yakutat","Pacific/Honolulu",
  "America/Toronto","America/Vancouver","America/Edmonton",
  "America/Winnipeg","America/Regina","America/Halifax",
  "America/Moncton","America/St_Johns","America/Whitehorse",
  "America/Yellowknife","America/Iqaluit","America/Rankin_Inlet",
  "America/Thunder_Bay","America/Nipigon","America/Montreal",
  "America/Mexico_City","America/Monterrey","America/Cancun",
  "America/Merida","America/Tijuana","America/Chihuahua",
  "America/Hermosillo","America/Mazatlan","America/Ojinaga",
  "America/Bahia_Banderas","America/Ciudad_Juarez",
  "America/Guatemala","America/Belize","America/Managua",
  "America/Costa_Rica","America/Panama","America/El_Salvador",
  "America/Tegucigalpa","America/Port-au-Prince","America/Havana",
  "America/Jamaica","America/Nassau","America/Puerto_Rico",
  "America/Santo_Domingo"
]);
const NORTH_AMERICAN_ALIASES = new Set([
  "US/Eastern","US/Central","US/Mountain","US/Pacific",
  "US/Alaska","US/Hawaii","Canada/Eastern","Canada/Central",
  "Canada/Mountain","Canada/Pacific","Canada/Atlantic",
  "Canada/Newfoundland","Mexico/General","Mexico/BajaNorte",
  "Mexico/BajaSur"
]);
export function spellingVariant(timezone){
  const zone=String(timezone||"").trim();
  return NORTH_AMERICAN_ZONES.has(zone)||NORTH_AMERICAN_ALIASES.has(zone)
    ? "en-US" : "en-GB";
}
const formsGB=["colour","colours","coloured","colouring","colourful","colourless"];
const formsUS=["color","colors","colored","coloring","colorful","colorless"];
const words=new RegExp("\\b("+[...formsGB,...formsUS].join("|")+")\\b","gi");
function preserveCase(source,replacement){
  if(source===source.toUpperCase())return replacement.toUpperCase();
  if(source[0]===source[0].toUpperCase())return replacement[0].toUpperCase()+replacement.slice(1);
  return replacement;
}
export function regionalSpellingText(value,timezone){
  if(typeof value!=="string")return value;
  const target=spellingVariant(timezone)==="en-US"?formsUS:formsGB;
  return value.replace(words,match=>{
    const index=formsGB.indexOf(match.toLowerCase());
    const alternative=index<0?formsUS.indexOf(match.toLowerCase()):index;
    return preserveCase(match,target[alternative]||match);
  });
}
/**
 * React-independent display layer for existing English UI strings. React owns
 * the elements and their events. We only convert visible text and explicitly
 * UI-facing attributes, including content in portal dialogs.
 * Skip editable content, code, scripts and user-entered input values.
 */
export function installRegionalSpelling(root,timezone){
  if(!root||typeof document==="undefined"||typeof MutationObserver==="undefined")
    return ()=>{};
  let stopped=false,scheduled=false;
  const pending=new Set();
  const ignored="script,style,code,pre,textarea,[contenteditable]:not([contenteditable='false']),[data-preserve-spelling]";
  function visit(node){
    if(node.nodeType===3){
      const parent=node.parentElement;
      if(!parent||parent.closest(ignored))return;
      const next=regionalSpellingText(node.nodeValue,timezone);
      if(next!==node.nodeValue)node.nodeValue=next;
      return;
    }
    if(node.nodeType!==1)return;
    const element=node;
    if(element.matches(ignored))return;
    for(const attr of ["placeholder","aria-label","title"]){
      if(element.hasAttribute(attr)){
        const before=element.getAttribute(attr),after=regionalSpellingText(before,timezone);
        if(before!==after)element.setAttribute(attr,after);
      }
    }
    for(const child of element.childNodes)visit(child);
  }
  function apply(){
    scheduled=false;
    if(stopped){pending.clear();return;}
    const nodes=[...pending];pending.clear();
    for(const node of nodes)if(node===root || root.contains(node))visit(node);
  }
  const observer=new MutationObserver(mutations=>{
    for(const mutation of mutations){
      if(mutation.type==="childList"){
        for(const child of mutation.addedNodes)pending.add(child);
      }else{
        pending.add(mutation.target);
      }
    }
    if(pending.size&&!scheduled){scheduled=true;queueMicrotask(apply);}
  });
  visit(root);
  observer.observe(root,{subtree:true,childList:true,characterData:true,attributes:true,
    attributeFilter:["placeholder","aria-label","title"]});
  return ()=>{stopped=true;pending.clear();observer.disconnect();};
}
