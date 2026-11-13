import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {spellingVariant,regionalSpellingText,installRegionalSpelling} from "../src/regionalSpelling.js";

test("British default, London, North America, and South America",()=>{
 assert.equal(spellingVariant(), "en-GB");
 assert.equal(spellingVariant("Europe/London"),"en-GB");
 assert.equal(spellingVariant("Europe/Paris"),"en-GB");
 assert.equal(spellingVariant("America/New_York"),"en-US");
 assert.equal(spellingVariant("America/Los_Angeles"),"en-US");
 assert.equal(spellingVariant("America/Toronto"),"en-US");
 assert.equal(spellingVariant("America/Mexico_City"),"en-US");
 assert.equal(spellingVariant("America/Sao_Paulo"),"en-GB");
 assert.equal(spellingVariant("America/Bogota"),"en-GB");
});
test("only whole visible spelling words are transformed; preserve casing",()=>{
 assert.equal(regionalSpellingText("Colour painting · colours and COLOURED", "America/Toronto"),
   "Color painting · colors and COLORED");
 assert.equal(regionalSpellingText("Color palette, colorful, coloring", "Europe/London"),
   "Colour palette, colourful, colouring");
 assert.equal(regionalSpellingText("ColorFabb color_hex #ff0000", "Europe/London"),
   "ColorFabb color_hex #ff0000");
 assert.equal(regionalSpellingText("Colour",null),"Colour");
});
test("global UI spelling installer and app-level configuration integration",()=>{
 const src=fs.readFileSync(new URL("../src/App.jsx",import.meta.url),"utf8");
 assert.match(src,/installRegionalSpelling\(document.body,config.timezone\)/);
 assert.match(src,/document.documentElement.lang=spellingVariant\(config.timezone\)/);
 assert.equal(typeof installRegionalSpelling,"function");
});
