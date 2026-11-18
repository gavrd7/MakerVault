import React, {useCallback, useEffect, useState} from "react";
import {apiFetch} from "../api";
import {SlicerEngineLogo} from "./SlicerEngineChoices";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export default function SlicerEngineManager({engines = [], onChanged}) {
  const [state,setState] = useState(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");

  const refresh=useCallback(async()=>{
    try {
      const result=await apiFetch("/api/printing/slicer/engines/operations/");
      setState(result);setError("");
    } catch(e){setError(e.message);}
  },[]);
  useEffect(()=>{
    refresh();
    // Refresh is only needed while the panel is visible; operator can also
    // explicitly refresh. No polling when it is closed/unmounted.
  },[refresh]);

  const operation = (state?.operations || []).find(row => !TERMINAL.has(row.status));
  const releases=state?.approved_releases || [];
  const canManage=state?.can_manage !== false;
  const request=async(release,action)=>{
    if(!canManage || !state?.installation_available || busy || operation)return;
    const label=engines.find(row=>row.key===release.engine)?.label||release.engine;
    if(!window.confirm(
      action==="update"
        ? "Update "+label+" to "+release.version+"? Active slicing jobs must finish first. The current version will remain available for rollback."
        : "Install "+label+" "+release.version+"? MakerVault will check the download and compatibility automatically."
    ))return;
    setBusy(true);setError("");setNotice("");
    try{
      const result=await apiFetch("/api/printing/slicer/engines/operations/",{
        method:"POST",body:{
          engine:release.engine,version:release.version,action,
          release_sha256:release.bundle_sha256,
        },
      });
      setNotice("Installation queued for "+result.operation.engine+" "+result.operation.version+".");
      await refresh();
      onChanged?.();
    }catch(e){setError(e.message);}
    finally{setBusy(false);}
  };

  return <section className="slicerEngineManager" aria-label="Engine installations and updates">
    <div className="slicerEngineManagerHeading">
      <div>
        <h4>Installed engines and updates</h4>
        <p>Manage installed engines and available updates. MakerVault will check downloads and compatibility automatically.</p>
      </div>
      <button type="button" onClick={refresh} disabled={busy}>Refresh</button>
    </div>
    {!canManage && <p role="status">Engine installation is restricted by this instance’s administrator.</p>}
    {error && <p role="alert" className="integrationError">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <div className="slicerEngineManagerList">
      {engines.map(engine=>{
        const approved=releases.filter(release=>release.engine===engine.key);
        const installed=engine.available === true || engine.status === "validated";
        return <article key={engine.key} className="slicerEngineManagerCard">
          <div className="slicerEngineManagerIdentity">
            <SlicerEngineLogo engine={engine.key} label={engine.label} size="small"/>
            <div><strong>{engine.label}</strong>
              <small>{installed
                ? "Installed and ready · "+(engine.installed_version||"Verified")
                : "Not installed"}</small>
            </div>
          </div>
          {approved.length>0 ? approved.map(release=><div key={release.version+"-"+release.bundle_sha256}
            className="slicerEngineManagerRelease">
            <div><strong>Version {release.version}</strong>
              <small>{release.architecture} · {release.notes||"Reviewed release"}</small>
            </div>
            <button type="button" disabled={busy || !!operation || !state?.installation_available ||
              engine.installed_version===release.version || !canManage}
              onClick={()=>request(release,installed?"update":"install")}>
              {installed?"Update":"Install"}
            </button>
          </div>) : <small>{installed ? "Already installed — no newer version available." : "Installation package not yet available."}</small>}
        </article>;
      })}
    </div>
    <div className="slicerEngineManagerStatus">
      <h4>Installation service</h4>
      <p>{state?.host_updater_connected
        ? "Installer connected."
        : "Installer not yet configured on this server. Existing engines remain usable."}</p>
      {operation && <p role="status"><strong>{operation.engine} {operation.version}</strong> ·
        {" "+operation.action+" · "+operation.status+" · "+operation.progress+"%"}
        {operation.message && " · "+operation.message}</p>}
      {state?.operations?.length>0 && <details>
        <summary>Recent engine operations</summary>
        <ul>{state.operations.slice(0,10).map(item=><li key={item.id}>
          {item.engine} {item.version} · {item.action} · {item.status}
        </li>)}</ul>
      </details>}
      <small>Updates do not start printer jobs. Existing installations remain available while an update is prepared.</small>
    </div>
  </section>;
}
