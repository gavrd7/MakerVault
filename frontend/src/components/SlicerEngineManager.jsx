import React, {useCallback, useEffect, useMemo, useState} from "react";
import {apiFetch} from "../api";
import {SlicerEngineLogo} from "./SlicerEngineChoices";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function EngineReleasePicker({engine, releases, installedVersions, installed, disabled, onRequest}) {
  const [selection,setSelection] = useState("");
  const available = useMemo(()=>{
    const options = [];
    const seen = new Set();
    for (const row of installedVersions) {
      if (!row || typeof row.version !== "string" || seen.has(row.version)) continue;
      seen.add(row.version);
      options.push({version:row.version, local:true, digest:"", active:!!row.active});
    }
    for (const row of releases) {
      if (!row || typeof row.version !== "string" || seen.has(row.version)) continue;
      seen.add(row.version);
      options.push({version:row.version, local:false, digest:row.bundle_sha256, active:false});
    }
    if (installed && engine.installed_version && !seen.has(engine.installed_version)) {
      options.push({version:engine.installed_version,local:true,digest:"",active:true});
    }
    return options.sort((a,b)=>b.version.localeCompare(a.version,undefined,{numeric:true}));
  },[installedVersions,releases,installed,engine.installed_version]);
  const chosen = available.find(row=>row.version===selection) ||
    available.find(row=>row.version===engine.installed_version) || available[0];

  if (!chosen) return <small>Installation package not yet available.</small>;
  const current = installed && chosen.version === engine.installed_version;
  const canSelect = available.length>1 || !current;
  return <div className="slicerEngineManagerControls">
    <div className="slicerEngineManagerRelease" style={{display:"flex",alignItems:"center",gap:"0.75rem",flexWrap:"wrap"}}>
      <label style={{display:"flex",alignItems:"center",gap:"0.5rem",flex:"1 1 11rem",minWidth:0}}>
        <span>Version</span>
        <select aria-label={engine.label+" version"} value={chosen.version}
          onChange={event=>setSelection(event.target.value)}
          disabled={disabled || !canSelect} style={{minWidth:0,width:"100%"}}>
          {available.map(row=><option key={row.version} value={row.version}>
            {row.version}{installed && engine.installed_version===row.version ? " (installed)" : row.local ? " (available locally)" : ""}
          </option>)}
        </select>
      </label>
      {!current && <button type="button" disabled={disabled}
        onClick={()=>onRequest(engine.key, chosen.version,
          chosen.local ? "activate" : installed ? "update" : "install",chosen.digest)}>
        {chosen.local ? "Switch" : installed ? "Update" : "Install"}
      </button>}
    </div>
    {installed && <div className="slicerEngineManagerRemove" style={{display:"flex",justifyContent:"flex-end",marginTop:"0.5rem"}}>
      <button type="button" disabled={disabled} className="secondary"
        onClick={()=>onRequest(engine.key,"all","uninstall","")}>
        Uninstall
      </button>
    </div>}
  </div>;
}

export default function SlicerEngineManager({engines = [], onChanged}) {
  const [state,setState] = useState(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");

  const refresh=useCallback(async()=>{
    try {
      const result=await apiFetch("/api/printing/slicer/engines/operations/");
      setState(result);setError("");
      if (TERMINAL.has(result.operations?.[0]?.status)) setNotice("");
    } catch(e){setError(e.message);}
  },[]);
  useEffect(()=>{
    refresh();
    const timer=window.setInterval(()=>{
      refresh();
      onChanged?.();
    },2500);
    return ()=>window.clearInterval(timer);
  },[refresh,onChanged]);

  const operation=(state?.operations||[]).find(row=>!TERMINAL.has(row.status));
  const lastOperation=(state?.operations||[])[0];
  const releases=state?.approved_releases||[];
  const canManage=state?.can_manage !== false;
  const canOperate=!!state?.host_updater_connected && !busy && !operation && canManage;

  const request=async(engine,version,action,digest)=>{
    if(!canOperate || (action!=="activate" && action!=="uninstall" && !state?.installation_available))return;
    const label=engines.find(row=>row.key===engine)?.label||engine;
    const question=action==="uninstall"
      ? "Uninstall "+label+" and all its stored engine versions? Existing G-code and MakerVault data will remain. This cannot be undone without reinstalling."
      : action==="activate"
        ? "Switch "+label+" to the already installed version "+version+"? Active slicing jobs must finish first."
        : action==="update"
          ? "Change "+label+" to "+version+"? Active slicing jobs must finish first. Older installed versions will remain available."
          : "Install "+label+" "+version+"? MakerVault will verify the official download and compatibility.";
    if(!window.confirm(question))return;
    setBusy(true);setError("");setNotice("");
    try {
      const result=await apiFetch("/api/printing/slicer/engines/operations/",{
        method:"POST",body:{
          engine,version,action,
          release_sha256:action==="uninstall"||action==="activate"?"0".repeat(64):digest,
        },
      });
      setNotice(label+" "+action+" requested.");
      await refresh();
      onChanged?.();
    } catch(e){setError(e.message);}
    finally{setBusy(false);}
  };

  return <section className="slicerEngineManager" aria-label="Engine installations and updates">
    <div className="slicerEngineManagerHeading">
      <div>
        <h4>Installed engines and versions</h4>
        <p>Install, change versions or uninstall individual engines. Official downloads and compatibility are verified before activation.</p>
      </div>
      <button type="button" onClick={refresh} disabled={busy}>Refresh</button>
    </div>
    {!canManage && <p role="status">Engine changes are restricted by this instance’s administrator.</p>}
    {error && <p role="alert" className="integrationError">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!operation && lastOperation?.status==="failed" &&
      <p role="alert" className="integrationError">
        {lastOperation.engine} {lastOperation.version} {lastOperation.action} failed: {lastOperation.message || "Check installer status."}
      </p>}
    {!operation && lastOperation?.status==="completed" &&
      <p role="status">{lastOperation.engine} {lastOperation.version}: {lastOperation.message || "Engine operation complete."}</p>}
    <div className="slicerEngineManagerList">
      {engines.map(engine=>{
        const approved=releases.filter(row=>row.engine===engine.key);
        const installed=engine.available===true || engine.status==="validated";
        const versions=state?.installed_versions?.[engine.key]||[];
        const matching=(state?.operations||[]).find(item=>item.engine===engine.key && !TERMINAL.has(item.status));
        return <article key={engine.key} className="slicerEngineManagerCard">
          <div className="slicerEngineManagerIdentity">
            <SlicerEngineLogo engine={engine.key} label={engine.label} size="small"/>
            <div><strong>{engine.label}</strong>
              <small>{installed
                ? "Installed · "+(engine.installed_version||"Current")+
                  (engine.key==="crealityprint"?" · CLI integration in testing":"")
                : "Not installed"}</small>
            </div>
          </div>
          {matching && <div role="status" className="slicerEngineManagerRelease">
            <strong>{matching.action} · {matching.status} · {matching.progress}%</strong>
            <small>{matching.message}</small>
          </div>}
          <EngineReleasePicker engine={engine} releases={approved} installedVersions={versions}
            installed={installed} disabled={!canOperate} onRequest={request}/>
        </article>;
      })}
    </div>
    <div className="slicerEngineManagerStatus">
      <h4>Installation service</h4>
      <p>{state?.host_updater_connected
        ? "Installer connected."
        : "Installer not configured on this server. Existing engines remain usable."}</p>
      {operation && <p role="status"><strong>{operation.engine} {operation.version}</strong> ·
        {" "+operation.action+" · "+operation.status+" · "+operation.progress+"%"}
        {operation.message && " · "+operation.message}</p>}
      {state?.operations?.length>0 && <details>
        <summary>Recent engine operations</summary>
        <ul>{state.operations.slice(0,10).map(item=><li key={item.id}>
          {item.engine} {item.version} · {item.action} · {item.status}
          {item.status==="failed" && item.message ? " · "+item.message : ""}
        </li>)}</ul>
      </details>}
      <small>Engine changes do not start printer jobs. Your models and existing G-code remain untouched.</small>
    </div>
  </section>;
}
