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
  assert.match(workbench,/key=\{candidate\.sub_path \+ "::" \+ candidate\.name\}/);
  assert.match(workbench,/setOfficialImportTarget\(candidate\.sub_path \+ "::" \+ candidate\.name\)/);
});
