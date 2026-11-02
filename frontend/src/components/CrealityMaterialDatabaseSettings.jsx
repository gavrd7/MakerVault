import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";

export default function CrealityMaterialDatabaseSettings() {
  const [printers, setPrinters] = useState([]);
  const [selected, setSelected] = useState("");
  const [connections, setConnections] = useState([]);
  const [forms, setForms] = useState({});
  const [feedback, setFeedback] = useState(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    let active = true;
    apiFetch("/api/printing/?include_filaments=0")
      .then(result => {
        if (!active) return;
        const rows = (result.printers || []).filter(p =>
          String(p.manufacturer || "").toLowerCase().includes("creality"));
        setPrinters(rows);
        setSelected(current => current || String(rows[0]?.id || ""));
      })
      .catch(err => { if (active) setFeedback({type: "error", message: err.message}); });
    return () => { active = false; };
  }, []);

  async function loadConnections(printerId) {
    if (!printerId) { setConnections([]); return; }
    try {
      const result = await apiFetch("/api/printing/printers/" + printerId + "/connections/");
      setConnections((result.rows || []).filter(item => item.adapter === "creality_local"));
    } catch (err) {
      setFeedback({type: "error", message: err.message});
    }
  }

  useEffect(() => { setFeedback(null); loadConnections(selected); }, [selected]);

  function form(connection) {
    return forms[connection.id] || {
      username: connection.config?.material_ssh_user || "",
      password: "",
      fingerprint: connection.config?.material_ssh_fingerprint || "",
      scheduled: Boolean(connection.config?.material_database_scheduled),
    };
  }

  function update(connection, patch) {
    setForms(previous => ({...previous, [connection.id]: {...form(connection), ...patch}}));
  }

  async function run(connection, action) {
    if (busy) return;
    setFeedback(null);
    const settings = form(connection);
    if (action === "configure" && !/^SHA256:[A-Za-z0-9+/]{43}=?$/.test(settings.fingerprint.trim())) {
      setFeedback({type: "error", message: "Enter a verified SHA256 host-key fingerprint, or detect and confirm the printer key first."});
      return;
    }
    setBusy(action);
    try {
      const url = "/api/printing/printers/" + selected + "/connections/" + connection.id + "/material-database/";
      const result = await apiFetch(url, {method: "POST", body: action === "configure"
        ? {action, ...settings, fingerprint: settings.fingerprint.trim()} : {action}});
      if (action === "discover-key") {
        const fingerprint = result.host_key?.fingerprint;
        if (!fingerprint?.startsWith("SHA256:")) throw new Error("No ED25519 fingerprint returned.");
        if (window.confirm("Detected printer ED25519 fingerprint:\\n" + fingerprint +
          "\\n\\nVerify it against a trusted source before accepting and saving it.")) {
          update(connection, {fingerprint});
          setFeedback({type: "success", message: "Host key selected. Save settings to pin it."});
        }
      } else if (action === "configure") {
        update(connection, {password: ""});
        setFeedback({type: "success", message: "Printer database settings saved."});
        await loadConnections(selected);
      } else {
        setFeedback({type: "success", message: "Read-only printer database copy complete. " +
          result.result.top_level_items + " top-level JSON entries retrieved."});
        await loadConnections(selected);
      }
    } catch (err) {
      setFeedback({type: "error", message: err.message});
    } finally {
      setBusy("");
    }
  }

  return <section className="panel settingsPanel crealityMaterialSettings">
    <div className="panelHead"><div>
      <h3>Creality printer material databases</h3>
      <p>Copy a printer's own material database to MakerVault. This is separate from the CFS live-slot integration and never writes to the printer or automatically changes the Filament Library.</p>
    </div></div>
    <div className="crealityMaterialBody">
      <label className="crealityMaterialField"><span>Printer</span>
        <select value={selected} onChange={e => setSelected(e.target.value)}>
          {printers.map(printer => <option key={printer.id} value={printer.id}>{printer.name} · {printer.model}</option>)}
        </select>
      </label>
      {!printers.length && <p>No Creality printers are configured in the 3D Printing area.</p>}
      {connections.map(connection => <div className="crealityMaterialCard" key={connection.id}>
        <div className="crealityMaterialHeading">
          <strong>{connection.adapter_label} · {connection.endpoint_url || "Printer connection"}</strong>
          <small>{connection.enabled ? "Connection enabled" : "Connection disabled"}</small>
        </div>
        {feedback && <div role={feedback.type === "error" ? "alert" : "status"}
          className={feedback.type === "error" ? "formError" : "notice"}>{feedback.message}</div>}
        <div className="crealityMaterialFields">
          <label className="crealityMaterialField"><span>SSH username</span>
            <input autoComplete="username" value={form(connection).username}
              onChange={e => update(connection, {username: e.target.value})}/></label>
          <label className="crealityMaterialField"><span>SSH password</span>
            <input type="password" autoComplete="new-password" value={form(connection).password}
              placeholder={connection.config?.material_ssh_password_configured ? "Saved — leave blank to retain" : "Printer SSH password"}
              onChange={e => update(connection, {password: e.target.value})}/></label>
          <label className="crealityMaterialField crealityMaterialFull"><span>Verified host-key fingerprint (SHA256)</span>
            <input value={form(connection).fingerprint} placeholder="SHA256:..."
              onChange={e => update(connection, {fingerprint: e.target.value})}/></label>
        </div>
        <div className="crealityMaterialKey">
          <button type="button" disabled={Boolean(busy)} onClick={() => run(connection, "discover-key")}>Detect host key</button>
          <small>Detects the ED25519 key without logging in. Confirm the fingerprint against a trusted source before saving.</small>
        </div>
        <label className="settingsToggle compact">
          <div><strong>Automatic read-only sync</strong><small>Check the printer database daily. Leave off until a manual copy succeeds.</small></div>
          <input type="checkbox" checked={form(connection).scheduled}
            onChange={e => update(connection, {scheduled: e.target.checked})}/>
        </label>
        <div className="crealityMaterialFooter">
          <small>Scheduled: {connection.config?.material_database_scheduled ? "Enabled" : "Off"} · Last copy: {connection.config?.material_database_synced_at ? new Date(connection.config.material_database_synced_at).toLocaleString() : "Never"}</small>
          <div className="settingsActions compact">
            <button type="button" disabled={Boolean(busy)} onClick={() => run(connection, "configure")}>{busy === "configure" ? "Saving…" : "Save settings"}</button>
            <button type="button" disabled={Boolean(busy) || !connection.enabled} onClick={() => run(connection, "pull")}>{busy === "pull" ? "Synchronising…" : "Sync from printer now"}</button>
          </div>
        </div>
      </div>)}
      {!!selected && !connections.length && <p>No Creality local connection is configured for this printer. Add one from 3D Printing → Live Monitoring.</p>}
    </div>
  </section>;
}
