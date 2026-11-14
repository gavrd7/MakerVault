import test from "node:test";
import assert from "node:assert/strict";
import { spoolMaterial, chooseSuggestedProfile, defaultOfficialSearch, suggestOfficialVendor } from "../src/components/slicerProfileSuggestions.js";

const make = (id, kind, name, extra={}) => ({
  id, kind, name, engine:"crealityprint", engine_version:"7.3.0", is_default:false, ...extra,
});
const printer={id:"p1",model:"Creality K1",name:"My K1"};

test("recognise a known PETG spool without accidentally classifying PLA",()=>{
  assert.equal(spoolMaterial({material:"PETG-HF"}),"PETG");
  assert.equal(spoolMaterial({material:"PLA+"}),"PLA");
  assert.equal(spoolMaterial({material:"Unknown"}),"");
  assert.equal(defaultOfficialSearch("filament",{spool:{material:"PETG"}}),"PETG");
});

test("explicit defaults take precedence over last-use and generic 0.20 process",()=>{
  const profiles=[
    make("a","process","0.20mm Standard"),
    make("b","process","0.16mm Fine",{is_default:true}),
  ];
  const result=chooseSuggestedProfile(profiles,[{engine:"crealityprint",engine_version:"7.3.0",process_profile_id:"a"}],
    {engine:"crealityprint",version:"7.3.0",kind:"process"});
  assert.equal(result.profile.id,"b");
  assert.equal(result.reason,"default");
});

test("last-used only matches same printer and exact engine version",()=>{
  const profiles=[make("k1","printer","Creality K1 0.4 nozzle"),
    make("k2","printer","Creality K2 0.4 nozzle")];
  const result=chooseSuggestedProfile(profiles,[
    {engine:"crealityprint",engine_version:"7.3.0",printer:{id:"p2"},printer_profile_id:"k2"},
    {engine:"crealityprint",engine_version:"7.3.0",printer:{id:"p1"},printer_profile_id:"k1"},
  ],{engine:"crealityprint",version:"7.3.0",kind:"printer",printer,nozzle:"0.4"});
  assert.equal(result.profile.id,"k1");
  assert.equal(chooseSuggestedProfile(profiles,[],{engine:"crealityprint",version:"7.3.0",kind:"printer",printer:{id:"p3",model:"Creality K3"},nozzle:"0.4"}),null);
});

test("K2 Combo uses the base K2 native machine profile",()=>{
  const chosen=chooseSuggestedProfile([
    make("k2","printer","Creality K2 0.4 nozzle"),
  ],[],{engine:"crealityprint",version:"7.3.0",kind:"printer",
        printer:{id:"k2",model:"Creality K2 Combo"},nozzle:"0.4"});
  assert.equal(chosen?.profile.id,"k2");
  assert.equal(chooseSuggestedProfile([
    make("k2","printer","Creality K2 0.4 nozzle"),
  ],[],{engine:"crealityprint",version:"7.3.0",kind:"printer",
        printer:{id:"k2",model:"Creality K2 Combo"},nozzle:"0.6"}),null);
});

test("PETG profile filter excludes incompatible PLA defaults",()=>{
  const profiles=[make("pla","filament","Generic PLA",{is_default:true}),
    make("petg","filament","Generic PETG")];
  const suggestion=chooseSuggestedProfile(profiles,[],{engine:"crealityprint",version:"7.3.0",kind:"filament",material:"PETG"});
  assert.equal(suggestion.profile.id,"petg");
  assert.equal(chooseSuggestedProfile([profiles[0]],[],{engine:"crealityprint",version:"7.3.0",kind:"filament",material:"PETG"}),null);
});

test("do not auto-fill a K1 with K2-only PETG or process presets",()=>{
  const choices=[
    make("k2","filament","Generic PETG @Creality K2"),
    make("k1","filament","Generic PETG @Creality K1"),
    make("processK2","process","0.20mm Standard @Creality K2"),
    make("processK1","process","0.20mm Standard @Creality K1"),
  ];
  const opts={engine:"crealityprint",version:"7.3.0",printer,material:"PETG"};
  assert.equal(chooseSuggestedProfile(choices,[],{...opts,kind:"filament"}).profile.id,"k1");
  assert.equal(chooseSuggestedProfile(choices,[],{...opts,kind:"process"}).profile.id,"processK1");
});

test("0.20 mm standard is a fallback, not an invented preset",()=>{
  const profile=make("standard","process","0.20mm Standard @Creality K1");
  assert.equal(chooseSuggestedProfile([profile],[],{engine:"crealityprint",version:"7.3.0",kind:"process"}).profile.id,"standard");
  assert.equal(chooseSuggestedProfile([],[],{engine:"crealityprint",version:"7.3.0",kind:"process"}),null);
});

test("changing a physical spool family never inherits the old material's default", () => {
  const saved = [
    make("pla-default", "filament", "Creality Hyper PLA @Creality K1", {is_default:true}),
    make("petg-candidate", "filament", "Generic PETG @Creality K1"),
  ];
  const scope = {engine:"crealityprint", version:"7.3.0", kind:"filament", printer};
  assert.equal(chooseSuggestedProfile(saved, [], {...scope, material:"PLA"}).profile.id, "pla-default");
  assert.equal(chooseSuggestedProfile(saved, [], {...scope, material:"PETG"}).profile.id, "petg-candidate");
  assert.equal(chooseSuggestedProfile(saved, [], {...scope, material:"ABS"}), null);
});

test("printer-specific process defaults must not override a different printer", () => {
  const profiles = [
    make("k2-default", "process", "0.20mm Standard @Creality K2", {is_default:true}),
    make("k1-standard", "process", "0.20mm Standard @Creality K1"),
  ];
  const selected = chooseSuggestedProfile(profiles, [], {
    engine:"crealityprint", version:"7.3.0", kind:"process", printer,
  });
  assert.equal(selected.profile.id, "k1-standard");
  assert.equal(selected.reason, "0.20 mm starter");
});

test("a chosen engine version never inherits another version's saved default", () => {
  const candidates = [make("older", "process", "0.20mm Standard", {
    engine_version: "7.2.0", is_default:true,
  })];
  assert.equal(chooseSuggestedProfile(candidates, [], {
    engine:"crealityprint", version:"7.3.0", kind:"process",
  }), null);
});

test("native upstream selection uses the chosen printer rather than hardcoded Creality", () => {
  const vendors = ["Afinia", "BBL", "Creality", "Custom", "Prusa", "Voron"].map(id => ({id, label:id}));
  assert.equal(suggestOfficialVendor({manufacturer:"Prusa", model:"MK4"}, vendors), "Prusa");
  assert.equal(suggestOfficialVendor({brand:"Bambu Lab", name:"X1 Carbon"}, vendors), "BBL");
  assert.equal(suggestOfficialVendor({name:"Voron 2.4"}, vendors), "Voron");
  assert.equal(suggestOfficialVendor({name:"Unlisted Delta Prototype"}, vendors), "Custom");
  assert.equal(suggestOfficialVendor(null, [{id:"Creality", label:"Creality"}]), "Creality");
  assert.equal(defaultOfficialSearch("printer", {}), "0.4 nozzle");
});

test("generic printer qualifier filtering prevents cross-brand process or filament suggestions", () => {
  const profiles = [
    make("mk4","process","0.20mm Standard @MK4"),
    make("k2","process","0.20mm Standard @Creality K2 0.4 nozzle"),
    make("voron","process","0.20mm Standard @Voron 2.4"),
  ];
  const prusa = {model:"MK4", manufacturer:"Prusa"};
  assert.equal(chooseSuggestedProfile(profiles, [], {
    engine:"crealityprint", version:"7.3.0", kind:"process", printer:prusa,
  })?.profile.id, "mk4");
  const creality = {model:"Creality K2 Combo"};
  assert.equal(chooseSuggestedProfile(profiles, [], {
    engine:"crealityprint", version:"7.3.0", kind:"process", printer:creality,
  })?.profile.id, "k2");
  const custom = {model:"Voron 2.4"};
  assert.equal(chooseSuggestedProfile(profiles, [], {
    engine:"crealityprint", version:"7.3.0", kind:"process", printer:custom,
  })?.profile.id, "voron");
  assert.equal(chooseSuggestedProfile(profiles, [], {
    engine:"crealityprint", version:"7.3.0", kind:"process", printer:{model:"Anycubic Kobra 2"},
  }), null);
});
