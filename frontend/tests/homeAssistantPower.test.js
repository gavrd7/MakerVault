import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components");
const read = name => fs.readFileSync(path.join(root, name), "utf8");
const button = read("PrinterPowerButton.jsx");
const assignment = read("PrinterPowerAssignment.jsx");
const dashboard = read("Dashboard.jsx");
const printing = read("PrintingPage.jsx");
const settings = read("SettingsPage.jsx");
const haSettings = read("HomeAssistantSettings.jsx");

test("power button is absent until server confirms integration and assignment", () => {
  assert.match(button, /setPower\(data\.available \? data\.state : null\)/);
  assert.match(button, /if \(power == null\) return null/);
  assert.match(button, /window\.confirm\(/);
  assert.match(button, /body: \{action, \.\.\.\(action === "off" \? \{confirm: true\}/);
  assert.match(button, /result\.state !== action/);
  assert.doesNotMatch(button, /setInterval\(/);
});

test("button confirms by animation rather than red inline text", () => {
  assert.match(button, /feedback \? " feedback-" \+ feedback/);
  assert.match(button, /setFeedback\("success"\)/);
  assert.match(button, /setFeedback\("error"\)/);
  assert.match(button, /onAnimationEnd=/);
  assert.match(button, /printerPowerGlyph/);
  assert.doesNotMatch(button, /className="printerPowerError"/);
  assert.match(button, /printerPowerSrOnly/);
});

test("button labels describe the action rather than the current state", () => {
  assert.match(button, /power === "on" \? "Turn off" : power === "off" \? "Turn on"/);
  assert.match(button, /Home Assistant reports power/);
  assert.match(button, /power === "on" \? "off" : "on"/);
});

test("saving a switch assignment immediately refreshes the matching printer control", () => {
  assert.match(assignment, /window\.dispatchEvent\(new CustomEvent\("makervault:printer-power-assignment-changed"/);
  assert.match(assignment, /detail: \{printerId\}/);
  assert.match(button, /window\.addEventListener\("makervault:printer-power-assignment-changed", onAssignmentChange\)/);
  assert.match(button, /String\(event\.detail\?\.printerId\) === String\(printerId\)/);
  assert.match(button, /window\.removeEventListener\("makervault:printer-power-assignment-changed", onAssignmentChange\)/);
  assert.match(button, /window\.addEventListener\("focus", onFocus\)/);
  assert.doesNotMatch(button, /setInterval\(/);
});

test("Home Assistant assignment is opt-in and hidden when disabled", () => {
  assert.match(assignment, /if \(!item\?\.enabled \|\| !item\.token_configured\) return/);
  assert.match(assignment, /if \(!available\) return null/);
  assert.match(assignment, /power\/assignment\//);
  assert.match(assignment, /No smart plug assigned/);
});

test("one reusable power control is used across printer views", () => {
  assert.match(dashboard, /<PrinterPowerButton printerId=\{printer\.id\}/);
  assert.match(printing, /<PrinterPowerButton printerId=\{printer\.id\}/);
  assert.match(printing, /<PrinterPowerAssignment printerId=\{printer\.id\}/);
  assert.match(printing, /!addOnly && <PrinterPowerButton printerId=/);
  assert.match(button, /compact \? " isCompact"/);
});

test("token help opens a compact dialog with official Home Assistant guidance", () => {
  assert.match(haSettings, /How do I get a token\?/);
  assert.match(haSettings, /showTokenHelp && <Modal title="Home Assistant access token"/);
  assert.match(haSettings, /User profile|your user profile/);
  assert.match(haSettings, /https:\/\/www\.home-assistant\.io\/docs\/authentication\//);
  assert.match(haSettings, /rel="noopener noreferrer"/);
});

test("settings are manual only, do not leak the token, and share printing settings", () => {
  assert.match(settings, /<HomeAssistantSettings \/>/);
  assert.match(haSettings, /token_configured/);
  assert.match(haSettings, /input type="password"/);
  assert.match(haSettings, /Test connection/);
  assert.doesNotMatch(haSettings, /setInterval\(|setTimeout\(/);
});
