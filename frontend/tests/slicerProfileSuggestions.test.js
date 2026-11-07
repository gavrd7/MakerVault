import test from "node:test";
import assert from "node:assert/strict";
import { spoolMaterial, chooseSuggestedProfile, defaultOfficialSearch } from "../src/components/slicerProfileSuggestions.js";

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

test("PETG profile filter excludes incompatible PLA defaults",()=>{
  const profiles=[make("pla","filament","Generic PLA",{is_default:true}),
    make("petg","filament","Generic PETG")];
  const suggestion=chooseSuggestedProfile(profiles,[],{engine:"crealityprint",version:"7.3.0",kind:"filament",material:"PETG"});
  assert.equal(suggestion.profile.id,"petg");
  assert.equal(chooseSuggestedProfile([profiles[0]],[],{engine:"crealityprint",version:"7.3.0",kind:"filament",material:"PETG"}),null);
});

test("0.20 mm standard is a fallback, not an invented preset",()=>{
  const profile=make("standard","process","0.20mm Standard @Creality K1");
  assert.equal(chooseSuggestedProfile([profile],[],{engine:"crealityprint",version:"7.3.0",kind:"process"}).profile.id,"standard");
  assert.equal(chooseSuggestedProfile([],[],{engine:"crealityprint",version:"7.3.0",kind:"process"}),null);
});
