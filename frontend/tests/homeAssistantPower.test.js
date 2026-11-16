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
  assert.match(button, /body: \{action\}/);
  assert.match(button, /result\.state !== action/);
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
  assert.match(printing, /!addOnly && <div className="printerLiveActions"><PrinterPowerButton/);
  assert.match(button, /compact \? " isCompact"/);
});

test("settings are manual only, do not leak the token, and share printing settings", () => {
  assert.match(settings, /<HomeAssistantSettings \/>/);
  assert.match(haSettings, /token_configured/);
  assert.match(haSettings, /input type="password"/);
  assert.match(haSettings, /Test connection/);
  assert.doesNotMatch(haSettings, /onTimer|schedule|setInterval/);
});
