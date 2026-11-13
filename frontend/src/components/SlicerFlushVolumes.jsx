import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "../api";
import { estimateSlotFlush, multiplyFlushEstimate, slotMaterialCompatibility } from "./slicerFlushEstimates";

const empty = () => ({ multiplier: null, prime_tower: "native", transitions: [] });
const slotName = slot => `Slot ${Number(slot.slot_index ?? 0)+1} · ${slot.product_name || slot.material || "Unknown"}`;
const slotColour = slot => /^#[0-9a-f]{6}$/i.test(slot.color_hex||"") ? slot.color_hex : "#697b91";
const Swatch = ({slot}) => <span className="slicerFlushSwatch" aria-hidden="true"
  style={{backgroundColor:slotColour(slot)}}/>;

/** UI remains advisory until native physical-slot-to-tool mapping has been verified. */
export default function SlicerFlushVolumes({slots=[],value=null,onChange,disabled=false,processProfileId=""}) {
  const [open,setOpen]=useState(false);
  const [native,setNative]=useState(null);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const [estimateMode,setEstimateMode]=useState(true);
  const [previewMultiplier,setPreviewMultiplier]=useState(null);
  const [hasEditedMultiplier,setHasEditedMultiplier]=useState(false);
  const visible=slots.filter(slot=>slot?.id!=null).slice(0,16);
  const data=value||empty();
  useEffect(()=>{
    if(!open)return undefined;
    setNative(null);
    if(!processProfileId){setError("Select an imported OrcaSlicer process profile to view its native flushing values.");return undefined;}
    setError("");
    let live=true;
    setLoading(true);setError("");setNative(null);
    apiFetch("/api/printing/slicer/profiles/"+encodeURIComponent(processProfileId)+"/flush-defaults/")
      .then(v=>{if(live)setNative(v);})
      .catch(e=>{if(live)setError(e.message||"Could not resolve native flushing defaults.");})
      .finally(()=>{if(live)setLoading(false);});
    return ()=>{live=false;};
  },[open,processProfileId]);
  useEffect(()=>{
    if(!open)return undefined;
    const close=e=>{if(e.key==="Escape")setOpen(false);};
    window.addEventListener("keydown",close);
    return ()=>window.removeEventListener("keydown",close);
  },[open]);
  function updateTransition(from,to,raw){
    const rest=data.transitions.filter(t=>t.from_slot_id!==String(from.id)||t.to_slot_id!==String(to.id));
    if(!raw.trim()){onChange?.({...data,transitions:rest});return;}
    const n=Number(raw);
    if(Number.isFinite(n)&&n>=0&&n<=20000)
      onChange?.({...data,transitions:[...rest,{from_slot_id:String(from.id),to_slot_id:String(to.id),volume_mm3:n}]});
  }
  const overrideFor=(from,to)=>data.transitions.find(t=>
    t.from_slot_id===String(from.id)&&t.to_slot_id===String(to.id))?.volume_mm3;
  const nativeMultiplier=native?.multiplier;
  const effectiveMultiplier=nativeMultiplier??1;
  const desiredMultiplier=data.multiplier??effectiveMultiplier;
  // A changed multiplier does not mutate manually edited directional values.
  // It updates only the preview when the user selects Recalculate.
  const displayedMultiplier=previewMultiplier??desiredMultiplier;
  const recalcRequired=hasEditedMultiplier && Math.abs(displayedMultiplier-desiredMultiplier)>1e-8;
  useEffect(()=>{
    if(!open)return;
    setPreviewMultiplier(null);
    setHasEditedMultiplier(false);
  },[open,processProfileId]);
  const suggestions=visible.flatMap(from=>visible.flatMap(to=>{
    if(String(from.id)===String(to.id))return [];
    const estimate=estimateSlotFlush(from,to);
    return estimate==null?[]:[{from,to,estimate}];
  }));
  function copySuggestions(){
    const existing=data.transitions||[];
    const updates=[...existing];
    for(const row of suggestions){
      if(existing.some(t=>t.from_slot_id===String(row.from.id)&&t.to_slot_id===String(row.to.id)))continue;
      updates.push({from_slot_id:String(row.from.id),to_slot_id:String(row.to.id),volume_mm3:row.estimate});
    }
    onChange?.({...data,transitions:updates});
  }
  return <>
    <button type="button" className="slicerFlushOpenButton" onClick={()=>setOpen(true)}
      aria-haspopup="dialog">Flushing settings {value?"· customised":"· native defaults"}</button>
    {open && createPortal(<div className="slicerFlushModalBackdrop"
      onMouseDown={e=>{if(e.target===e.currentTarget)setOpen(false);}}>
      <section className="slicerFlushModal" role="dialog" aria-modal="true"
        aria-label="Flushing settings">
        <header className="slicerFlushModalHeader">
          <h3>Flushing settings</h3>
          <button type="button" onClick={()=>setOpen(false)} aria-label="Close flushing settings">✕</button>
        </header>
        <div className="slicerFlushModalBody">
          <p className="projectUploadHint">Native values come from the selected process profile.
            Physical CFS bays are not assumed to match native tool indices.</p>
          {loading&&<p role="status">Resolving native profile settings…</p>}
          {error&&<p role="alert" className="formError">{error}</p>}
          <div className="slicerFlushModalControls">
            <div className="slicerFlushField">
              <label htmlFor="slicer-flush-multiplier">Flush multiplier</label>
              <input id="slicer-flush-multiplier" type="number" min=".1" max="3" step=".1"
                disabled={disabled} value={data.multiplier ?? effectiveMultiplier}
                onChange={e=>{
                  const raw=e.target.value;
                  if(!raw.trim()){
                    setPreviewMultiplier(current=>current??desiredMultiplier);
                    onChange?.({...data,multiplier:null});setHasEditedMultiplier(true);return;
                  }
                  const n=Number(raw);if(n>=.1&&n<=3){
                    setPreviewMultiplier(current=>current??desiredMultiplier);
                    onChange?.({...data,multiplier:n});setHasEditedMultiplier(true);
                  }
                }}/>
              <small>{data.multiplier==null
                ? nativeMultiplier!=null?"Inherited from process profile · "+nativeMultiplier
                  :"Orca project default · 1 (not process profile data)"
                :"Custom override · "+data.multiplier}</small>
            </div>
            <div className="slicerFlushField">
              <label htmlFor="slicer-flush-prime-tower">Prime tower</label>
              <select id="slicer-flush-prime-tower" disabled={disabled} value={data.prime_tower}
                onChange={e=>onChange?.({...data,prime_tower:e.target.value})}>
                <option value="native">Native default {native?.prime_tower==null?"(unknown)":native.prime_tower?"(enabled)":"(disabled)"}</option>
                <option value="enabled">Enabled</option><option value="disabled">Disabled</option>
              </select>
              <small>{data.prime_tower==="native"
                ?"Inherited from native process / project settings":"User override"}</small>
            </div>
          </div>
          <h4>Directional flushing · mm³</h4>
          <p className="projectUploadHint">Rows: unloaded filament. Columns: next loaded filament.
            Each editable cell is a directional override. Native process values are tool-indexed,
            not physical CFS slot values, until a verified slot-to-tool map is available.</p>
          <div className="slicerFlushEstimateBar">
            <label><input type="checkbox" checked={estimateMode}
              onChange={e=>setEstimateMode(e.target.checked)}/>
              Show colour-only estimates (not native volumes)</label>
            <button type="button" disabled={!estimateMode || !recalcRequired}
              onClick={()=>{setPreviewMultiplier(desiredMultiplier);setHasEditedMultiplier(false);}}>
              Recalculate
            </button>
            <button type="button" disabled={disabled||!suggestions.length||!estimateMode}
              title="Copies colour-only estimates as manual draft overrides; does not verify safe purging"
              onClick={()=>{if(window.confirm("These are unscaled colour-only contributions, not native purge volumes. The selected multiplier is applied separately during slicing. Mixed-material values are NOT copied, and minimum material purge is missing. Add same-material base estimates as draft overrides for inspection?"))copySuggestions();}}>
              Copy estimates to draft
            </button>
          </div>
          {estimateMode&&<p className="projectUploadHint" role="status">
            Displayed estimates include a preview multiplier of {displayedMultiplier}.
            They omit nozzle minimum purging, calibrated prediction and CFS tool routing.
            Mixed-material (†) cells show colour contribution only and are never copied into draft overrides.
            Copying same-material estimates saves unscaled values because the multiplier is applied separately.
            {recalcRequired ? " Multiplier changed: choose Recalculate to refresh the estimates." : ""}
          </p>}
          {visible.length>=2 ? <div className="slicerFlushTableScroll">
            <table className="slicerFlushMatrix" aria-label="Directional flushing volumes">
              <thead><tr><th scope="col">From / To</th>{visible.map(slot=><th scope="col" key={slot.id}>
                <span className="slicerFlushSlotLabel"><Swatch slot={slot}/>
                  <span>{slotName(slot)}</span></span>
              </th>)}</tr></thead>
              <tbody>{visible.map(from=><tr key={from.id}>
                <th scope="row"><span className="slicerFlushSlotLabel"><Swatch slot={from}/>
                  <span>{slotName(from)}</span></span></th>
                {visible.map(to=><td key={to.id}>
                  {String(from.id)===String(to.id) ? <span aria-label="Same filament">—</span> :
                  <><input className="slicerFlushCell" type="number" min="0" max="20000" step="1"
                    disabled={disabled} value={overrideFor(from,to)??""}
                    placeholder={estimateMode ? (()=>{
                      const estimate=estimateSlotFlush(from,to,{allowMixed:true});
                      const scaled=multiplyFlushEstimate(estimate,displayedMultiplier);
                      return scaled==null?"—":String(scaled);
                    })() : "—"}
                    title={estimateMode ? (slotMaterialCompatibility(from,to)==="mixed"
                      ? "† Mixed materials: colour contribution only, not a safe purge amount; never auto-copied."
                      : "Estimated colour contribution × preview multiplier, not a native purge amount.")
                      : "Blank = inherit; native slot value requires verified mapping"}
                    aria-label={`Flush ${slotName(from)} to ${slotName(to)}`}
                    onChange={e=>updateTransition(from,to,e.target.value)}/>
                    {estimateMode && slotMaterialCompatibility(from,to)==="mixed" && 
                      <span className="slicerFlushMixedMarker" title="Mixed material: unverified colour-only contribution">†</span>}</>}
                </td>)}
              </tr>)}</tbody>
            </table>
          </div> : <p className="projectUploadHint">Refresh at least two loaded filament slots to edit transitions.</p>}
          {!!native?.matrix ? <details>
            <summary>Native tool-indexed matrix from process profile</summary>
            <div className="slicerFlushTableScroll"><table className="slicerFlushMatrix">
              <thead><tr><th>Tool</th>{Array.from({length:native.tool_count},(_,i)=><th key={i}>T{i}</th>)}</tr></thead>
              <tbody>{Array.from({length:native.tool_count},(_,i)=><tr key={i}>
                <th>T{i}</th>{Array.from({length:native.tool_count},(_,j)=><td key={j}>
                  {native.matrix[i*native.tool_count+j]}</td>)}
              </tr>)}</tbody>
            </table></div>
          </details> : <p className="projectUploadHint">No native tool flushing matrix is defined in the selected
            process profile. It may instead be stored in the slicer's project settings.
            MakerVault cannot safely infer physical CFS-to-tool values from this profile.</p>}
          {slots.length>16&&<p className="formError">At most sixteen slots can be edited.</p>}
          <p className="projectUploadHint">The machine's native preset remains responsible for unloading,
            loading, purging and priming. These draft overrides are not firmware commands.</p>
        </div>
        <footer className="slicerFlushModalFooter">
          <button type="button" disabled={disabled||!value} onClick={()=>onChange?.(null)}>Reset to native</button>
          <button type="button" className="primary" onClick={()=>setOpen(false)}>Done</button>
        </footer>
      </section>
    </div>,document.body)}
  </>;
}
