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
  assert.match(prepare,/const prusaMaterialRoutingPending = prusaNativeTools && activeEngine==="prusaslicer"/);
  assert.match(prepare,/!prusaNativeReady/);
  assert.match(prepare,/<PrusaNativeToolEditor/);
  assert.match(prepare,/onPrusaNativeToolsChange/);
  assert.match(prepare,/onSlice\?\.\(\)/);
  assert.match(workbench,/prusaNativeOffline && mode==="all"/);
});

test("Prusa MMU/XL allows only spatially qualified Object wall/infill controls",()=>{
  assert.match(prepare,/\["wall_loops","sparse_infill_density"\]\.includes\(key\)/);
  assert.match(prepare,/prusaUnsupportedObjectKeys/);
  assert.match(prepare,/Prusa MMU\/XL\/INDX supports only Object wall loops and infill density/);
  assert.match(prepare,/prusaNativeReady/);
  assert.match(prepare,/prusaMaterialRoutingPending/);
});

test("Prusa painted MMU draft binds swatches to explicit T1-T4 native tools",()=>{
  assert.match(editor,/colour_tools:\[\]/);
  assert.match(editor,/paintedSlots/);
  assert.match(editor,/singleColour/);
  assert.match(editor,/updateColour/);
  assert.match(editor,/Painted swatch/);
  assert.match(prepare,/prusaSinglePaint/);
  assert.match(prepare,/prusaPaintedSlots/);
  assert.match(prepare,/prusaNativeTools\.colour_tools\[0\]\.tool/);
  assert.match(prepare,/prusaSinglePaint && prusaNativeReady/);
  assert.match(workbench,/prusaNativeOffline = form\.engine==="prusaslicer"/);
});

test("Eight native INDX tools are configurable without MMU purge/tower dependencies",()=>{
  assert.match(editor,/<option value="indx">Bondtech INDX/);
  assert.match(editor,/\[2,3,4,5,6,7,8\]/);
  assert.match(editor,/value\.mode!=="mmu"/);
  assert.match(prepare,/prusaNativeTools\.mode\) && !primeTower/);
  assert.match(prepare,/objects\.length<=12/);
});
