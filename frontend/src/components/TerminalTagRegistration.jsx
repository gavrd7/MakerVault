import React, { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import TerminalNdefWrite from "./TerminalNdefWrite";
import "./TerminalTagRegistration.css";

function MakerVaultMark({ className = "" }) {
  // Reuse the app's existing branded asset, cropped to its square symbol.
  return <span className={"terminalBrandMark " + className}><img src="/static/core/makervault-logo.jpg" alt="" /></span>;
}

export function TerminalArtwork() {
  return <div className="terminalScanArt" aria-hidden="true">
    <div className="terminalScanDevice">
      <div className="terminalScanScreen"><MakerVaultMark className="terminalScreenMark" /><small>SCAN TAG</small></div>
      <div className="terminalScanControls"><i /><b /><b /></div>
    </div>
    <svg className="terminalScanWaves" viewBox="0 0 100 120" fill="none" aria-hidden="true">
      <path className="terminalScanWave waveOne" d="M 8 43 Q 27 60 8 77" />
      <path className="terminalScanWave waveTwo" d="M 34 30 Q 64 60 34 90" />
      <path className="terminalScanWave waveThree" d="M 60 18 Q 104 60 60 102" />
    </svg>
    <div className="terminalScanTag"><MakerVaultMark className="terminalTagMark" /></div>
  </div>;
}

export default function TerminalTagRegistration({ groups, initialTarget, onClose, onCompleted, onRegistered }) {
  const onRegisteredRef = useRef(onRegistered);
  onRegisteredRef.current = onRegistered;
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;
  const targets = (groups || []).filter(group => ["inventory", "spool"].includes(group.type));
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [targetType, setTargetType] = useState(initialTarget?.type && ["inventory", "spool"].includes(initialTarget.type) ? initialTarget.type : "inventory");
  const [targetId, setTargetId] = useState(initialTarget?.id || "");
  const [registration, setRegistration] = useState(null);
  const [writeTag, setWriteTag] = useState(null);
  const handoffStarted = useRef(false);
  const [pendingRegistration, setPendingRegistration] = useState(null);
  const [checkingPending, setCheckingPending] = useState(false);
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
    if (!deviceId || registration) return undefined;
    let active = true;
    setCheckingPending(true);
    apiFetch("/api/device/tag-registration/pending/?device_id=" + encodeURIComponent(deviceId))
      .then(result => { if (active) setPendingRegistration(result.registration); })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setCheckingPending(false); });
    return () => { active = false; };
  }, [deviceId, registration]);

  function resumePending() {
    if (!pendingRegistration) return;
    setRegistration(pendingRegistration);
    setPendingRegistration(null);
    setError("");
  }

  async function cancelPending() {
    if (!pendingRegistration || busy) return;
    setBusy(true); setError("");
    try {
      await apiFetch("/api/device/tag-registration/" + pendingRegistration.id + "/cancel/", { method: "POST" });
      setPendingRegistration(null);
    } catch (err) {
      if (err.status === 409) setPendingRegistration(null);
      else setError("Unable to cancel previous registration: " + err.message);
    } finally { setBusy(false); }
  }

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
        if (next.state === "cancelled" || next.state === "expired") {
          setRegistration(null);
          setPendingRegistration(null);
          setError(next.state === "cancelled" ? "Registration cancelled on the terminal." : "Registration request expired.");
          return;
        }
        setRegistration(next);
        setSeconds(Math.max(0, Math.ceil((new Date(next.expires_at).getTime() - Date.now()) / 1000)));
        if (next.state === "completed" && !handoffStarted.current) {
          handoffStarted.current = true;
          try {
            const response = await apiFetch("/api/tags/" + next.tag.id + "/");
            if (!active) return;
            const fullTag = response.item;
            onRegisteredRef.current?.(fullTag);
            // This NFC-capable terminal registration leads directly to writing,
            // without a second independently initiated task in the browser.
            if (fullTag?.kind === "nfc") setWriteTag(fullTag);
            else onCompletedRef.current?.(fullTag);
          } catch (err) {
            if (active) {
              handoffStarted.current = false;
              setError("Tag saved, but could not open writing: " + err.message);
            }
          }
        }
      } catch (err) {
        if (active) setError(err.message);
      }
    };
    tick();
    const timer = window.setInterval(tick, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [registration?.id, registration?.state]);

  async function begin(event) {
    event.preventDefault();
    if (!deviceId || !targetId || busy || pendingRegistration) return;
    setBusy(true); setError("");
    try {
      const item = await apiFetch("/api/device/tag-registration/", {
        method: "POST", body: { device_id: deviceId, target_type: targetType, target_id: targetId }
      });
      setRegistration(item);
      setSeconds(Math.max(0, Math.ceil((new Date(item.expires_at).getTime() - Date.now()) / 1000)));
    } catch (err) {
      if (err.status === 409) {
        try {
          const found = await apiFetch("/api/device/tag-registration/pending/?device_id=" + encodeURIComponent(deviceId));
          if (found.registration) {
            setPendingRegistration(found.registration);
            setError("");
          } else setError(err.message);
        } catch (lookupError) { setError(lookupError.message); }
      } else setError(err.message);
    }
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

  if (writeTag) return <TerminalNdefWrite tag={writeTag} onClose={() => {
    onCompletedRef.current?.(null);
    onClose();
  }} />;

  return <Modal title="Add MakerTag with terminal" subtitle="Scan a physical tag with a paired MakerVault handheld." onClose={close} wide className="terminalTagModal">
    <div className="terminalTagLayout">
      <TerminalArtwork />
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
          {checkingPending && <p className="terminalTagHint full">Checking for an unfinished registration…</p>}
          {pendingRegistration && <div className="full" role="status">
            <strong>Unfinished terminal registration</strong>
            <p>A previous request for {pendingRegistration.target?.label || "another record"} is still active on this terminal.</p>
            <div className="modalActions">
              <button type="button" onClick={resumePending} disabled={busy}>Resume previous request</button>
              <button type="button" onClick={cancelPending} disabled={busy}>Cancel previous request</button>
            </div>
          </div>}
          <div className="modalActions full">
            <button type="button" onClick={close}>Cancel</button>
            <button type="submit" className="primary" disabled={busy || checkingPending || !!pendingRegistration || !deviceId || !targetId}>{busy ? "Starting…" : "Use terminal to add"}</button>
          </div>
        </form>}
        {registration && <div className="terminalTagProgress" role="status" aria-live="polite">
          <strong>{registration.state === "completed" ? "MakerTag linked successfully" : registration.state === "pending" ? "Request sent — waiting for terminal…" : registration.state === "expired" ? "Scan request expired" : "Registration cancelled"}</strong>
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
