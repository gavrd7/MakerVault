import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";

export default function PrinterStartGcodeModal({ printer, connection, canEdit, onConfigureMoonraker, onClose, onChanged, initialAsset = null }) {
  const [source, setSource] = useState("makervault");
  const [action, setAction] = useState("upload");
  const [files, setFiles] = useState([]);
  const [remoteFiles, setRemoteFiles] = useState([]);
  const [assetId, setAssetId] = useState(initialAsset?.id ? String(initialAsset.id) : "");
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
  const [transferStage, setTransferStage] = useState("");
  const [bambuPin, setBambuPin] = useState("");
  const [filamentAnalysis, setFilamentAnalysis] = useState(null);
  const [cfsAssignments, setCfsAssignments] = useState({});
  const [useSlicedCfs, setUseSlicedCfs] = useState(false);
  const [cfsAcknowledged, setCfsAcknowledged] = useState(false);
  const base = "/api/printing/printers/" + printer.id + "/connections/" + connection.id + "/gcode";
  const cfs = capabilities?.cfs || null;
  const cfsSlicedAvailable = Boolean(capabilities?.can_start_sliced_mapping);
  const requirements = source === "makervault" ? (filamentAnalysis?.requirements || []) : [];
  const sameMaterial = (left, right) => Boolean(left && right) && left.trim().toUpperCase() === right.trim().toUpperCase();
  const matches = (requirement, slot) => sameMaterial(requirement.material, slot.material);
  const suggestedSlot = (requirement) => (cfs?.slots || []).find(slot =>
    matches(requirement, slot) && requirement.color_hex &&
    slot.color_hex?.toLowerCase() === requirement.color_hex.toLowerCase()
  )?.label || "";
  const current = files.find(f => String(f.id) === String(assetId)) || (initialAsset && String(initialAsset.id) === String(assetId) ? initialAsset : null);

  async function load() {
    // A broken printer-side file API must not hide perfectly valid MakerVault files.
    const [local, remote] = await Promise.allSettled([
      apiFetch("/api/files/"),
      apiFetch(base + "/files/"),
    ]);
    if (local.status === "fulfilled") {
      setFiles((local.value.rows || []).filter(f => (f.filename || "").toLowerCase().endsWith(".gcode")));
    } else {
      setError("MakerVault file list unavailable: " + local.reason.message);
    }
    if (remote.status === "fulfilled") {
      setRemoteFiles(remote.value.rows || []);
      setCapabilities(remote.value.capabilities || {});
      setNotice(remote.value.error || remote.value.notice || "");
    } else {
      setRemoteFiles([]);
      setNotice("Printer storage listing unavailable. MakerVault files remain accessible.");
      setError(remote.reason.message);
    }
  }
  useEffect(() => { load(); }, [printer.id, connection.id]);

  useEffect(() => {
    let active = true;
    setVerdict(null);
    setFilamentAnalysis(null);
    setCfsAssignments({});
    setAck(false);
    if (source !== "makervault" || !assetId) return () => { active = false; };
    setChecking(true);
    apiFetch("/api/files/" + assetId + "/gcode/inspect/?printer_id=" + encodeURIComponent(printer.id))
      .then(data => { if (active) { setVerdict(data.compatibility); setFilamentAnalysis(data.analysis?.filaments || null); } })
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

  async function toggleNativeTransfer() {
    if (!["prusa", "creality_local", "flashforge"].includes(connection.adapter)) return;
    const enabled = !capabilities?.enabled;
    if (enabled && !window.confirm("Enable EXPERIMENTAL native printer file operations for " + printer.name + "? This is unverified on hardware. Files can be sent to this printer only after an additional confirmation.")) return;
    setBusy(true); setError("");
    try {
      await apiFetch(base + "/native-opt-in/", { method: "PATCH", body: { enabled } });
      await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function toggleCrealityStart() {
    if (connection.adapter !== "creality_local" || !capabilities?.enabled) return;
    const enable = !capabilities?.can_start && capabilities?.requires_start_opt_in;
    if (enable && !window.confirm(
      "Enable EXPERIMENTAL Creality native single-spool print-start? This sends an actual start command to the selected printer. It is disabled whenever CFS is connected, and the proprietary protocol does not acknowledge delivery."
    )) return;
    setBusy(true); setError("");
    try {
      await apiFetch(base + "/native-opt-in/", {
        method: "PATCH",
        body: { enabled: true, single_spool_start: enable },
      });
      await load();
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
    const slicedCfs = operation === "print" && cfsSlicedAvailable && useSlicedCfs;
    if (!name) { setError("Select a G-code file."); return; }
    if (operation === "print" && !capabilities?.can_start && !slicedCfs) { setError("Choose a supported print mode first."); return; }
    if (slicedCfs && !cfsAcknowledged) { setError("Confirm the loaded CFS filaments and original slicer mapping before starting."); return; }
    if (verdict?.status === "mismatch") { setError("Printer model mismatch; submission blocked."); return; }
    if ((source === "printer" || verdict?.status !== "metadata_match") && !ack) {
      setError("Confirm your review of unverified printer compatibility."); return;
    }
    if (!window.confirm("Printer: " + printer.name + "\nFile: " + name + "\nAction: " +
      (operation === "print" ? "START PRINT" : "UPLOAD ONLY, no printing") + (slicedCfs ? "\nCFS: USE ORIGINAL SLICER MAPPING; NO SLOT OVERRIDE\nConfirm the filament on the K2 screen before proceeding." : "") + "\n\nContinue?")) return;
    setBusy(true); setError(""); setReceipt(null);
    setTransferStage("Submitting request and checking printer readiness…");
    const requestId = window.crypto.randomUUID();
    const statusTimer = window.setInterval(async () => {
      try {
        const status = await apiFetch(base + "/submissions/" + requestId + "/");
        if (status?.submission?.message) setTransferStage(status.submission.message);
      } catch (_error) {
        // The request may not have been journaled yet; the POST remains authoritative.
      }
    }, 1200);
    try {
      const result = await apiFetch(base + "/submit/", {
        method: "POST",
        body: {
          request_id: requestId,
          source: source === "printer" ? "printer" : "makervault",
          action: operation, printer_path: remotePath,
          file_asset_id: assetId, confirmed: true, acknowledge_unknown: ack,
          cfs_mode: slicedCfs ? "use_sliced" : null, cfs_acknowledged: slicedCfs && cfsAcknowledged,
        },
      });
      setReceipt(result.submission);
      setTransferStage(result.submission?.message || "Printer responded.");
      if (result.submission?.status === "unknown") {
        setError("Printer outcome is uncertain. Inspect the printer before trying anything else.");
      }
      await onChanged?.();
    } catch (err) { setError(err.message); setTransferStage("Submission failed or could not be verified."); }
    finally { window.clearInterval(statusTimer); setBusy(false); }
  }

  return <Modal title={"G-code printing · " + printer.name}
    subtitle="Select one source and explicitly confirm upload or start. Nothing runs automatically."
    onClose={onClose} wide>
    <div className="gcodePrintModalContent">
    {error && <div className="formError" role="alert">{error}</div>}
    {notice && <div className="settingsCallout">{notice}</div>}
    {["prusa", "creality_local", "flashforge"].includes(connection.adapter) && <div className="settingsCallout">
      <strong>Experimental native G-code transfer</strong>
      <p>{connection.adapter === "creality_local" ? "Native upload is supported experimentally. Single-spool start is a separate opt-in; CFS printing remains disabled until mapping is validated." : connection.adapter === "prusa" ? "Native PrusaLink v1 transfer and print-start are experimental and require the correct firmware capabilities." : "Adventurer 5M / 5M Pro: upload-only or explicitly confirmed start. Multi-material FlashForge models are not enabled."}</p>
      <label className="checkRow">
        <input type="checkbox" checked={Boolean(capabilities?.enabled)} disabled={!canEdit || busy} onChange={toggleNativeTransfer} />
        Enable experimental G-code file transfer for this printer
      </label>
    </div>}
    {connection.adapter === "creality_local" && <div className="settingsCallout">
      <strong>Experimental stock Creality print-start</strong>
      <p>Native single-spool print-start is available for hardware validation on K1/K2, separately enabled from file uploads. It will not run while CFS is detected, and the printer protocol does not acknowledge command acceptance. Confirm the printer and loaded filament physically.</p>
      <label className="checkRow">
        <input type="checkbox" checked={Boolean(capabilities?.enabled && !capabilities?.requires_start_opt_in)} disabled={!canEdit || busy || !capabilities?.enabled} onChange={toggleCrealityStart} />
        Allow experimental single-spool native start (never CFS)
      </label>
      {capabilities?.enabled && !capabilities?.can_start && !capabilities?.requires_start_opt_in && <small>Start remains unavailable: printer is busy/offline, CFS is connected, or telemetry is stale.</small>}
    </div>}
    {connection.adapter === "creality_local" && <details className="settingsCallout">
      <summary><strong>Alternative transport: Moonraker / Klipper (optional)</strong></summary>
      <p>MakerVault uses stock Creality LAN protocols for this connection. Moonraker is optional when the printer separately exposes its API; it is not required for native file browsing, uploads or single-spool prints.</p>
      {onConfigureMoonraker && <button type="button" onClick={onConfigureMoonraker}>Configure additional Moonraker source</button>}
    </details>}
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
    {cfs?.applicable && <div className="settingsCallout">
      <strong>Creality CFS · Live loaded filaments</strong>
      <p>{cfs.connected === true
        ? "These materials were reported by the K2's native LAN telemetry. Choose a candidate slot for review; MakerVault does not yet apply a verified filament mapping to the print-start command."
        : cfs.connected === false && cfs.verified
          ? "The latest native printer reading reports no CFS connected."
          : "CFS connection state is unavailable or stale. Remote print-start remains disabled until it can be verified."}</p>
      {cfs.connected === true && <>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <strong>Current CFS inventory</strong>
          <button type="button" onClick={load} disabled={busy}>Refresh CFS snapshot</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(215px, 1fr))", gap: 10, margin: "12px 0" }}>
          {(cfs.slots || []).map(slot => <div key={slot.label} style={{ display: "flex", alignItems: "center", gap: 10, padding: 12, border: "1px solid var(--border-color, #344255)", borderRadius: 10 }}>
            <span aria-label={slot.color_hex || "Unknown colour"} style={{ width: 24, height: 24, flexShrink: 0, borderRadius: 6, background: /^#[0-9a-fA-F]{6}$/.test(slot.color_hex || "") ? slot.color_hex : "transparent", border: "1px solid #718096" }} />
            <span><strong>{slot.label}</strong> · {slot.material || "Unknown type"}<small style={{ display: "block" }}>{slot.vendor || "Unknown brand"} · {slot.product_name || "Unknown product"}</small></span>
          </div>)}
        </div>
        {source === "makervault" && assetId && (checking ? <p>Reading sliced filament requirements…</p> : requirements.length ? <>
          <strong>Sliced filament mapping review</strong>
          <p>MakerVault proposes matching loaded slots from the G-code metadata. Your choices are not transmitted to the K2 yet.</p>
          {requirements.map(requirement => {
            const chosen = cfsAssignments[requirement.tool_index] ?? suggestedSlot(requirement);
            const selected = (cfs.slots || []).find(slot => slot.label === chosen);
            const materialMatch = selected && matches(requirement, selected);
            const colourMatch = materialMatch && !!requirement.color_hex && selected.color_hex?.toLowerCase() === requirement.color_hex.toLowerCase();
            return <div key={requirement.tool_index} style={{ margin: "12px 0", padding: 12, border: "1px solid var(--border-color, #344255)", borderRadius: 10 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <strong>Slicer filament {requirement.tool_index + 1}</strong>
                {requirement.color_hex && <span style={{ width: 18, height: 18, borderRadius: 5, border: "1px solid #718096", background: requirement.color_hex }} />}
                <span>{requirement.material || "Unknown material"}{requirement.color_hex ? " · " + requirement.color_hex : ""}</span>
              </div>
              {requirement.preset && <small>Profile: {requirement.preset}</small>}
              <label style={{ display: "block", marginTop: 8 }}>CFS slot for review
                <select value={chosen} onChange={e => setCfsAssignments(previous => ({ ...previous, [requirement.tool_index]: e.target.value }))}>
                  <option value="">Unassigned</option>
                  {(cfs.slots || []).map(slot => <option key={slot.label} value={slot.label}>
                    {slot.label} · {slot.material || "Unknown material"} · {slot.product_name || "Unknown filament"}{slot.color_hex ? " · " + slot.color_hex : ""}
                  </option>)}
                </select>
              </label>
              <small role="status">{!selected ? "No CFS slot selected." : !requirement.material ? "Material unknown — cannot check compatibility." : !materialMatch ? "Material mismatch — do not print using this selection." : colourMatch ? "Material and colour match the slicer metadata (advisory only)." : "Material matches, but colour differs or is unknown."}</small>
            </div>;
          })}
          {!filamentAnalysis?.complete && <p role="status">Slicer metadata is incomplete. Automatic mapping cannot be verified.</p>}
        </> : <p>There are no explicit sliced filament declarations in this G-code. An automatic matching recommendation cannot be made.</p>)}
        {source === "printer" && <p>Files already on the printer do not have source filament metadata in this dialog. No mapping is inferred from the filename.</p>}
        <small>All mapping selections are read-only. Printing through either transport remains disabled when CFS is connected until the printer mapping protocol and acknowledgement are verified.</small>
      </>}
    </div>}
    {cfsSlicedAvailable && <div className="settingsCallout">
      <strong>Print using the G-code's existing CFS mapping</strong>
      <p>The K2 previously accepted slicer-mapped G-code via Moonraker. This mode does not send a new filament selection. Any candidate slot chosen above is for review only and will NOT change the print.</p>
      <label className="checkRow"><input type="checkbox" checked={useSlicedCfs} disabled={busy} onChange={e => { setUseSlicedCfs(e.target.checked); setCfsAcknowledged(false); }} />
        Allow explicit print-start using the original sliced mapping
      </label>
      {useSlicedCfs && <label className="checkRow"><input type="checkbox" checked={cfsAcknowledged} disabled={busy} onChange={e => setCfsAcknowledged(e.target.checked)} />
        I have checked the K2's actual loaded CFS filaments and its expected mapping. I understand MakerVault cannot override or verify the active slot selection.
      </label>}
    </div>}
    {capabilities && !capabilities.supported ? <div className="settingsCallout">
      <strong>Experimental adapter — printer file submission unavailable</strong>
      <p>This source supports monitoring, but its storage and start-print protocol is not implemented or verified here. Bambu storage listing is experimental and read-only; Bambu print-start, proprietary Creality and other manufacturer transfer paths still require dedicated implementation and hardware validation.</p>
    </div> : <>
      <label>Source<select value={source} onChange={e => { setSource(e.target.value); setError(""); setReceipt(null); }}>
        <option value="new">Upload a new G-code file</option>
        <option value="makervault">Existing MakerVault G-code</option>
        <option value="printer" disabled={capabilities && !capabilities.can_browse}>Already stored on the printer</option>
      </select></label>
      {source === "new" && <div className="printingManageForm">
        <label>G-code<input type="file" accept=".gcode" onChange={e => setNewFile(e.target.files?.[0] || null)} /></label>
        <small>This ad-hoc file is saved in MakerVault Files before transfer. It can be linked to a project or model later.</small>
        <button type="button" className="primary" disabled={!newFile || busy || !canEdit} onClick={saveNew}>Save and review</button>
      </div>}
      {source === "makervault" && <label>MakerVault file<select value={assetId} onChange={e => setAssetId(e.target.value)}>
        <option value="">Choose a G-code file…</option>
        {initialAsset && !files.some(f => String(f.id) === String(initialAsset.id)) && <option value={initialAsset.id}>{initialAsset.name} · selected G-code</option>}
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
          <option value="print" disabled={cfs?.applicable && !capabilities?.can_start && !cfsSlicedAvailable}>Upload and start print{cfsSlicedAvailable ? " — original sliced CFS mapping" : cfs?.applicable && !capabilities?.can_start ? " — CFS mode unavailable" : ""}</option>
        </select></label>}
        {(source === "printer" || verdict?.status !== "metadata_match") && <label className="checkRow">
          <input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />
          I have reviewed this file for {printer.name} and understand the printer profile is unverified.
        </label>}
        <div className="formActions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="button" className="primary" onClick={submit}
            disabled={busy || checking || !canEdit || !capabilities?.supported ||
              (source === "printer" ? !remotePath || !(capabilities.can_start || (cfsSlicedAvailable && useSlicedCfs && cfsAcknowledged)) : !assetId || !capabilities.can_upload ||
                (action === "print" && !(capabilities.can_start || (cfsSlicedAvailable && useSlicedCfs && cfsAcknowledged)))) || verdict?.status === "mismatch"}>
            {busy ? "Submitting…" : source === "printer" || action === "print" ? "Review & start print" : "Review & upload only"}
          </button>
        </div>
      </>}
    </>}
    {busy && <div className="gcodeTransferProgress" role="status" aria-live="polite">
      <strong>Printer transfer and verification</strong>
      <progress aria-label="Printer transfer in progress" />
      <p>{transferStage || "Waiting for printer response…"}</p>
      <small>Progress is indeterminate because the printer adapter does not report bytes transferred. The stage text reflects server-side checks. Do not submit another job while this operation is running.</small>
    </div>}
    {receipt && <div className="settingsCallout" role="status">
      <strong>Submission: {receipt.status}</strong><p>{receipt.message}</p>
      <small>Request ID {receipt.request_id} — uncertain requests are never resent automatically.</small>
    </div>}
    </div>
  </Modal>;
}
