// Stable, dependency-free classification for locally bundled illustrations.
// Type and name identify form factor; a generic "switch" must not become a button.
export function componentIllustrationKind({ type = "", category = "", name = "" } = {}) {
  const text = `${type} ${name} ${category}`.toLowerCase();
  const has = (...terms) => terms.some(term => text.includes(term));
  if (has("dip switch", "dip-switch")) return "dip-switch";
  if (has("rocker switch", "rocker-switch")) return "rocker-switch";
  if (has("slide switch", "slider switch", "slide-switch")) return "slide-switch";
  if (has("toggle switch", "lever switch", "toggle-switch")) return "toggle-switch";
  if (has("rotary switch", "selector switch", "rotary-switch")) return "rotary-switch";
  if (has("tactile", "tact switch", "push button", "pushbutton", "momentary button", "button")) return "button";
  if (has("switch")) return "switch";
  if (has("potentiometer", "trimmer")) return "potentiometer";
  if (has("electrolytic capacitor")) return "electrolytic-capacitor";
  if (has("ceramic capacitor", "capacitor")) return "capacitor";
  if (has("resistor")) return "resistor";
  if (has("diode")) return "diode";
  if (has("transistor", "mosfet")) return "transistor";
  if (has("connector", "header", "jst", "terminal")) return "connector";
  if (has("led", "lighting")) return "led";
  if (has("relay")) return "relay";
  return "component";
}
export const componentIllustrationLabel = kind => ({
  "dip-switch": "DIP switch", "rocker-switch": "Rocker switch",
  "slide-switch": "Slide switch", "toggle-switch": "Toggle switch",
  "rotary-switch": "Rotary switch", button: "Tactile push button",
  switch: "Generic switch", potentiometer: "Potentiometer",
  "electrolytic-capacitor": "Electrolytic capacitor", capacitor: "Capacitor",
  resistor: "Resistor", diode: "Diode", transistor: "Transistor",
  connector: "Connector", led: "LED", relay: "Relay", component: "Electronic component",
})[kind] || "Electronic component";
