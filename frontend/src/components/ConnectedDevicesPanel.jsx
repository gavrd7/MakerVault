import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";

export default function ConnectedDevicesPanel() {
  const [rows, setRows] = useState([]);
  const [adding, setAdding] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [write, setWrite] = useState(false);
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
      const scopes = kind === "filament_scale" ? ["tags:read", "inventory:read", "devices:status"] :
        write ? ["tags:read", "tags:write", "devices:status"] : ["tags:read", "devices:status"];
      const result = await apiFetch("/api/account/connected-devices/pair/approve/", {
        method: "POST",
        body: JSON.stringify({ name, confirmation_code: code, device_type: kind, scopes }),
      });
      setAwaiting({ device_uid: result.device_uid, pairing_id: result.pairing_id });
      setAdding(false); setCode(""); setName("");
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
      <button type="button" className="primary" onClick={() => setAdding(!adding)}> {adding ? "Cancel" : "Add Device"} </button>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="notice">{notice}</p>}
    {awaiting && <div role="status" className="notice"><strong>Waiting for device confirmation.</strong> The device must complete pairing over verified HTTPS. Refreshing the registered device list automatically. If the one-time token is lost, unpair and start again. <button type="button" onClick={() => { setAwaiting(null); reload().catch(e => setError(e.message)); }}>Stop watching</button></div>}
    {adding && <div className="settingsPanel">
      <h4>Connect a hardware device</h4>
      <p><strong>MakerVault-led setup (recommended).</strong> Choose the device type, name and permissions below. Complete Wi-Fi setup on the terminal first; the server cannot discover an unnetworked ESP32.</p>
      <p><strong>1. Prepare the connection.</strong> On a phone, join the setup Wi-Fi shown on your device and enter your home Wi-Fi credentials in its local portal. On a desktop, connect using the device's setup access point or a compatible USB setup utility. MakerVault cannot contact hardware that has not joined a network.</p>
      <p><strong>2. Verify HTTPS.</strong> Configure the MakerVault server URL on the device and trust its certificate. For a private/self-signed certificate, install the correct CA explicitly; do not disable certificate checks.</p>
      <p><strong>Alternative: terminal + phone.</strong> On the terminal, choose Connections → MakerVault → Pair device. Its local QR setup page helps configure the network, server URL and certificate trust. You still approve the exact same code here.</p>
      <p><strong>3. Approve pairing.</strong> Read the eight-digit code displayed on the device. It expires after five minutes. Never enter your MakerVault password into the device.</p>
      <form onSubmit={approve}>
        <div className="formGrid">
          <label>Device type
            <select value={kind} onChange={e => setKind(e.target.value)}>
              <option value="rfid_terminal">RFID/NFC terminal</option>
              <option value="filament_scale">Filament weighing station</option>
            </select>
          </label>
          <label>Device name <input required maxLength={120} value={name} onChange={e => setName(e.target.value)} placeholder="Workshop reader" /></label>
          <label>Eight-digit pairing code <input required inputMode="numeric" pattern="[0-9]{8}" maxLength={8} value={code} onChange={e => setCode(e.target.value.replace(/\\D/g, ""))} /></label>
        </div>
        {kind === "rfid_terminal" && <label style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 16 }}><input type="checkbox" checked={write} onChange={e => setWrite(e.target.checked)} /> Allow tag registration and assignment (write access)</label>}
        <p>New devices receive limited read-only scopes by default. Write permissions require explicit approval.</p>
        <button className="primary" disabled={busy || code.length !== 8 || !name.trim()}>Approve pairing</button>
      </form>
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
          <div style={{ display: "grid", gap: 10, margin: "16px 0" }}>
            {(permissionOptions[device.device_type] || []).map(([scope, label]) =>
              <label key={scope} style={{ display: "flex", alignItems: "center", gap: 10 }}>
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
