import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";

export default function PrinterStartGcodeModal({ printer, connection, canEdit, onConfigureMoonraker, onClose, onChanged }) {
  const [source, setSource] = useState("makervault");
  const [action, setAction] = useState("upload");
  const [files, setFiles] = useState([]);
  const [remoteFiles, setRemoteFiles] = useState([]);
  const [assetId, setAssetId] = useState("");
  const [remotePath, setRemotePath] = useState("");
  const [newFile, setNewFile] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [verdict, setVerdict] = useState(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [receipt, setReceipt] = useState(null);
  const [bambuPin, setBambuPin] = useState("");
  const base = "/api/printing/printers/" + printer.id + "/connections/" + connection.id + "/gcode";
  const current = files.find(f => f.id === assetId);

  async function load() {
    try {
      const [local, remote] = await Promise.all([
        apiFetch("/api/files/"),
        apiFetch(base + "/files/"),
      ]);
      setFiles((local.rows || []).filter(f => (f.filename || "").toLowerCase().endsWith(".gcode")));
      setRemoteFiles(remote.rows || []);
      setCapabilities(remote.capabilities || {});
      setNotice(remote.error || remote.notice || "");
    } catch (err) { setError(err.message); }
  }
  useEffect(() => { load(); }, [printer.id, connection.id]);

  useEffect(() => {
    let active = true;
    setVerdict(null);
    setAck(false);
    if (source !== "makervault" || !assetId) return () => { active = false; };
    setChecking(true);
    apiFetch("/api/files/" + assetId + "/gcode/inspect/?printer_id=" + encodeURIComponent(printer.id))
      .then(data => { if (active) setVerdict(data.compatibility); })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [source, assetId, printer.id]);

  async function saveNew() {
    if (!newFile || !newFile.name.toLowerCase().endsWith(".gcode")) return;
    setBusy(true); setError("");
    try {
      const body = new FormData();
      body.append("file", newFile);
      body.append("category", "gcode");
      body.append("name", newFile.name.replace(/\.gcode$/i, ""));
      const saved = await apiFetch("/api/files/", { method: "POST", body });
      await load();
      setAssetId(saved.file.id);
      setSource("makervault");
      setNotice("G-code saved privately in MakerVault Files. Review compatibility before submission.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function configureBambuPin() {
    if (bambuPin.trim() && !/^(?:[0-9a-fA-F]{2}:?){32}$/.test(bambuPin.trim())) {
      setError("Supply exactly 64 hex characters (colons optional) for the independently verified certificate SHA-256.");
      return;
    }
    if (!window.confirm("Change the Bambu FTPS trust fingerprint for " + printer.name + "? Only a fingerprint independently verified against your own printer should be used.")) return;
    setBusy(true); setError("");
    try {
      await apiFetch(base + "/bambu-certificate/", {
        method: "PATCH", body: { sha256: bambuPin.trim() },
      });
      setBambuPin("");
      await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function submit() {
    const name = source === "printer" ? remotePath : current?.filename;
    const operation = source === "printer" ? "print" : action;
    if (!name) { setError("Select a G-code file."); return; }
    if (verdict?.status === "mismatch") { setError("Printer model mismatch; submission blocked."); return; }
    if ((source === "printer" || verdict?.status !== "metadata_match") && !ack) {
      setError("Confirm your review of unverified printer compatibility."); return;
    }
    if (!window.confirm("Printer: " + printer.name + "\nFile: " + name + "\nAction: " +
      (operation === "print" ? "START PRINT" : "UPLOAD ONLY, no printing") + "\n\nContinue?")) return;
    setBusy(true); setError(""); setReceipt(null);
    try {
      const result = await apiFetch(base + "/submit/", {
        method: "POST",
        body: {
          request_id: window.crypto.randomUUID(),
          source: source === "printer" ? "printer" : "makervault",
          action: operation, printer_path: remotePath,
          file_asset_id: assetId, confirmed: true, acknowledge_unknown: ack,
        },
      });
      setReceipt(result.submission);
      if (result.submission?.status === "unknown") {
        setError("Printer outcome is uncertain. Inspect the printer before trying anything else.");
      }
      await onChanged?.();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <Modal title={"G-code printing · " + printer.name}
    subtitle="Select one source and explicitly confirm upload or start. Nothing runs automatically."
    onClose={onClose} wide>
    {error && <div className="formError" role="alert">{error}</div>}
    {notice && <div className="settingsCallout">{notice}</div>}
    {connection.adapter === "creality_local" && <div className="settingsCallout">
      <strong>Creality native monitoring does not imply file transfer</strong>
      <p>Some Creality K1/K2 firmware exposes a separate Moonraker/Klipper service on the same printer. You can configure that as an additional source, with its own authentication and explicit printer controls. MakerVault will not assume the endpoint is present or send files through the monitoring WebSocket.</p>
      {onConfigureMoonraker && <button type="button" onClick={onConfigureMoonraker}>Configure separate Moonraker source</button>}
    </div>}
    {connection.adapter === "prusa" && <div className="settingsCallout"><strong>Experimental PrusaLink transfer</strong><p>Native PrusaLink v1 file listing, upload and start support is unverified on physical hardware. Unsupported firmware returns an error; never assume print acceptance until confirmed on the printer.</p></div>}
    {connection.adapter === "bambu_local" && <div className="printingManageForm">
      <strong>Bambu LAN storage — read-only experimental browser</strong>
      <p>Bambu may expose its files over implicit FTPS on port 990. The browser requires an independently verified certificate SHA-256 fingerprint; no file is uploaded and no print command is available.</p>
      <label>FTPS certificate SHA-256 fingerprint
        <input value={bambuPin} onChange={e => setBambuPin(e.target.value)} placeholder="64 hexadecimal characters, colons optional" autoComplete="off" />
      </label>
      <div className="formActions">
        <button type="button" disabled={busy || !canEdit} onClick={configureBambuPin}>Save / clear certificate pin</button>
        <button type="button" disabled={busy} onClick={load}>Browse printer storage</button>
      </div>
      {!!remoteFiles.length && <div className="printingRevisionList">
        {remoteFiles.map(file => <div key={file.path}><strong>{file.path}</strong><small>{file.size_bytes == null ? "Size unknown" : (file.size_bytes / 1048576).toFixed(2) + " MiB"} · Read-only</small></div>)}
      </div>}
      <small>FTPS availability differs by Bambu model and firmware. A PIN mismatch or unsupported TLS handshake fails closed. Starting Bambu print jobs is not implemented.</small>
    </div>}
    {capabilities && !capabilities.supported ? <div className="settingsCallout">
      <strong>Experimental adapter — printer file submission unavailable</strong>
      <p>This source supports monitoring, but its storage and start-print protocol is not implemented or verified here. Bambu storage listing is experimental and read-only; Bambu print-start, proprietary Creality and other manufacturer transfer paths still require dedicated implementation and hardware validation.</p>
    </div> : <>
      <label>Source<select value={source} onChange={e => { setSource(e.target.value); setError(""); setReceipt(null); }}>
        <option value="new">Upload a new G-code file</option>
        <option value="makervault">Existing MakerVault G-code</option>
        <option value="printer">Already stored on the printer</option>
      </select></label>
      {source === "new" && <div className="printingManageForm">
        <label>G-code<input type="file" accept=".gcode" onChange={e => setNewFile(e.target.files?.[0] || null)} /></label>
        <small>This ad-hoc file is saved in MakerVault Files before transfer. It can be linked to a project or model later.</small>
        <button type="button" className="primary" disabled={!newFile || busy || !canEdit} onClick={saveNew}>Save and review</button>
      </div>}
      {source === "makervault" && <label>MakerVault file<select value={assetId} onChange={e => setAssetId(e.target.value)}>
        <option value="">Choose a G-code file…</option>
        {files.map(f => <option value={f.id} key={f.id}>{f.name} · {f.project || "Standalone"}</option>)}
      </select></label>}
      {source === "printer" && <>
        <label>Printer storage<select value={remotePath} onChange={e => setRemotePath(e.target.value)}>
          <option value="">Choose a printer file…</option>
          {remoteFiles.map(f => <option key={f.path} value={f.path}>{f.path}</option>)}
        </select></label>
        <button type="button" disabled={busy} onClick={load}>Refresh printer storage</button>
      </>}
      {source === "makervault" && (checking ? <p>Analysing printer metadata…</p> : verdict && <div className="settingsCallout" role="status">
        <strong>{verdict.status === "mismatch" ? "Printer mismatch — blocked" : verdict.status === "metadata_match" ? "Printer name matches; full safety not verified" : "Printer identity unknown"}</strong>
        <p>{verdict.reason}</p>
      </div>)}
      {source !== "new" && <>
        {source === "makervault" && <label>Operation<select value={action} onChange={e => setAction(e.target.value)}>
          <option value="upload">Upload only — do not print</option>
          <option value="print">Upload and start print</option>
        </select></label>}
        {(source === "printer" || verdict?.status !== "metadata_match") && <label className="checkRow">
          <input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />
          I have reviewed this file for {printer.name} and understand the printer profile is unverified.
        </label>}
        <div className="formActions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="button" className="primary" onClick={submit}
            disabled={busy || checking || !canEdit || !capabilities?.supported ||
              (source === "printer" ? !remotePath || !capabilities.can_start : !assetId || !capabilities.can_upload ||
                (action === "print" && !capabilities.can_start)) || verdict?.status === "mismatch"}>
            {busy ? "Submitting…" : source === "printer" || action === "print" ? "Review & start print" : "Review & upload only"}
          </button>
        </div>
      </>}
    </>}
    {receipt && <div className="settingsCallout" role="status">
      <strong>Submission: {receipt.status}</strong><p>{receipt.message}</p>
      <small>Request ID {receipt.request_id} — uncertain requests are never resent automatically.</small>
    </div>}
  </Modal>;
}
