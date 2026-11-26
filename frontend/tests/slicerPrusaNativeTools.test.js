import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const read=p=>fs.readFileSync(path.join(root,p),"utf8");
const workbench=read("src/components/SlicerWorkbench.jsx");
const prepare=read("src/components/SlicerPrepareWorkspace.jsx");
const editor=read("src/components/PrusaNativeToolEditor.jsx");

test("Prusa native materials are saved and restored through the ordinary job API",()=>{
  assert.match(workbench,/const \[prusaNativeTools,setPrusaNativeTools\] = useState\(null\)/);
  assert.match(workbench,/prusa_native_tools:prusaNativeTools/);
  assert.match(workbench,/multi_material_test:true/);
  assert.match(workbench,/setPrusaNativeTools\(job\.settings\?\.prusa_native_tools \|\| null\)/);
  assert.match(workbench,/prusaNativeTools=\{prusaNativeTools\}/);
  assert.match(workbench,/onPrusaNativeToolsChange=\{setPrusaNativeTools\}/);
});

test("Native tools are never derived from physical printer slot numbers",()=>{
  assert.match(editor,/independent of the printer's live slots/);
  assert.match(editor,/value\.model_tools/);
  assert.match(editor,/filament_profile_ids/);
  assert.match(editor,/Native T\{index\} filament profile/);
  assert.match(editor,/Assign a tool/);
  assert.doesNotMatch(editor,/slot_index/);
});

test("MMU purge matrix is directional and blank cells block slicing",()=>{
  assert.match(editor,/matrixFor = count/);
  assert.match(editor,/i===j\?0:null/);
  assert.match(editor,/aria-label=\{\x60Purge T/);
  assert.match(editor,/amount!=null&&amount>=1&&amount<=1000/);
  assert.match(editor,/primeTower!=null/);
  assert.match(editor,/physical MMU loading/);
});

test("Interactive slicer blocks incomplete Prusa mapping but keeps draft saving available",()=>{
  assert.match(prepare,/const prusaNativeReady = activeEngine === "prusaslicer"/);
  assert.match(prepare,/const materialRoutingPending = prusaNativeTools && activeEngine==="prusaslicer"/);
  assert.match(prepare,/!prusaNativeReady/);
  assert.match(prepare,/<PrusaNativeToolEditor/);
  assert.match(prepare,/onPrusaNativeToolsChange/);
  assert.match(prepare,/onSlice\?\.\(\)/);
  assert.match(workbench,/prusaNativeOffline && mode==="all"/);
});
