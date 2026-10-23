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

  async function reload() {
    const result = await apiFetch("/api/account/connected-devices/");
    setRows(result.rows || []);
  }
  useEffect(() => { reload().catch(e => setError(e.message)); }, []);

  async function approve(event) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const scopes = kind === "filament_scale" ? ["tags:read", "inventory:read", "devices:status"] :
        write ? ["tags:read", "tags:write", "devices:status"] : ["tags:read", "devices:status"];
      await apiFetch("/api/account/connected-devices/pair/approve/", {
        method: "POST",
        body: JSON.stringify({ name, confirmation_code: code, scopes }),
      });
      setAdding(false); setCode(""); setName("");
      setNotice("Approved. The device can now securely collect its one-time credential.");
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
    {adding && <div className="settingsPanel">
      <h4>Connect a hardware device</h4>
      <p><strong>1. Prepare the connection.</strong> On a phone, join the setup Wi-Fi shown on your device and enter your home Wi-Fi credentials in its local portal. On a desktop, connect using the device's setup access point or a compatible USB setup utility. MakerVault cannot contact hardware that has not joined a network.</p>
      <p><strong>2. Verify HTTPS.</strong> Configure the MakerVault server URL on the device and trust its certificate. For a private/self-signed certificate, install the correct CA explicitly; do not disable certificate checks.</p>
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
        {kind === "rfid_terminal" && <label><input type="checkbox" checked={write} onChange={e => setWrite(e.target.checked)} /> Allow tag registration and assignment (write access)</label>}
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
        </div>
        {!device.revoked_at && <button type="button" disabled={busy} onClick={() => revoke(device)}>Unpair</button>}
      </article>)}
    </div>}
    <p>Wi-Fi connection, MakerVault API access and device health are separate statuses. Offline devices remain registered; a temporary network outage does not reopen setup mode.</p>
  </section>;
}
