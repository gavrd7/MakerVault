import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import "./TerminalTagRegistration.css";

function TerminalSymbol() {
  return <div className="terminalScanArt" aria-hidden="true">
    <div className="terminalScanDevice">
      <div className="terminalScanScreen"><span>⌁</span><small>SCAN TAG</small></div>
      <div className="terminalScanControls"><i /><b /><b /></div>
    </div>
    <div className="terminalScanWaves"><span /><span /><span /></div>
    <div className="terminalScanTag">⌁</div>
  </div>;
}

export default function TerminalTagRegistration({ groups, initialTarget, onClose, onCompleted }) {
  const targets = (groups || []).filter(group => ["inventory", "spool"].includes(group.type));
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [targetType, setTargetType] = useState(initialTarget?.type && ["inventory", "spool"].includes(initialTarget.type) ? initialTarget.type : "inventory");
  const [targetId, setTargetId] = useState(initialTarget?.id || "");
  const [registration, setRegistration] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(300);
  const group = targets.find(item => item.type === targetType);
  const rows = group?.rows || [];
  const selectedDevice = devices.find(device => device.id === deviceId);

  useEffect(() => {
    let active = true;
    apiFetch("/api/account/connected-devices/")
      .then(result => {
        if (!active) return;
        const eligible = (result.rows || []).filter(device =>
          device.device_type === "rfid_terminal" && !device.revoked_at && device.scopes?.includes("tags:write")
        );
        setDevices(eligible);
        setDeviceId(eligible[0]?.id || "");
      })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (targetId && rows.some(row => String(row.id) === String(targetId))) return;
    setTargetId(rows[0]?.id || "");
  }, [targetType, rows, targetId]);

  useEffect(() => {
    if (!registration || registration.state !== "pending") return undefined;
    let active = true;
    const tick = async () => {
      try {
        const next = await apiFetch("/api/device/tag-registration/" + registration.id + "/");
        if (!active) return;
        setRegistration(next);
        setSeconds(Math.max(0, Math.ceil((new Date(next.expires_at).getTime() - Date.now()) / 1000)));
        if (next.state === "completed") onCompleted?.();
      } catch (err) {
        if (active) setError(err.message);
      }
    };
    tick();
    const timer = window.setInterval(tick, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [registration?.id, registration?.state, onCompleted]);

  async function begin(event) {
    event.preventDefault();
    if (!deviceId || !targetId || busy) return;
    setBusy(true); setError("");
    try {
      const item = await apiFetch("/api/device/tag-registration/", {
        method: "POST", body: { device_id: deviceId, target_type: targetType, target_id: targetId }
      });
      setRegistration(item);
      setSeconds(Math.max(0, Math.ceil((new Date(item.expires_at).getTime() - Date.now()) / 1000)));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function close() {
    if (busy) return;
    if (registration?.state === "pending") {
      setBusy(true);
      try {
        await apiFetch("/api/device/tag-registration/" + registration.id + "/cancel/", { method: "POST" });
      } catch (err) {
        if (err.status !== 409) { setError("Unable to cancel registration: " + err.message); setBusy(false); return; }
      }
      setBusy(false);
    }
    onClose();
  }

  return <Modal title="Add Maker Tag with terminal" subtitle="Scan a physical tag with a paired MakerVault handheld." onClose={close} wide className="terminalTagModal">
    <div className="terminalTagLayout">
      <TerminalSymbol />
      <div className="terminalTagContent">
        {!registration && <form onSubmit={begin} className="formGrid">
          <label className="full">Connected terminal
            <select required value={deviceId} onChange={event => setDeviceId(event.target.value)}>
              {!devices.length && <option value="">No paired terminals with tag registration permission</option>}
              {devices.map(device => <option key={device.id} value={device.id}>{device.name}{device.online ? " · Connected" : " · Offline"}</option>)}
            </select>
          </label>
          <label>Record type
            <select value={targetType} onChange={event => { setTargetType(event.target.value); setTargetId(""); }}>
              {targets.map(group => <option key={group.type} value={group.type}>{group.label}</option>)}
            </select>
          </label>
          <label>Record
            <select required value={targetId} onChange={event => setTargetId(event.target.value)}>
              {!rows.length && <option value="">No records available</option>}
              {rows.map(row => <option key={row.id} value={row.id}>{row.label} {row.subtitle ? "· " + row.subtitle : ""}</option>)}
            </select>
          </label>
          <p className="terminalTagHint full">Select a record and terminal. The handheld will ask for confirmation before MakerVault saves the scanned UID.</p>
          <div className="modalActions full">
            <button type="button" onClick={close}>Cancel</button>
            <button type="submit" className="primary" disabled={busy || !deviceId || !targetId}>{busy ? "Starting…" : "Use terminal to add"}</button>
          </div>
        </form>}
        {registration && <div className="terminalTagProgress" role="status" aria-live="polite">
          <strong>{registration.state === "completed" ? "Maker Tag linked successfully" : registration.state === "pending" ? "Waiting for terminal scan…" : registration.state === "expired" ? "Scan request expired" : "Registration cancelled"}</strong>
          <p>{registration.target?.label || "Selected record"}</p>
          <p>Terminal: {selectedDevice?.name || "Paired handheld"}</p>
          {registration.state === "pending" && <p className="terminalTagCountdown">Time remaining: {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</p>}
          {registration.state === "completed" && <p>UID: <code>{registration.tag?.id ? "Registration confirmed" : "Saved"}</code></p>}
          <div className="modalActions">
            <button type="button" onClick={close} disabled={busy}>{registration.state === "pending" ? "Cancel registration" : "Close"}</button>
          </div>
        </div>}
        {error && <div className="formError" role="alert">{error}</div>}
      </div>
    </div>
  </Modal>;
}
