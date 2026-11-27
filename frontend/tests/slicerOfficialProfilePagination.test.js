import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const dir=path.dirname(fileURLToPath(import.meta.url));
const workbench=fs.readFileSync(path.resolve(dir,"../src/components/SlicerWorkbench.jsx"),"utf8");

test("all official profile kinds use server-side pages of forty with stable submitted filters",()=>{
  assert.match(workbench,/setOfficialSearchParams\(params\.toString\(\)\)/);
  assert.match(workbench,/new URLSearchParams\(officialSearchParams\)/);
  assert.match(workbench,/params\.set\("page", String\(page\)\)/);
  assert.match(workbench,/setOfficialResults\(result\)/);
  assert.match(workbench,/officialResults\.total_pages/);
  assert.match(workbench,/officialResults\.page_size/);
});

test("official profile modal provides accessible first previous next and last controls",()=>{
  for (const label of ["First page","Previous page","Next page","Last page"])
    assert.ok(workbench.includes('aria-label="'+label+'"'));
  assert.match(workbench,/Page \{officialResults\.page\} of \{officialResults\.total_pages\}/);
  assert.match(workbench,/officialBusy \|\| officialResults\.page <= 1/);
  assert.match(workbench,/officialBusy \|\| officialResults\.page >= officialResults\.total_pages/);
});

test("Prusa INI rows use the name and subpath as a unique identity",()=>{
  assert.match(workbench,/key=\{\(candidate\.vendor \|\| officialVendor\) \+ "::" \+ candidate\.sub_path \+ "::" \+ candidate\.name\}/);
  assert.match(workbench,/setOfficialImportTarget\(candidate\.sub_path \+ "::" \+ candidate\.name\)/);
});

test("Prusa official profile browser preserves selected printer, filament and process kind", () => {
  const start = workbench.indexOf("function openOfficialSearch(");
  const end = workbench.indexOf("async function removeProfile(", start);
  assert.ok(start >= 0 && end > start);
  const open = workbench.slice(start, end);
  assert.ok(open.includes("setImportKind(kind)"));
  assert.ok(!open.includes('form.engine === "prusaslicer" ? "printer"'));
  for (const kind of ["printer", "filament", "process"])
    assert.ok(workbench.includes('<option value="' + kind + '">'));
});

test("official modal places profile type first and uses one unified Orca filament manufacturer control",()=>{
  const start=workbench.indexOf('profileModal === "search" && <Modal');
  const modal=workbench.slice(start,workbench.indexOf('profileModal === "import" && <Modal',start));
  assert.ok(start>=0);
  assert.ok(modal.indexOf("<label>Profile type") < modal.indexOf("<label>Filament manufacturer"));
  assert.ok(modal.indexOf("<label>Profile type") < modal.indexOf("<label>Manufacturer / upstream catalogue"));
  assert.match(modal,/importKind === "filament" \? \(/);
  assert.match(modal,/form.engine === "orcaslicer"/);
  assert.match(modal,/officialBrands\.map\(brand/);
  assert.match(modal,/\{candidate\.vendor && candidate\.vendor \+ " · "\}/);
  assert.match(workbench,/vendor: candidate\.vendor \|\| officialVendor/);
  assert.match(workbench,/params\.set\("unified_filaments","1"\)/);
  assert.match(workbench,/unified_filaments:"1"/);
  assert.match(workbench,/importKind!=="filament" && !officialManualModel\.trim\(\) && officialModel/);
});
