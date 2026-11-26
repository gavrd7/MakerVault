import React, { useEffect, useState } from "react";

/**
 * Prusa's native tool assignment is independent of the printer's live slots.
 * Offline G-code is never a printer submission or physical toolchange test.
 */
const matrixFor = count => Array.from({length:count},(_,i)=>
  Array.from({length:count},(_,j)=>i===j?0:null));
const fresh = (mode="mmu",count=2,primary="") => ({
  version:1,mode,tool_count:count,
  filament_profile_ids:Array.from({length:count},(_,i)=>i===0?primary:""),
  model_tools:[],colour_tools:[],purge_matrix:mode==="mmu"?matrixFor(count):null,
});
const safeNumber = raw => {
  if(raw==="" || raw==null)return null;
  const value=Number(raw);
  return Number.isFinite(value)&&value>=0&&value<=1000?value:null;
};

export default function PrusaNativeToolEditor({
  value, onChange, models=[], profileChoices=[], primaryProfileId="",
  engineVersion="2.9.7", primeTower, onPrimeTowerChange, disabled=false,
}) {
  const [towerX,setTowerX]=useState(primeTower?.x==null?"":String(primeTower.x));
  const [towerY,setTowerY]=useState(primeTower?.y==null?"":String(primeTower.y));
  useEffect(()=>{
    setTowerX(primeTower?.x==null?"":String(primeTower.x));
    setTowerY(primeTower?.y==null?"":String(primeTower.y));
  },[primeTower?.x,primeTower?.y]);
  const profiles=profileChoices.filter(profile=>profile?.kind==="filament" &&
    profile.engine==="prusaslicer" && profile.engine_version===engineVersion);
  const updateTower=(axis,raw)=>{
    const x=axis==="x"?raw:towerX;
    const y=axis==="y"?raw:towerY;
    if(axis==="x")setTowerX(raw);else setTowerY(raw);
    if(x!=="" && y!=="" && Number.isFinite(Number(x)) && Number.isFinite(Number(y)) &&
        Number(x)>=0 && Number(y)>=0){
      onPrimeTowerChange?.({x:Number(x),y:Number(y)});
    } else {
      onPrimeTowerChange?.(null);
    }
  };
  const updateProfiles=(index,id)=>onChange?.({...value,
    filament_profile_ids:value.filament_profile_ids.map((entry,i)=>i===index?id:entry)});
  const updateModel=(instanceId,tool)=>{
    const existing=(value.model_tools||[]).filter(row=>row.instance_id!==instanceId);
    onChange?.({...value,model_tools:tool?[
      ...existing,{instance_id:instanceId,tool:Number(tool)}]:existing});
  };
  const updateColour=(slot,tool)=>{
    const others=(value.colour_tools||[]).filter(row=>row.slot!==slot);
    onChange?.({...value,colour_tools:tool?[
      ...others,{slot,tool:Number(tool)}]:others});
  };
  const paintedSlots=[...new Set(models.flatMap(model=>
    model.colour_paint?.regions?.map(region=>region.slot)||[]))];
  const singleColour=models.length===1 && paintedSlots.length===1 && value?.mode==="mmu";
  const editMatrix=(source,target,raw)=>{
    const matrix=value.purge_matrix.map(row=>[...row]);
    matrix[source][target]=safeNumber(raw);
    onChange?.({...value,purge_matrix:matrix});
  };
  const obsoleteToolMappings=(value?.model_tools||[]).filter(row=>
    !models.some(model=>model.instance_id===row.instance_id));
  const status=value?(
    value.filament_profile_ids.every(Boolean) &&
    ((models.length>=2 && models.length<=5) || singleColour) &&
    value.model_tools.length===models.length &&
    models.every(row=>value.model_tools.some(item=>item.instance_id===row.instance_id)) &&
    (singleColour
      ? value.model_tools[0]?.tool===1 &&
        value.colour_tools?.length===1 &&
        value.colour_tools[0].slot===paintedSlots[0] &&
        value.colour_tools[0].tool>=2 && value.colour_tools[0].tool<=value.tool_count
      : new Set(value.model_tools.map(row=>row.tool)).size>=2 &&
        !(value.colour_tools||[]).length) &&
    (value.mode==="xl" ||
      (primeTower!=null && value.purge_matrix?.every((row,i)=>
        row.every((amount,j)=>i===j||amount!=null&&amount>=1&&amount<=1000))))
  ):false;
  return <section className="slicerPrusaNativeTools" aria-label="Prusa native material tools"
    style={{minWidth:0,padding:12,border:"1px solid var(--border-color, #60708044)",borderRadius:10}}>
    <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12,flexWrap:"wrap"}}>
      <strong>Prusa MMU / XL native materials</strong>
      {!value?<button type="button" disabled={disabled}
        onClick={()=>onChange?.(fresh("mmu",2,primaryProfileId))}>
        Configure native tools
      </button>:<button type="button" disabled={disabled}
        onClick={()=>{onChange?.(null);onPrimeTowerChange?.(null);}}>
        Clear native tools
      </button>}
    </div>
    <p className="projectUploadHint">Assign actual Prusa native extruders to models, independently of loaded
      printer bays. This produces offline preview/Library G-code only; physical MMU loading,
      XL pickup and printer submission are not approved.</p>
    {value && <>
      <div style={{display:"flex",gap:12,flexWrap:"wrap"}}>
        <label>Toolchanger architecture
          <select value={value.mode} disabled={disabled}
            onChange={e=>{
              const mode=e.target.value;
              onChange?.({...value,mode,purge_matrix:mode==="mmu"?matrixFor(value.tool_count):null});
              if(mode==="xl")onPrimeTowerChange?.(null);
            }}>
            <option value="mmu">MMU3 — one nozzle, multiple filaments</option>
            <option value="xl">Prusa XL — independent toolheads</option>
          </select>
        </label>
        <label>Native logical tools
          <select value={value.tool_count} disabled={disabled}
            onChange={e=>{
              const count=Number(e.target.value);
              onChange?.({...value,tool_count:count,
                filament_profile_ids:Array.from({length:count},(_,i)=>value.filament_profile_ids[i]||""),
                model_tools:value.model_tools.filter(row=>row.tool<=count),
                colour_tools:(value.colour_tools||[]).filter(row=>row.tool<=count),
                purge_matrix:value.mode==="mmu"?matrixFor(count):null});
            }}>
            {[2,3,4,5].map(count=><option key={count} value={count}>{count}</option>)}
          </select>
        </label>
      </div>
      <p className="projectUploadHint">The selected native printer profile must contain the same
        nozzle/tool count and mechanism. A profile with six to eight tools (INDX) remains unqualified.</p>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))",gap:10}}>
        {value.filament_profile_ids.map((id,index)=><label key={index}>
          Native T{index} filament profile
          <select disabled={disabled} value={id||""}
            onChange={e=>updateProfiles(index,e.target.value)}>
            <option value="">Select imported Prusa filament…</option>
            {profiles.map(profile=><option key={profile.id} value={profile.id}>{profile.name}</option>)}
          </select>
        </label>)}
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))",gap:10,marginTop:10}}>
        {models.map((model,index)=><label key={model.instance_id}>
          {model.label||"Model "+(index+1)} — native extruder
          <select disabled={disabled} value={value.model_tools.find(row=>
            row.instance_id===model.instance_id)?.tool||""}
            onChange={e=>updateModel(model.instance_id,e.target.value)}>
            <option value="">Assign a tool…</option>
            {Array.from({length:value.tool_count},(_,i)=>
              <option key={i+1} value={i+1}>T{i} (native tool {i+1})</option>)}
          </select>
        </label>)}
      </div>
      {paintedSlots.length>0 && <div style={{marginTop:10}}>
        <p className="projectUploadHint">Native Prusa surface colour: the verified offline
          MMU route currently accepts one upright model painted on its front face,
          with base extruder T0 and one different painted native tool. Other paint
          directions and combined tools can be saved but cannot yet be sliced.</p>
        {paintedSlots.map(slot=><label key={slot} style={{display:"block",marginBottom:8}}>
          Painted swatch {slot} — native Prusa tool
          <select disabled={disabled} value={(value.colour_tools||[]).find(
              row=>row.slot===slot)?.tool||""}
            onChange={e=>updateColour(slot,e.target.value)}>
            <option value="">Choose a painted tool…</option>
            {Array.from({length:value.tool_count-1},(_,i)=>i+2).map(tool=>
              <option key={tool} value={tool}>T{tool-1} (native tool {tool})</option>)}
          </select>
        </label>)}
      </div>}
      {obsoleteToolMappings.length>0 && <div className="projectUploadHint">
        <p>{obsoleteToolMappings.length} native tool assignment(s) refer to removed models.
          Clear the stale assignments before slicing; your saved draft remains intact.</p>
        <button type="button" disabled={disabled} onClick={()=>onChange?.({...value,
          model_tools:value.model_tools.filter(row=>!obsoleteToolMappings.includes(row))})}>
          Clear obsolete model assignments
        </button>
      </div>}
      {value.mode==="mmu"&&<>
        <p className="projectUploadHint">MMU3 requires a complete, explicit directional purge
          matrix in mm³. Blank entries block slicing; suggested colour values are not proof of
          sufficient physical purging.</p>
        <div style={{overflowX:"auto",maxWidth:"100%"}}>
          <table className="slicerFlushMatrix" aria-label="Prusa MMU directional purge matrix">
            <thead><tr><th scope="col">From / To</th>
              {value.filament_profile_ids.map((_,i)=><th key={i} scope="col">T{i}</th>)}
            </tr></thead>
            <tbody>{value.purge_matrix.map((row,i)=><tr key={i}><th scope="row">T{i}</th>
              {row.map((amount,j)=><td key={j}>{i===j?"—":
                <input type="number" min="1" max="1000" step="1"
                  aria-label={`Purge T${i} to T${j}`} disabled={disabled}
                  value={amount??""} onChange={e=>editMatrix(i,j,e.target.value)}
                  style={{width:72}}/>}</td>)}
            </tr>)}</tbody>
          </table>
        </div>
        <div style={{display:"flex",gap:12,flexWrap:"wrap"}}>
          <label>Native wipe tower X (mm)
            <input type="number" min="0" step="0.1" disabled={disabled}
              value={towerX} onChange={e=>updateTower("x",e.target.value)}/>
          </label>
          <label>Native wipe tower Y (mm)
            <input type="number" min="0" step="0.1" disabled={disabled}
              value={towerY} onChange={e=>updateTower("y",e.target.value)}/>
          </label>
        </div>
      </>}
      <p role="status">{status
        ?"Native tool assignments are complete. The server will verify the exact printer profile and run a model-local G-code audit before saving output."
        :"Complete all native tool profiles, assign at least two distinct tools (or one model plus a painted native colour), and provide MMU purge/tower values where applicable. You can save an incomplete draft."}</p>
    </>}
  </section>;
}
