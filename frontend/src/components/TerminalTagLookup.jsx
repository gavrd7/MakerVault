import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import { TerminalArtwork } from "./TerminalTagRegistration";

export default function TerminalTagLookup({ onClose, onFound }) {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [session, setSession] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    apiFetch("/api/account/connected-devices/")
      .then(data => {
        if (!active) return;
        const eligible = (data.rows || []).filter(device =>
          device.device_type === "rfid_terminal" && !device.revoked_at && device.scopes?.includes("tags:read")
        );
        setDevices(eligible);
        setDeviceId(eligible[0]?.id || "");
      })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (session?.state !== "pending") return undefined;
    let active = true;
    const poll = async () => {
      try {
        const updated = await apiFetch("/api/device/tag-lookup/" + session.id + "/");
        if (active) setSession(updated);
      } catch (err) {
        if (active) setError(err.message);
      }
    };
    poll();
    const timer = window.setInterval(poll, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [session?.id, session?.state]);

  async function begin() {
    if (!deviceId || busy) return;
    setBusy(true); setError("");
    try {
      setSession(await apiFetch("/api/device/tag-lookup/", { method: "POST", body: { device_id: deviceId } }));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function close() {
    if (busy) return;
    if (session?.state === "pending") {
      setBusy(true);
      try {
        await apiFetch("/api/device/tag-lookup/" + session.id + "/cancel/", { method: "POST" });
      } catch (err) {
        if (err.status !== 409) { setError(err.message); setBusy(false); return; }
      }
      setBusy(false);
    }
    onClose();
  }

  return <Modal title="Scan with MakerVault terminal" subtitle="Look up a physical tag without registering or changing it." onClose={close} wide className="terminalTagModal">
    <div className="terminalTagLayout">
      <TerminalArtwork />
      <div className="terminalTagContent">
        {!session ? <>
          <label>Connected terminal
            <select value={deviceId} onChange={e => setDeviceId(e.target.value)}>
              {!devices.length && <option value="">No paired terminals with tags:read permission</option>}
              {devices.map(device => <option key={device.id} value={device.id}>{device.name}</option>)}
            </select>
          </label>
          <div className="modalActions">
            <button type="button" onClick={close}>Cancel</button>
            <button type="button" className="primary" onClick={begin} disabled={!deviceId || busy}>{busy ? "Starting…" : "Start scanning"}</button>
          </div>
        </> : <div className="terminalTagProgress" role="status" aria-live="polite">
          {session.state === "pending" && <><strong>Request sent to MakerVault terminal</strong><p>Waiting for the handheld to receive the request. When its screen says “Present a tag”, hold the tag against the reader. The request expires after five minutes.</p></>}
          {session.state === "completed" && <>
            <strong>{session.found ? "MakerTag found" : "Unregistered tag"}</strong>
            <p className="terminalTagUid">UID: <span>{session.uid}</span></p>
            {session.tag && <><p>{session.tag.label || session.tag.target?.label}</p><p>{session.tag.target?.subtitle}</p></>}
            {session.tag && <button type="button" className="primary" onClick={() => { onFound(session.tag.id); onClose(); }}>Open MakerTag</button>}
          </>}
          {session.state === "expired" && <strong>Scan request expired.</strong>}
          {session.state === "cancelled" && <strong>Scan cancelled.</strong>}
          <div className="modalActions"><button type="button" onClick={close} disabled={busy}>{session.state === "pending" ? "Cancel scan" : "Close"}</button></div>
        </div>}
        {error && <div className="formError" role="alert">{error}</div>}
      </div>
    </div>
  </Modal>;
}
