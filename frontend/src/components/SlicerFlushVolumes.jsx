import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "../api";

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
            <label>Flush multiplier
              <input type="number" min=".1" max="3" step=".1" disabled={disabled}
                value={data.multiplier ?? nativeMultiplier ?? ""} placeholder={nativeMultiplier!=null?String(nativeMultiplier):"Not defined"}
                onChange={e=>{
                  const raw=e.target.value;
                  if(!raw.trim()){onChange?.({...data,multiplier:null});return;}
                  const n=Number(raw);if(n>=.1&&n<=3)onChange?.({...data,multiplier:n});
                }}/>
              <small>{data.multiplier===null
                ? nativeMultiplier!=null?"Inherited from process profile · "+nativeMultiplier+" (edit to override)":"Not defined in selected process profile"
                :"Overriding native multiplier"}</small>
            </label>
            <label>Prime tower
              <select disabled={disabled} value={data.prime_tower}
                onChange={e=>onChange?.({...data,prime_tower:e.target.value})}>
                <option value="native">Native default {native?.prime_tower==null?"(unknown)":native.prime_tower?"(enabled)":"(disabled)"}</option>
                <option value="enabled">Enabled</option><option value="disabled">Disabled</option>
              </select>
            </label>
          </div>
          <h4>Directional flushing · mm³</h4>
          <p className="projectUploadHint">Each row represents the filament being unloaded;
            each column is the filament being loaded. Blank fields inherit their native
            values only when matching tools have been verified.</p>
          {visible.length>=2 ? <div className="slicerFlushTableScroll">
            <table className="dataTable slicerFlushTable">
              <thead><tr><th>From / To</th>{visible.map(slot=><th key={slot.id}>
                <span className="slicerFlushSlotLabel"><Swatch slot={slot}/>
                  <span>{slotName(slot)}</span></span>
              </th>)}</tr></thead>
              <tbody>{visible.map(from=><tr key={from.id}>
                <th><span className="slicerFlushSlotLabel"><Swatch slot={from}/>
                  <span>{slotName(from)}</span></span></th>
                {visible.map(to=><td key={to.id}>{String(from.id)===String(to.id)?"—":
                  <input type="number" min="0" max="20000" step="1"
                    disabled={disabled} value={overrideFor(from,to)??""}
                    placeholder="Inherit" aria-label={`Flush ${slotName(from)} to ${slotName(to)}`}
                    onChange={e=>updateTransition(from,to,e.target.value)}/>}</td>)}
              </tr>)}</tbody>
            </table>
          </div> : <p className="projectUploadHint">Refresh at least two loaded filament slots to edit transitions.</p>}
          {!!native?.matrix && <details>
            <summary>Native tool-indexed values (not physical slot mappings)</summary>
            <div className="slicerFlushTableScroll"><table className="dataTable slicerFlushTable">
              <thead><tr><th>Tool</th>{Array.from({length:native.tool_count},(_,i)=><th key={i}>T{i}</th>)}</tr></thead>
              <tbody>{Array.from({length:native.tool_count},(_,i)=><tr key={i}>
                <th>T{i}</th>{Array.from({length:native.tool_count},(_,j)=><td key={j}>
                  {native.matrix[i*native.tool_count+j]}</td>)}
              </tr>)}</tbody>
            </table></div>
          </details>}
          {!native?.matrix && <p className="projectUploadHint">This process profile has no inspectable native
            flushing matrix. No volume is assumed from filament colour.</p>}
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
