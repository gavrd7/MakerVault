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

test("Prusa MMU/XL/INDX admits verified native Object wall, shell and infill controls",()=>{
  for (const key of ["top_shell_layers","bottom_shell_layers",
                     "outer_wall_speed","inner_wall_speed",
                     "sparse_infill_speed","top_surface_speed"])
    assert.match(prepare,new RegExp('"' + key + '"'));
  assert.match(prepare,/prusaUnsupportedObjectKeys/);
  assert.match(prepare,/Prusa MMU\/XL\/INDX maps Object walls, shells, infill density and native perimeter\/infill\/top-surface speeds/);
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
  assert.match(prepare,/prusaNativeTools\.colour_tools\.map\(row=>row\.tool\)/);
  assert.match(prepare,/prusaSinglePaint && prusaNativeReady/);
  assert.match(prepare,/prusaPaintedSlots\.length<=2/);
  assert.match(editor,/new Set\(value\.colour_tools\.map\(row=>row\.tool\)\)\.size===paintedSlots\.length/);
  assert.match(workbench,/prusaNativeOffline = form\.engine==="prusaslicer"/);
});

test("Eight native INDX tools are configurable without MMU purge/tower dependencies",()=>{
  assert.match(editor,/<option value="indx">Bondtech INDX/);
  assert.match(editor,/profileToolCount \? \[\.\.\.new Set\(\[value\.tool_count, profileToolCount\]\)\]/);
  assert.match(editor,/value\.mode!=="mmu"/);
  assert.match(prepare,/prusaNativeTools\.mode\) && !primeTower/);
  assert.match(prepare,/objects\.length<=200/);
});

test("MMU, XL and INDX map native modifier and variable layer regions",()=>{
  assert.match(prepare,/prusaSinglePaint && object\.variable_layer_profile\?\.bands\?\.length/);
  assert.match(prepare,/prusaSinglePaint && object\.modifier_volumes\?\.length/);
  assert.match(prepare,/object\.modifier_volumes\.length===1/);
  assert.match(prepare,/object\.modifier_volumes\[0\]\?\.shape==="box"/);
  assert.match(prepare,/object\.modifier_volumes\[0\]\?\.kind==="modifier"/);
  assert.match(prepare,/sparse_infill_density/);
  assert.doesNotMatch(prepare,/!prusaIndependentTools/);
  for (const key of ["top_shell_layers","bottom_shell_layers",
                     "outer_wall_speed","inner_wall_speed",
                     "sparse_infill_speed","top_surface_speed"])
    assert.match(prepare,new RegExp('"' + key + '"'));
  assert.match(prepare,/Prusa MMU\/XL\/INDX maps Object walls, shells/);
  assert.match(prepare,/const prusaUnsupportedObjectKeys/);
  assert.match(prepare,/String\(engine \|\| ""\)\.split\(" "\)\[0\] === "prusaslicer"/);
  assert.match(prepare,/const verifiedObjectSettings = new Set/);
  assert.match(prepare,/object\.negative_volumes\?\.length/);
  assert.match(prepare,/object\.support_paint\?\.regions\?\.length/);
  assert.match(prepare,/object\.seam_paint\?\.regions\?\.length/);
  assert.match(prepare,/object\.fuzzy_skin_paint\?\.regions\?\.length/);
  assert.match(editor,/printerTopology\?\.kind==="indx" \? "indx"/);
  assert.match(editor,/Prusa XL/);
});

test("Prusa independent XL and INDX reuse one- or two-wall native painting without MMU purging",()=>{
  assert.match(editor,/paintedSlots\.length<=2/);
  assert.match(editor,/value\?\.mode==="xl" && value\?\.tool_count===5/);
  assert.match(editor,/paintedSlots\.length===4/);
  assert.match(prepare,/\["mmu","xl","indx"\]\.includes\(prusaNativeTools\?\.mode\)/);
  assert.match(prepare,/prusaPaintedSlots\.length<=2/);
  assert.match(prepare,/prusaNativeTools\?\.mode==="xl"/);
  assert.match(prepare,/prusaPaintedSlots\.length===4/);
  assert.doesNotMatch(prepare,/!prusaIndependentTools/);
  assert.match(editor,/without\s+MMU\s+purging/);
  assert.match(editor,/Math\.min\(value\.tool_count-1,7\)/);
});


test("offline Prusa bulk material assignment uses native tool indices, never physical slot IDs",()=>{
  assert.match(prepare,/selectedModelIds=\{selectedModels\.map\(model => model\.instance_id\)\}/);
  assert.match(editor,/selectedModelIds=\[\]/);
  assert.match(editor,/const updateSelectedModels = tool =>/);
  assert.match(editor,/const ids = new Set\(selectedModelIds\)/);
  assert.match(editor,/models\.filter\(row => ids\.has\(row\.instance_id\)\)/);
  assert.match(editor,/Change native filament for/);
  assert.match(editor,/onChange=\{event => updateSelectedModels\(event\.target\.value\)\}/);
});


test("Prusa native tool capacity is retrieved from an owner-scoped resolved printer profile",()=>{
  assert.match(workbench,/prusa_printer_topology_id=/);
  assert.match(workbench,/prusaProfileTopology=\{prusaProfileTopology\}/);
  assert.match(prepare,/printerTopology=\{prusaProfileTopology\}/);
  assert.match(editor,/const profileToolCount = Number\.isInteger\(printerTopology\?\.logical_tool_count\)/);
  assert.match(editor,/const profileMode = printerTopology\?\.kind/);
  assert.match(editor,/Match native printer profile/);
  assert.match(editor,/profileMatches && value\.filament_profile_ids\.every\(Boolean\)/);
  assert.match(editor,/const profileMatches = !!profileToolCount && !!profileMode/);
  assert.match(editor,/profileToolCount \? \[\.\.\.new Set\(\[value\.tool_count, profileToolCount\]\)\]/);
  assert.match(editor,/draft; profile mismatch/);
});

test("Prusa Slice readiness refuses native-profile mismatch before sending the job",()=>{
  assert.match(prepare,/const prusaProfileMode = prusaProfileTopology\?\.kind/);
  assert.match(prepare,/const prusaTopologyMatches = !!prusaProfileTopology/);
  assert.match(prepare,/prusaNativeTools\?\.tool_count===prusaProfileTopology\.logical_tool_count/);
  assert.match(prepare,/prusaTopologyMatches &&/);
  assert.match(prepare,/Use Match native printer profile in the materials panel/);
});

test("new Prusa native-tool drafts inherit the chosen printer profile topology",()=>{
  assert.match(editor,/fresh\(profileMode, profileToolCount, primaryProfileId\)/);
  assert.match(editor,/disabled=\{disabled \|\| !profileMode \|\| !profileToolCount\}/);
  assert.match(editor,/const profileMode = printerTopology\?\.kind==="single_nozzle_changer"/);
});


test("Prusa multi-tool workbench maps native speeds and first-layer adhesion controls",()=>{
  const native = prepare.slice(prepare.indexOf("const prusaNativeReady"),
    prepare.indexOf("const prusaMaterialRoutingPending"));
  for (const key of ["outer_wall_speed","inner_wall_speed",
                     "sparse_infill_speed","travel_speed","top_surface_speed"])
    assert.match(native,new RegExp('"' + key + '"'));
  for (const key of ["brim_width","skirt_loops"])
    assert.match(native,new RegExp('"' + key + '"'));
  assert.match(prepare,/const prusaUnsupportedGlobalKeys/);
  assert.match(prepare,/Object\.keys\(processOverrides\|\|\{\}\)\.every/);
});


test("selecting every Prusa model to one filament switches to verified single-material path",()=>{
  assert.match(prepare,/const entirePlateSelected = ids\.size === objects\.length/);
  assert.match(prepare,/const hasPaintedColours = objects\.some/);
  assert.match(prepare,/entirePlateSelected && !hasPaintedColours && onUsePrusaSingleMaterial/);
  assert.match(prepare,/onUsePrusaSingleMaterial\(matchingProfile\.id\)/);
  assert.match(workbench,/onUsePrusaSingleMaterial=\{profileId => \{/);
  assert.match(workbench,/selectNativeProfile\("filament", profileId\)/);
  assert.match(workbench,/setPrusaNativeTools\(null\)/);
  assert.match(workbench,/setPrimeTower\(null\)/);
  assert.match(prepare,/const existing = \(prusaNativeTools\.model_tools \|\| \[\]\)\.filter/);
});


test("Prusa painted MMU workbench checks one disjoint box infill modifier and one cavity",()=>{
  assert.match(prepare,/prusaNativeTools\?\.mode==="mmu"/);
  assert.match(prepare,/object\.modifier_volumes\.length===2/);
  assert.match(prepare,/object\.modifier_volumes\[0\]\?\.kind==="modifier"/);
  assert.match(prepare,/object\.modifier_volumes\[1\]\?\.kind==="negative"/);
  assert.match(prepare,/object\.modifier_volumes\[1\]\?\.coordinate_space==="world"/);
  assert.match(prepare,/Object\.keys\(object\.modifier_volumes\[1\]\?\.settings\|\|\{\}\)\.length===0/);
});

test("Shared Prusa tool selector explains independently audited native MMU compound regions",()=>{
  assert.match(editor,/one complete T1-painted wall can combine Object process settings/);
  assert.match(editor,/one box infill modifier and one disjoint negative box/);
  assert.match(editor,/native\s+extrusion and cavity subtraction are checked/);
});

test("Prusa MMU admits only qualified T1 colour with disjoint fuzzy skin",()=>{
  assert.match(prepare,/object\.fuzzy_skin_paint\?\.regions\?\.length &&/);
  assert.match(prepare,/prusaNativeTools\?\.mode==="mmu"/);
  assert.match(prepare,/prusaPaintedSlots\.length===1/);
  assert.match(prepare,/prusaNativeTools\?\.colour_tools\?\.\[0\]\?\.tool===2/);
  assert.match(prepare,/!object\.modifier_volumes\?\.length/);
  assert.match(prepare,/!object\.support_paint\?\.regions\?\.length/);
  assert.match(prepare,/!object\.seam_paint\?\.regions\?\.length/);
  assert.match(editor,/complete MMU T1 front colour wall can alternatively/);
  assert.match(editor,/selective fuzzy skin on the opposite T0 wall/);
});

test("Two independent MMU painted objects bind native T0 bases to signed T1/T2 swatches",()=>{
  assert.match(prepare,/const prusaMultiPaint=activeEngine==="prusaslicer"/);
  assert.match(prepare,/objects\.length===2 && prusaNativeTools\?\.mode==="mmu"/);
  assert.match(prepare,/row\.instance_id===object\.instance_id && row\.tool===1/);
  assert.match(prepare,/row\.tool===index\+2/);
  assert.match(prepare,/prusaSinglePaint \|\| prusaMultiPaint/);
  assert.match(prepare,/Object\.keys\(object\.process_overrides\|\|\{\}\)\.length/);
  assert.match(editor,/MMU also accepts two distinct/);
  assert.match(editor,/native wipe-tower purge checked/);
});

test("Shared Prusa colour help differentiates native split walls from unqualified geometries",()=>{
  assert.match(editor,/MMU supports one painted vertical wall or two/);
  assert.match(editor,/independently coloured opposite vertical walls/);
  assert.match(editor,/independently audited/);
  assert.match(editor,/XL5 independently supports both split/);
  assert.match(editor,/partially painted horizontal top faces/);
  assert.match(editor,/curved\/nonplanar facets/);
  assert.match(editor,/genuinely curved T1 brush/);
  assert.match(editor,/other MMU\/INDX\/XL tools/);
  assert.match(editor,/T1 brush region on a planar angled face/);
  assert.match(editor,/More than two painted models/);
});

test("Prusa colour-paint guidance names the native MMU/XL route and profile-derived tools",()=>{
  assert.match(prepare,/Prusa native colour painting needs a selected MMU or XL printer profile/);
  assert.match(prepare,/owned filament preset for each reported tool/);
  assert.match(prepare,/Prusa virtual tools use native extruder assignments from the selected printer profile/);
  assert.match(prepare,/one qualified painted MMU\/XL model with T0 base/);
  assert.doesNotMatch(prepare,/Prusa virtual tools use explicit native T0–T7 assignments/);
});

test("Prusa tool configurator does not invent MMU, XL or INDX capacity",()=>{
  assert.match(editor,/Select an imported, inspectable native Prusa printer profile first/);
  assert.match(editor,/fresh\(profileMode, profileToolCount, primaryProfileId\)/);
  assert.match(editor,/disabled=\{disabled \|\| !!profileMode\}/);
  assert.match(editor,/disabled=\{disabled \|\| !!profileToolCount\}/);
  assert.doesNotMatch(editor,/value\.mode==="indx"\?\[2,3,4,5,6,7,8\]/);
});

test("native Prusa Slice stays blocked until its inspected printer topology is available",()=>{
  assert.match(prepare,/const prusaTopologyMatches = !!prusaProfileTopology &&/);
  assert.match(prepare,/prusaTopologyMatches &&/);
  assert.match(editor,/const profileMatches = !!profileToolCount && !!profileMode/);
  assert.match(editor,/profileMatches && value\.filament_profile_ids\.every\(Boolean\)/);
});

test("Prusa Slice explains uninspected profile topology without dereferencing null",()=>{
  assert.match(prepare,/!prusaProfileTopology\s*\? "The selected Prusa printer profile topology has not been inspected yet/);
  assert.match(prepare,/String\(prusaProfileTopology\.kind \|\| "unknown"\)\.replaceAll/);
  assert.match(prepare,/const prusaTopologyMatches = !!prusaProfileTopology/);
});


test("MMU retains native modifier volumes while known upstream variable-layer failure is gated",()=>{
  assert.match(prepare,/object\.variable_layer_profile\?\.bands\?\.length &&\s*prusaNativeTools\?\.mode==="mmu"/);
  assert.match(prepare,/prusaSinglePaint && object\.variable_layer_profile\?\.bands\?\.length/);
  assert.match(prepare,/prusaSinglePaint && object\.modifier_volumes\?\.length/);
  assert.doesNotMatch(prepare,/!prusaIndependentTools/);
});
