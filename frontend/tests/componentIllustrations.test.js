import test from "node:test";
import assert from "node:assert/strict";
import { componentIllustrationKind, componentIllustrationLabel } from "../src/components/componentIllustrations.js";

test("switch form factors have distinct illustrations", () => {
  const examples = {
    "Mini toggle switch": "toggle-switch",
    "Rocker switch ON OFF": "rocker-switch",
    "3 pin slide switch": "slide-switch",
    "4-position rotary switch": "rotary-switch",
    "8 way DIP switch": "dip-switch",
    "6x6 tactile push button": "button",
    "Generic switch": "switch",
  };
  for (const [name, expected] of Object.entries(examples)) {
    assert.equal(componentIllustrationKind({ name }), expected, name);
  }
  assert.notEqual(componentIllustrationKind({ name: "toggle switch" }), "button");
});

test("passives and connectors use distinct illustrations", () => {
  for (const [name, expected] of Object.entries({
    "10k resistor": "resistor",
    "100uF electrolytic capacitor": "electrolytic-capacitor",
    "100nF ceramic capacitor": "capacitor",
    "JST-XH connector": "connector",
    "1N4148 diode": "diode",
    "MOSFET transistor": "transistor",
  })) {
    assert.equal(componentIllustrationKind({ name }), expected);
  }
});

test("every switch illustration has descriptive accessibility text", () => {
  for (const kind of ["toggle-switch", "rocker-switch", "slide-switch",
    "rotary-switch", "dip-switch", "button", "switch"]) {
    assert.ok(componentIllustrationLabel(kind).length > 6);
  }
});
