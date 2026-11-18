import React, {useCallback, useEffect, useState} from "react";
import {apiFetch} from "../api";
import {SlicerEngineLogo} from "./SlicerEngineChoices";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export default function SlicerEngineManager({engines = [], canManage = false, onChanged}) {
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
    if(!canManage)return;
    refresh();
    // Refresh is only needed while the panel is visible; operator can also
    // explicitly refresh. No polling when it is closed/unmounted.
  },[canManage,refresh]);

  const operation = (state?.operations || []).find(row => !TERMINAL.has(row.status));
  const releases=state?.approved_releases || [];
  const request=async(release,action)=>{
    if(!state?.installation_available || busy || operation)return;
    const label=engines.find(row=>row.key===release.engine)?.label||release.engine;
    if(!window.confirm(
      action==="update"
        ? "Update "+label+" to "+release.version+"? Active slicing jobs must finish first. The current version will remain available for rollback."
        : "Install "+label+" "+release.version+"? Only the independently approved binary will be installed by the restricted host updater."
    ))return;
    setBusy(true);setError("");setNotice("");
    try{
      const result=await apiFetch("/api/printing/slicer/engines/operations/",{
        method:"POST",body:{
          engine:release.engine,version:release.version,action,
          release_sha256:release.bundle_sha256,
        },
      });
      setNotice("Request queued: "+result.operation.engine+" "+result.operation.version+
        ". Activation requires validation by the host updater.");
      await refresh();
      onChanged?.();
    }catch(e){setError(e.message);}
    finally{setBusy(false);}
  };

  return <section className="slicerEngineManager" aria-label="Engine installations and updates">
    <div className="slicerEngineManagerHeading">
      <div>
        <h4>Installed engines and approved updates</h4>
        <p>All engines use the same isolated slicer worker. Installed versions are preserved for rollback.</p>
      </div>
      {canManage && <button type="button" onClick={refresh} disabled={busy}>Refresh</button>}
    </div>
    {!canManage && <p role="status">Only a MakerVault administrator can view approved updates or request engine installation.</p>}
    {error && <p role="alert" className="integrationError">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <div className="slicerEngineManagerList">
      {engines.map(engine=>{
        const approved=releases.filter(release=>release.engine===engine.key);
        return <article key={engine.key} className="slicerEngineManagerCard">
          <div className="slicerEngineManagerIdentity">
            <SlicerEngineLogo engine={engine.key} label={engine.label} size="small"/>
            <div><strong>{engine.label}</strong>
              <small>{engine.available
                ? "Installed · "+(engine.installed_version||"Verified")
                : "Not installed / not validated"}</small>
            </div>
          </div>
          {approved.length>0 ? approved.map(release=><div key={release.version+"-"+release.bundle_sha256}
            className="slicerEngineManagerRelease">
            <div><strong>Approved {release.version}</strong>
              <small>{release.architecture} · {release.notes||"Reviewed release"}</small>
            </div>
            <button type="button" disabled={busy || !!operation || !state?.installation_available ||
              engine.installed_version===release.version}
              onClick={()=>request(release,engine.available?"update":"install")}>
              {engine.available?"Update":"Install"}
            </button>
          </div>) : <small>No approved installation release is available yet.</small>}
        </article>;
      })}
    </div>
    {canManage && <div className="slicerEngineManagerStatus">
      <h4>Host updater</h4>
      <p>{state?.host_updater_connected
        ? "Host updater enabled. Operations are queued for an independently provisioned maintenance service."
        : "Not connected. Engine installation and updates are unavailable until a restricted host updater is configured."}</p>
      {operation && <p role="status"><strong>{operation.engine} {operation.version}</strong> ·
        {" "+operation.action+" · "+operation.status+" · "+operation.progress+"%"}
        {operation.message && " · "+operation.message}</p>}
      {state?.operations?.length>0 && <details>
        <summary>Recent engine operations</summary>
        <ul>{state.operations.slice(0,10).map(item=><li key={item.id}>
          {item.engine} {item.version} · {item.action} · {item.status}
        </li>)}</ul>
      </details>}
      <small>Updating an engine never automatically starts a printer job. Each installed binary must pass independent checksum and worker compatibility checks before slicing can use it.</small>
    </div>}
  </section>;
}
