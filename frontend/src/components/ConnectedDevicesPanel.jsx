import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";

export default function ConnectedDevicesPanel() {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [step, setStep] = useState(0);
  const [networkReady, setNetworkReady] = useState(false);
  const [httpsReady, setHttpsReady] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [initialScopes, setInitialScopes] = useState(["tags:read", "devices:status"]);
  const [kind, setKind] = useState("rfid_terminal");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);
  const [editName, setEditName] = useState("");
  const [editScopes, setEditScopes] = useState([]);
  const [awaiting, setAwaiting] = useState(null);

  async function reload() {
    const result = await apiFetch("/api/account/connected-devices/");
    setRows(result.rows || []);
  }
  useEffect(() => { reload().catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (!awaiting) return undefined;
    let stopped = false;
    async function check() {
      try {
        const data = await apiFetch("/api/account/connected-devices/");
        if (stopped) return;
        setRows(data.rows || []);
        const paired = (data.rows || []).find(device => device.device_uid === awaiting.device_uid && !device.revoked_at);
        if (paired) {
          setAwaiting(null);
          setNotice(`${paired.name} has completed pairing. Waiting for its first heartbeat to report API connectivity.`);
        }
      } catch (e) { if (!stopped) setError(e.message); }
    }
    check();
    const timer = window.setInterval(check, 3000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [awaiting]);

  async function approve(event) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const scopes = initialScopes;
      const result = await apiFetch("/api/account/connected-devices/pair/approve/", {
        method: "POST",
        body: JSON.stringify({ name, confirmation_code: code, device_type: kind, scopes }),
      });
      setAwaiting({ device_uid: result.device_uid, pairing_id: result.pairing_id });
      setAdding(false); setStep(0); setCode(""); setName("");
      setNotice("Approved. Waiting for the device to collect and save its credential…");
      await reload();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const permissionOptions = {
    rfid_terminal: [
      ["tags:read", "Read and resolve tags"],
      ["inventory:read", "Search inventory and spools"],
      ["tags:write", "Register and assign tags"],
      ["devices:status", "Update device connection status"],
    ],
    filament_scale: [
      ["tags:read", "Read and resolve tags"],
      ["inventory:read", "Search inventory and spools"],
      ["spools:weight", "Record confirmed spool weights"],
      ["devices:status", "Update device connection status"],
    ],
  };

  function beginEdit(device) {
    setEditing(device.id);
    setEditName(device.name);
    setEditScopes([...(device.scopes || [])]);
    setError(""); setNotice("");
  }

  async function saveEdit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await apiFetch(`/api/account/connected-devices/${editing}/`, {
        method: "PATCH", body: JSON.stringify({ name: editName, scopes: editScopes }),
      });
      setEditing(null);
      setNotice("Device permissions updated. Changes take effect on its next API request.");
      await reload();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function revoke(device) {
    if (!window.confirm(`Unpair ${device.name}? Its API credential will be revoked immediately.`)) return;
    setBusy(true); setError("");
    try {
      await apiFetch(`/api/account/connected-devices/${device.id}/revoke/`, { method: "POST" });
      setNotice(`${device.name} was unpaired.`);
      await reload();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return <section className="panel settingsPanel">
    <div className="panelHead">
      <div><h3>Connected Devices</h3><p>Manage MakerVault hardware and approve secure device pairing.</p></div>
      <button type="button" className="primary" onClick={() => { setAdding(!adding); setStep(0); }}> {adding ? "Cancel" : "Add Device"} </button>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="notice">{notice}</p>}
    {awaiting && <div role="status" className="notice"><strong>Waiting for device confirmation.</strong> The device must complete pairing over verified HTTPS. Refreshing the registered device list automatically. If the one-time token is lost, unpair and start again. <button type="button" onClick={() => { setAwaiting(null); reload().catch(e => setError(e.message)); }}>Stop watching</button></div>}
    {adding && <div className="deviceWizard">
      <div className="deviceWizardProgress" aria-label="Pairing wizard progress">
        {["Device & permissions", "Network setup", "Secure pairing", "Approve"].map((label, index) =>
          <div key={label} className={`deviceWizardProgressItem ${index === step ? "current" : index < step ? "done" : ""}`}>
            <span className="deviceWizardNumber">{index + 1}</span><span>{label}</span>
          </div>)}
      </div>
      {step === 0 && <div className="deviceWizardPage">
        <h4>1. Choose your device</h4>
        <p>Select the hardware you want to connect. These settings will be submitted when you approve the device's pairing code.</p>
        <div className="formGrid">
          <label>Device type<select value={kind} onChange={e => { setKind(e.target.value); setInitialScopes(["tags:read", "devices:status"]); }}>
            <option value="rfid_terminal">RFID/NFC terminal</option><option value="filament_scale">Filament weighing station</option>
          </select></label>
          <label>Device name<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} placeholder="Workshop reader" /></label>
        </div>
        <fieldset className="devicePermissionGroup"><legend>Permissions</legend>
          <p>Read-only tag access and connection reporting are enabled by default. Additional access is optional.</p>
          <div className="devicePermissionList">
            {(permissionOptions[kind] || []).map(([scope, label]) => <label key={scope} className="devicePermissionOption">
              <input type="checkbox" checked={initialScopes.includes(scope)} onChange={e => setInitialScopes(old =>
                e.target.checked ? [...old, scope] : old.filter(item => item !== scope))} />
              <span className="devicePermissionText"><strong>{label}</strong><small>{scope}{scope === "tags:write" || scope === "spools:weight" ? " · Write access" : ""}</small></span>
            </label>)}
          </div>
        </fieldset>
      </div>}
      {step === 1 && <div className="deviceWizardPage">
        <h4>2. Connect the device to Wi-Fi</h4>
        <p>MakerVault cannot connect to or discover hardware that has not joined a network.</p>
        <div className="deviceWizardInfo">
          <strong>Already connected?</strong><p>Use your terminal's saved Wi-Fi connection and continue.</p>
          <strong>Using a phone?</strong><p>On the terminal, open its Connections setup and use the LAN QR webpage, or start its temporary setup Wi-Fi when offline. Enter Wi-Fi credentials locally on the device.</p>
          <strong>Desktop setup</strong><p>Use the hardware's local configuration page or a compatible USB setup helper, if available.</p>
        </div>
        <label className="devicePermissionOption"><input type="checkbox" checked={networkReady} onChange={e => setNetworkReady(e.target.checked)} /><span>My device is connected to a usable network.</span></label>
      </div>}
      {step === 2 && <div className="deviceWizardPage">
        <h4>3. Enable verified HTTPS</h4>
        <div className="deviceWizardRequirement"><strong>HTTPS is required to pair devices.</strong><p>Enable HTTPS for MakerVault before continuing. Both the browser approval and the terminal's API connection must use secure HTTPS.</p></div>
        <p>Configure the MakerVault HTTPS URL in your terminal. Publicly trusted certificates normally work automatically; for self-signed/private certificates, explicitly install the trusted CA or certificate on the device. Never disable TLS verification.</p>
        <p>Then open <strong>Connections → MakerVault → Pair device</strong> on the terminal. It will request and display an eight-digit code from MakerVault. The terminal + phone method uses the same pairing API and approval below.</p>
        <label className="devicePermissionOption"><input type="checkbox" checked={httpsReady} onChange={e => setHttpsReady(e.target.checked)} /><span>MakerVault HTTPS is enabled and the device trusts its certificate.</span></label>
      </div>}
      {step === 3 && <div className="deviceWizardPage">
        <h4>4. Approve the pairing code</h4>
        <p>Enter the server-issued eight-digit code displayed on the device. The code expires after five minutes. Never type your MakerVault password or a permanent API key into the device.</p>
        <form id="devicePairApproval" onSubmit={approve}>
          <label className="deviceWizardCodeLabel">Eight-digit pairing code
            <input required autoComplete="off" inputMode="numeric" pattern="[0-9]{8}" maxLength={8} value={code}
              onChange={e => setCode(e.target.value.split("").filter(char => char >= "0" && char <= "9").join(""))} placeholder="00000000" />
          </label>
          <p><strong>Device:</strong> {name.trim()} ({kind === "rfid_terminal" ? "RFID/NFC terminal" : "Filament weighing station"})</p>
          <p><strong>Permissions:</strong> {initialScopes.join(", ")}</p>
          <p>After approval, MakerVault will watch for the terminal to complete pairing and store its credential.</p>
        </form>
      </div>}
      <div className="deviceWizardActions">
        <button type="button" disabled={busy} onClick={() => { if (step === 0) { setAdding(false); } else { setStep(step - 1); } }}>{step === 0 ? "Cancel" : "Back"}</button>
        {step < 3 ? <button type="button" className="primary" disabled={busy || (step === 0 && (!name.trim() || !initialScopes.length)) || (step === 1 && !networkReady) || (step === 2 && !httpsReady)} onClick={() => setStep(step + 1)}>Continue</button> :
          <button form="devicePairApproval" className="primary" disabled={busy || code.length !== 8 || !name.trim() || !initialScopes.length}>Approve pairing</button>}
      </div>
    </div>}
    {rows.length === 0 ? <p>No devices paired yet.</p> : <div className="settingsList">
      {rows.map(device => <article key={device.id} className="settingsListItem">
        <div>
          <strong>{device.name}</strong>
          <p>{device.device_type === "rfid_terminal" ? "RFID/NFC Terminal" : "Filament Weighing Station"} · {device.revoked_at ? "Unpaired" : device.online ? "Recently connected" : "Offline / not recently seen"}</p>
          <small>Device ID: {device.device_uid} · Scopes: {(device.scopes || []).join(", ") || "None"} · Last seen: {device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : "Never"}</small>
          <p><small>Wi-Fi: {device.online ? (device.reported_status?.wifi || "Not reported") : "Unknown (offline)"} · MakerVault API: {device.online ? "Recently verified" : "Offline / no heartbeat"} · Hardware: {device.online ? (device.reported_status?.hardware || "Not reported") : "Unknown (offline)"}</small></p>
        </div>
        {!device.revoked_at && <div style={{ display: "flex", gap: 8 }}>
          <button type="button" disabled={busy} onClick={() => beginEdit(device)}>Edit</button>
          <button type="button" disabled={busy} onClick={() => revoke(device)}>Unpair</button>
        </div>}
        {editing === device.id && <form onSubmit={saveEdit} style={{ width: "100%", paddingTop: 12 }}>
          <h4>Edit device permissions</h4>
          <label>Device name <input required maxLength={120} value={editName} onChange={e => setEditName(e.target.value)} /></label>
          <div className="devicePermissionList">
            {(permissionOptions[device.device_type] || []).map(([scope, label]) =>
              <label key={scope} className="devicePermissionOption">
                <input type="checkbox" checked={editScopes.includes(scope)} onChange={e => setEditScopes(old => e.target.checked ? [...old, scope] : old.filter(x => x !== scope))} />
                {label} <small>({scope})</small>
              </label>)}
          </div>
          <p>Permissions are enforced immediately. A previously issued credential cannot gain rights beyond those selected here.</p>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="primary" disabled={busy || !editScopes.length || !editName.trim()}>Save changes</button>
            <button type="button" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </form>}
      </article>)}
    </div>}
    <p>Wi-Fi connection, MakerVault API access and device health are separate statuses. Offline devices remain registered; a temporary network outage does not reopen setup mode.</p>
  </section>;
}
