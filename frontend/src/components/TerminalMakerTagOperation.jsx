import React, { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import "./TerminalNdefWrite.css";

// Physical NFC clearing and MakerTag registration deletion are independent.
export default function TerminalMakerTagOperation({tag, mode, onClose, onCompleted}) {
  const remove = mode === "remove";
  const [alsoClean, setAlsoClean] = useState(!remove);
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [request, setRequest] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [finished, setFinished] = useState(false);
  const active = useRef(true);
  const supported = tag.kind === "nfc" && /^[0-9A-Fa-f]{14}$/.test(tag.code);

  useEffect(() => {
    active.current = true;
    apiFetch("/api/account/connected-devices/").then(data => {
      if (!active.current) return;
      const available = (data.rows || []).filter(device =>
        device.device_type === "rfid_terminal" && !device.revoked_at &&
        device.scopes?.includes("tags:write") &&
        device.capabilities?.includes("ntag215_ndef_write"));
      setDevices(available);
      setDeviceId(available[0]?.id || "");
    }).catch(err => { if (active.current) setError(err.message); });
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    if (!request || !["pending", "cleaned"].includes(request.state)) return undefined;
    let live = true;
    async function refresh() {
      try {
        const value = await apiFetch("/api/device/makertag-operation/" + request.id + "/");
        if (live) setRequest(value.operation);
      } catch (err) {
        if (live) setError(err.message);
      }
    }
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => { live = false; window.clearInterval(timer); };
  }, [request?.id, request?.state]);

  useEffect(() => {
    if (!request || request.state !== "completed" || finished) return;
    setFinished(true);
    onCompleted(remove ? "removed" : "cleaned");
  }, [request?.state, finished, remove, onCompleted]);

  async function begin() {
    if (busy || request) return;
    setBusy(true); setError("");
    try {
      if (remove && !alsoClean) {
        // Existing server-side removal deliberately leaves NFC memory untouched.
        await apiFetch("/api/tags/" + tag.id + "/", {method: "DELETE"});
        onCompleted("removed");
        return;
      }
      if (!supported || !deviceId) throw new Error("Choose a compatible paired terminal.");
      const result = await apiFetch("/api/device/makertag-operation/", {
        method: "POST",
        body: {
          tag_id: tag.id, device_id: deviceId,
          action: remove ? "remove" : "clean", also_clean: true,
        },
      });
      if (active.current) setRequest(result.operation);
    } catch (err) { if (active.current) setError(err.message); }
    finally { if (active.current) setBusy(false); }
  }

  async function cancel() {
    if (!request || !["pending", "cleaned"].includes(request.state)) { onClose(); return; }
    setBusy(true); setError("");
    try {
      const response = await apiFetch("/api/device/makertag-operation/" + request.id + "/cancel/", {method: "POST"});
      if (active.current) setRequest(response.operation);
    } catch (err) { if (active.current) setError("Cancellation failed: " + err.message); }
    finally { if (active.current) setBusy(false); }
  }

  const pending = request && ["pending", "cleaned"].includes(request.state);
  return <Modal title={remove ? "Remove MakerTag" : "Clean NFC data"}
    subtitle={remove ? "Remove this registration from MakerVault." : "Erase the writable NFC data without removing the MakerTag."}
    onClose={pending ? cancel : onClose} wide>
    <div className="terminalNdefStack">
      <div className="terminalNdefIdentity">
        <strong>{tag.maker_tag_id}</strong> · UID <code>{tag.code}</code>
      </div>
      {error && <div className="formError" role="alert">{error}</div>}
      {!request && <>
        {remove ? <>
          <p>Remove the MakerTag association from MakerVault? The linked inventory record will be preserved.</p>
          <label><input type="checkbox" checked={alsoClean && supported} disabled={!supported || busy}
            onChange={e => setAlsoClean(e.target.checked)} /> Also clean NFC data on the physical tag</label>
          {!supported && <small>Physical NFC cleaning requires a registered seven-byte NTAG215. Server-only removal remains available.</small>}
          {!alsoClean && <p>The physical tag will not be modified. A previously written NFC URL may remain on the tag but will no longer resolve.</p>}
        </> : <p>This physically clears the writable NDEF data, but leaves the MakerTag registration and permanent URL intact in MakerVault.</p>}
        {(!remove || alsoClean) && <>
          <label>Paired terminal
            <select value={deviceId} disabled={busy} onChange={e => setDeviceId(e.target.value)}>
              {!devices.length && <option value="">No NFC-capable paired terminal available</option>}
              {devices.map(device => <option key={device.id} value={device.id}>{device.name}{device.online ? " · Connected" : " · Offline"}</option>)}
            </select>
          </label>
          <small>The correct physical tag must be presented and the wipe verified on the terminal before this request can complete.</small>
        </>}
      </>}
      {request && <div className="terminalNdefPreview" aria-live="polite">
        <strong>{request.state === "pending" ? "Present the correct NFC tag to the terminal" :
          request.state === "cleaned" ? "NFC cleared; MakerTag removal pending" :
          request.state === "completed" ? (remove ? "MakerTag removed" : "NFC data cleared; MakerTag retained") :
          "Operation " + request.state}</strong>
        <small>UID: {request.uid}</small>
        {request.state === "pending" && <small>Request expires at {new Date(request.expires_at).toLocaleTimeString()}.</small>}
      </div>}
      <div className="terminalNdefActions">
        {!request && <button className={remove ? "dangerButton" : "primary"} disabled={busy || ((!remove || alsoClean) && (!deviceId || !supported))} onClick={begin}>
          {busy ? "Working…" : remove ? (alsoClean && supported ? "Send clean and remove request" : "Remove registration only") : "Request NFC cleaning"}
        </button>}
        <button disabled={busy} onClick={pending ? cancel : onClose}>
          {pending ? "Cancel request" : "Close"}
        </button>
      </div>
    </div>
  </Modal>;
}
