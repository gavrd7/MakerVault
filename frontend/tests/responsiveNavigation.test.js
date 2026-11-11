import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src");
const component = fs.readFileSync(path.join(root, "components/ResponsiveNav.jsx"), "utf8");
const app = fs.readFileSync(path.join(root, "App.jsx"), "utf8");
const styles = fs.readFileSync(path.join(root, "styles.css"), "utf8");

test("main navigation retains the same page choices and slicer availability rules", () => {
  assert.match(app, /<ResponsiveNav items=\{NAV\} selected=\{section\} onSelect=\{navigateSection\}/);
  assert.match(app, /isDisabled=\{n => n === "MakerVault Slicer"/);
  assert.match(component, /items\.map\(name => <button/);
  assert.match(component, /aria-current=\{selected === name \? "page"/);
  assert.match(component, /onClick=\{\(\) => onSelect\(name\)\}/);
});

test("arrows reflect measured content overflow and track scroll and resize", () => {
  assert.match(component, /nav\.scrollWidth - nav\.clientWidth/);
  assert.match(component, /nav\.scrollLeft > 2/);
  assert.match(component, /nav\.scrollLeft < max - 2/);
  assert.match(component, /nav\.addEventListener\("scroll", update/);
  assert.match(component, /new ResizeObserver\(update\)/);
  assert.match(component, /observer\?\.observe\(nav\)/);
  assert.match(component, /window\.addEventListener\("resize", update\)/);
  assert.match(component, /nav\.scrollBy\(/);
  assert.match(component, /aria-label="Show previous navigation options"/);
  assert.match(component, /aria-label="Show more navigation options"/);
});

test("active tab remains in view and arrows do not alter desktop nav", () => {
  assert.match(component, /getAttribute\("aria-current"\) === "page"/);
  assert.match(component, /window\.matchMedia\("\(min-width: 901px\)"\)/);
  assert.match(styles, /\.mobileNavOverflow\{display:contents\}/);
  assert.match(styles, /\.mobileNavArrow\{display:none\}/);
  assert.match(styles, /\.mobileNavArrow\.isVisible/);
  assert.match(styles, /@media\(max-width:900px\)/);
  assert.match(styles, /prefers-reduced-motion:reduce/);
});
