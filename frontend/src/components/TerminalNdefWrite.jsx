import React, { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import "./TerminalNdefWrite.css";

// Terminal-mediated NDEF writes are deliberately capability gated: firmware
// v0.6.1 does not advertise ntag215_ndef_write and must never receive requests.
export default function TerminalNdefWrite({ tag, onClose }) {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [override, setOverride] = useState("");
  const [showOverride, setShowOverride] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(true);
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

  // Preview automatically, including after a user changes the optional address.
  // Discard stale responses so an earlier address can never authorize Send.
  useEffect(() => {
    if (request) return undefined;
    let current = true;
    setPreview(null);
    setPreviewLoading(true);
    setError("");
    const refresh = async () => {
      try {
        const next = await apiFetch("/api/tags/" + tag.id + "/ndef-preview/", {
          method: "POST",
          body: { origin: window.location.origin, override: override.trim() },
        });
        if (current) setPreview(next);
      } catch (err) {
        if (current) setError(err.message);
      } finally {
        if (current) setPreviewLoading(false);
      }
    };
    refresh();
    return () => { current = false; };
  }, [tag.id, override, !!request]);

  async function begin() {
    if (!preview || !deviceId || previewLoading || busy || request) return;
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
    <div className="terminalNdefStack">
      <div className="terminalNdefIdentity">Tag <strong>{tag.maker_tag_id}</strong> <span>·</span> UID <code>{tag.code}</code></div>
      {error && <div className="formError" role="alert">{error}</div>}
      {!request && <>
        <label>Paired terminal
          <select value={deviceId} onChange={event => { setDeviceId(event.target.value); setPreview(null); }} disabled={busy}>
            {!devices.length && <option value="">No terminal currently advertises NTAG215 writing</option>}
            {devices.map(device => <option key={device.id} value={device.id}>{device.name}{device.online ? " · Connected" : " · Offline"}</option>)}
          </select>
        </label>
        <button type="button" className="terminalNdefOverrideToggle" onClick={() => setShowOverride(value => !value)} disabled={busy}>
          {showOverride ? "Hide address override" : "Override address"}
        </button>
        {showOverride && <label>Alternative MakerVault address
          <input type="url" value={override} placeholder={window.location.origin}
            onChange={event => { setOverride(event.target.value); setPreview(null); }} disabled={busy}/>
        </label>}
        <div className="terminalNdefPreview" aria-live="polite">
          <strong>URL preview</strong>
          {preview ? <>
            <code>{preview.url}</code>
            {preview.local_address_warning && <small role="status">This address may only be reachable on the same LAN or VPN.</small>}
          </> : <p>{previewLoading ? "Checking URL…" : "No valid URL available."}</p>}
        </div>
        <p className="terminalNdefHint">The ESP32-S3 must verify the tag UID, request physical confirmation and read back the written URL.</p>
      </>}
      {request && <div className="terminalNdefPreview" aria-live="polite">
        <strong>{request.state === "pending" ? "Waiting for terminal confirmation" :
          request.state === "completed" ? "Terminal reported verified write" : "Write request: " + request.state}</strong>
        <code>{request.url}</code>
        {request.state === "pending" && <small>Expires at {new Date(request.expires_at).toLocaleTimeString()}.</small>}
        {request.state === "completed" && <small>Check the link independently using your phone.</small>}
      </div>}
      <div className="terminalNdefActions">
        <button type="button" className="primary" disabled={busy || previewLoading || !deviceId || !preview || !!request} onClick={begin}>Send to terminal</button>
        <button type="button" disabled={busy} onClick={request?.state === "pending" ? cancel : onClose}>
          {request?.state === "pending" ? "Cancel request" : "Close"}
        </button>
      </div>
    </div>
  </Modal>;
}
