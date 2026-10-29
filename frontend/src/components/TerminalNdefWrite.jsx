import React, { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";

// Terminal-mediated NDEF writes are deliberately capability gated: firmware
// v0.6.1 does not advertise ntag215_ndef_write and must never receive requests.
export default function TerminalNdefWrite({ tag, onClose }) {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [override, setOverride] = useState("");
  const [preview, setPreview] = useState(null);
  const [request, setRequest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);

  useEffect(() => {
    active.current = true;
    apiFetch("/api/account/connected-devices/").then(result => {
      if (!active.current) return;
      const eligible = (result.rows || []).filter(device =>
        device.device_type === "rfid_terminal" && !device.revoked_at &&
        device.scopes?.includes("tags:write") &&
        device.capabilities?.includes("ntag215_ndef_write")
      );
      setDevices(eligible);
      setDeviceId(eligible[0]?.id || "");
    }).catch(err => { if (active.current) setError(err.message); });
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    if (request?.state !== "pending") return undefined;
    let live = true;
    async function refresh() {
      try {
        const next = await apiFetch("/api/device/ndef-write/" + request.id + "/");
        if (live) setRequest(next);
      } catch (err) {
        if (live) setError(err.message);
      }
    }
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => { live = false; window.clearInterval(timer); };
  }, [request?.id, request?.state]);

  async function check() {
    setBusy(true); setError(""); setPreview(null);
    try {
      const next = await apiFetch("/api/tags/" + tag.id + "/ndef-preview/", {
        method: "POST",
        body: { origin: window.location.origin, override: override.trim() },
      });
      if (active.current) setPreview(next);
    } catch (err) { if (active.current) setError(err.message); }
    finally { if (active.current) setBusy(false); }
  }

  async function begin() {
    if (!preview || !deviceId) return;
    setBusy(true); setError("");
    try {
      const result = await apiFetch("/api/device/ndef-write/", {
        method: "POST", body: {
          tag_id: tag.id, device_id: deviceId,
          origin: window.location.origin, override: override.trim(),
        },
      });
      // Preview and execution must agree exactly, preventing changed input.
      if (result.url !== preview.url) {
        await apiFetch("/api/device/ndef-write/" + result.id + "/cancel/", {method: "POST"});
        throw new Error("Address changed; preview it again before writing.");
      }
      if (active.current) setRequest(result);
    } catch (err) { if (active.current) setError(err.message); }
    finally { if (active.current) setBusy(false); }
  }

  async function cancel() {
    if (!request || request.state !== "pending") { onClose(); return; }
    setBusy(true); setError("");
    try {
      await apiFetch("/api/device/ndef-write/" + request.id + "/cancel/", {method: "POST"});
      if (active.current) setRequest({...request, state: "cancelled"});
    } catch (err) {
      if (active.current) setError("Unable to cancel: " + err.message);
      return;
    } finally { if (active.current) setBusy(false); }
  }

  return <Modal title="Write MakerVault NFC link" subtitle="Write a standard NDEF URL using a paired RFID terminal." onClose={request?.state === "pending" ? cancel : onClose} wide>
    <div className="formGrid">
      <p>Tag <strong>{tag.maker_tag_id}</strong> · UID <code>{tag.code}</code></p>
      {error && <div className="formError" role="alert">{error}</div>}
      {!request && <>
        <label>Paired terminal
          <select value={deviceId} onChange={event => { setDeviceId(event.target.value); setPreview(null); }} disabled={busy}>
            {!devices.length && <option value="">No terminal currently advertises NTAG215 writing</option>}
            {devices.map(device => <option key={device.id} value={device.id}>{device.name}{device.online ? " · Connected" : " · Offline"}</option>)}
          </select>
        </label>
        <label>Optional URL address override
          <input type="url" value={override} placeholder={window.location.origin}
            onChange={event => { setOverride(event.target.value); setPreview(null); }} disabled={busy}/>
        </label>
        <button type="button" disabled={busy} onClick={check}>Preview URL</button>
        {preview && <>
          <p><strong>Exact URL:</strong> <code>{preview.url}</code></p>
          {preview.local_address_warning && <p role="status">This address may only be reachable on the same LAN or VPN.</p>}
          <p>The terminal must confirm the physical UID, ask for confirmation and verify its memory after writing. Scanning a tag alone never writes to it.</p>
          <button type="button" className="primary" disabled={busy || !deviceId} onClick={begin}>Send to terminal</button>
        </>}
      </>}
      {request && <>
        <p><strong>Status:</strong> {request.state === "pending" ? "Waiting for terminal confirmation" :
           request.state === "completed" ? "Terminal reported verified write" : request.state}</p>
        <p><code>{request.url}</code></p>
        {request.state === "pending" && <p>Expires at {new Date(request.expires_at).toLocaleTimeString()}.</p>}
        {request.state === "completed" && <p>Tap the tag using your phone to confirm it opens the intended MakerVault instance.</p>}
      </>}
      <div className="formActions">
        <button type="button" disabled={busy} onClick={request?.state === "pending" ? cancel : onClose}>
          {request?.state === "pending" ? "Cancel request" : "Close"}
        </button>
      </div>
    </div>
  </Modal>;
}
