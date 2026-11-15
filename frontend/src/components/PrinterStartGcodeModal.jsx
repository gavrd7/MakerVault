import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { findSlicedRequirement } from "../utils/gcodeMapping";
import { Modal } from "./Common";

export default function PrinterStartGcodeModal({ printer, connection, canEdit, onConfigureMoonraker, onClose, onChanged, onSubmissionConfirmed, initialAsset = null, initialAction = "upload" }) {
  const [source, setSource] = useState("makervault");
  const [action, setAction] = useState(initialAction === "print" ? "print" : "upload");
  const [files, setFiles] = useState([]);
  const [remoteFiles, setRemoteFiles] = useState([]);
  const [assetId, setAssetId] = useState(initialAsset?.id ? String(initialAsset.id) : "");
  const [remotePath, setRemotePath] = useState("");
  const [newFile, setNewFile] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [verdict, setVerdict] = useState(null);

  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [receipt, setReceipt] = useState(null);
  const [transferStage, setTransferStage] = useState("");
  const [bambuPin, setBambuPin] = useState("");
  const [filamentAnalysis, setFilamentAnalysis] = useState(null);
  const [slicedPrintSetup, setSlicedPrintSetup] = useState(null);
  const [printerInspection, setPrinterInspection] = useState(null);
  const [printerInspectNotice, setPrinterInspectNotice] = useState("");
  const [printerInspecting, setPrinterInspecting] = useState(false);
  const [cfsAssignments, setCfsAssignments] = useState({});
  const [mappingMode, setMappingMode] = useState("mapped");


  // Do not treat a transport acknowledgement or uncertain CFS dispatch as
  // proof that a print actually started. Only surface confirmed outcomes.
  const isConfirmedSubmission = (submission, submittedAction) => {
    if (submittedAction === "upload") return submission?.status === "uploaded";
    if (submission?.status !== "started") return false;
    const message = String(submission.message || "").toLowerCase();
    return !(/awaiting .*verif|without acknowledgement|awaiting live job|commands dispatched|not acknowledge|unknown outcome|check the k2 display|verify on printer/.test(message));
  };
  const base = "/api/printing/printers/" + printer.id + "/connections/" + connection.id + "/gcode";
  const cfs = capabilities?.cfs || null;
  const cfsSlicedAvailable = Boolean(capabilities?.can_start_sliced_mapping);
  const cfsOriginalSupported = Boolean(capabilities?.supports_original_mapping);
  const cfsMappedAvailable = Boolean(capabilities?.can_start_mapped_cfs);
  const selectedAnalysis = source === "printer" ? printerInspection?.filaments : filamentAnalysis;
  const selectedSetup = source === "printer" ? printerInspection?.print_setup : slicedPrintSetup;
  const requirements = source !== "new" && selectedAnalysis?.usage_confident
    ? (selectedAnalysis?.used_requirements || []) : [];
  const usageUnknown = source !== "new" && (source === "printer" ? !!remotePath : !!assetId)
    && !!selectedAnalysis && !selectedAnalysis.usage_confident;
  const sameMaterial = (left, right) => Boolean(left && right) && left.trim().toUpperCase() === right.trim().toUpperCase();
  const matches = (requirement, slot) => sameMaterial(requirement.material, slot.material);
  const suggestedSlot = (requirement) => (cfs?.slots || []).find(slot =>
    matches(requirement, slot) && requirement.color_hex &&
    slot.color_hex?.toLowerCase() === requirement.color_hex.toLowerCase()
  )?.label || "";
  const current = files.find(f => String(f.id) === String(assetId)) || (initialAsset && String(initialAsset.id) === String(assetId) ? initialAsset : null);

  async function load(refreshStatus = false) {
    // A broken printer-side file API must not hide perfectly valid MakerVault files.
    const [local, privateSlices, remote] = await Promise.allSettled([
      // Library G-code is independent of the selected printer adapter.
      apiFetch("/api/files/?category=gcode"),
      // Completed private slice outputs remain selectable for an explicit
      // printer transfer without being silently saved into the G-code library.
      apiFetch("/api/printing/slicer/jobs/"),
      apiFetch(base + (refreshStatus === true ? "/files/?refresh_status=1" : "/files/")),
    ]);
    const libraryFiles = local.status === "fulfilled"
      ? (local.value.rows || []).filter(f => f.category === "gcode")
      : [];
    const pendingFiles = privateSlices.status === "fulfilled"
      ? (privateSlices.value.jobs || [])
        .filter(job => job.status === "completed" && !job.gcode_in_library && job.output_asset?.id)
        .map(job => ({
          ...job.output_asset,
          category: "other",
          privateSlice: true,
          project: "Private sliced output",
        }))
      : [];
    const knownIds = new Set(libraryFiles.map(file => String(file.id)));
    const allFiles = [...libraryFiles];
    for (const file of pendingFiles) {
      if (!knownIds.has(String(file.id))) {
        knownIds.add(String(file.id));
        allFiles.push(file);
      }
    }
    setFiles(allFiles);
    if (local.status === "rejected" && privateSlices.status === "rejected") {
      setError("MakerVault G-code sources unavailable: " + local.reason.message);
    } else if (local.status === "rejected") {
      setNotice("Saved G-code library could not be loaded; private slices remain available.");
    } else if (privateSlices.status === "rejected") {
      setNotice("Private slicing jobs could not be loaded; saved G-code remains available.");
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
    // A Creality print-start may be confirmed by a later normal telemetry
    // poll. Read only the existing receipt; never re-submit the command.
    if (!["started", "unknown"].includes(receipt?.status) ||
        !(receipt.message?.startsWith("Awaiting native Creality start verification") ||
          receipt.message?.startsWith("Print-start sent without acknowledgement; awaiting live job verification") ||
          receipt.message?.startsWith("Print-start command accepted; awaiting live job verification")) ||
        !receipt.request_id) return undefined;
    let active = true;
    let checks = 0;
    const timer = window.setInterval(async () => {
      if (!active || ++checks > 24) {
        window.clearInterval(timer);
        return;
      }
      try {
        const result = await apiFetch(base + "/submissions/" + receipt.request_id + "/");
        const updated = result?.submission;
        if (!active || !updated) return;
        if (updated.message?.startsWith("Print started — verified by live printer telemetry") ||
            updated.message?.startsWith("Print start confirmed by live Creality telemetry") ||
            ["rejected", "uploaded"].includes(updated.status)) {
          window.clearInterval(timer);
          setReceipt(updated);
          setTransferStage(updated.message || "");
          if (updated.status === "started") {
            setError("");
            setNotice("Print start verified using the printer's live job status.");
            onChanged?.();
            onSubmissionConfirmed?.(updated);
          }
        }
      } catch (_err) {
        // A temporary connection error cannot be taken as proof of failure.
      }
    }, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [receipt?.request_id, receipt?.status, receipt?.message, base]);



  useEffect(() => {
    let active = true;
    setVerdict(null);
    setFilamentAnalysis(null);
    setSlicedPrintSetup(null);
    setCfsAssignments({});

    if (source !== "makervault" || !assetId) return () => { active = false; };
    setChecking(true);
    apiFetch("/api/files/" + assetId + "/gcode/inspect/?printer_id=" + encodeURIComponent(printer.id))
      .then(data => { if (active) { setVerdict(data.compatibility); setFilamentAnalysis(data.analysis?.filaments || null); setSlicedPrintSetup(data.analysis?.print_setup || null); } })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [source, assetId, printer.id]);

  useEffect(() => {
    let active = true;
    setPrinterInspection(null);
    setPrinterInspectNotice("");
    setCfsAssignments({});
    if (source !== "printer" || !remotePath) return () => { active = false; };
    setPrinterInspecting(true);
    apiFetch(base + "/files/?inspect_path=" + encodeURIComponent(remotePath))
      .then(data => { if (active) setPrinterInspection(data.analysis || null); })
      .catch(err => { if (active) setPrinterInspectNotice(err.message || "File inspection unavailable. Original mapping remains available."); })
      .finally(() => { if (active) setPrinterInspecting(false); });
    return () => { active = false; };
  }, [source, remotePath, connection.id, printer.id]);

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
    const mappedCfs = operation === "print" && mappingMode === "mapped" && cfsMappedAvailable && requirements.length > 0 && !usageUnknown && (source === "printer" ? !!printerInspection : !!assetId);
    const originalSelected = operation === "print" && mappingMode === "original" && cfs?.connected === true;
    const slicedCfs = originalSelected && cfsSlicedAvailable;
    if (originalSelected && !cfsSlicedAvailable) {
      setError(cfsOriginalSupported
        ? "Original slicer mapping is supported, but the printer is not ready. Refresh its status after the current print finishes."
        : "Original slicer mapping is unavailable on this connection. Select compatible CFS slots instead.");
      return;
    }
    const selections = requirements.map(r => ({
      tool_index: r.tool_index, slot_label: cfsAssignments[r.tool_index] ?? suggestedSlot(r)
    }));
    if (mappedCfs) {
      if (!selections.length || selections.some(item => !item.slot_label)) {
        setError("Select a loaded CFS slot for each filament actually used by this print."); return;
      }
      for (const item of selections) {
        const required = findSlicedRequirement(requirements, item.tool_index);
        const loaded = (cfs?.slots || []).find(slot => slot.label === item.slot_label);
        if (!required?.material || !loaded || !matches(required, loaded)) {
          setError("Sliced and loaded material types must agree before mapped printing."); return;
        }
      }
    }
    if (!name) { setError("Select a G-code file."); return; }
    if (operation === "print" && !capabilities?.can_start && !slicedCfs && !mappedCfs) { setError("Choose a supported print mode first."); return; }

    if (verdict?.status === "mismatch") { setError("Printer model mismatch; submission blocked."); return; }
    const mappingSummary = mappedCfs
      ? selections.map(item => "Slicer " + (item.tool_index + 1) + " (" + (findSlicedRequirement(requirements, item.tool_index)?.material || "?") + ") → CFS " + item.slot_label).join("\n")
      : slicedCfs ? "Use original slicer mapping (no slot changes)." : "";
    if (!window.confirm("Printer: " + printer.name + "\nFile: " + name + "\nAction: " +
      (operation === "print" ? "START PRINT" : "UPLOAD ONLY, no printing") +
      (mappingSummary ? "\n\nCFS mapping:\n" + mappingSummary : "") +
      (mappedCfs ? "\n\nK2 native start has no command acknowledgement. Check the selected filament on the printer." : "") +

      "\n\nContinue?")) return;
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
          file_asset_id: assetId, confirmed: true, acknowledge_unknown: true,
          cfs_mode: mappedCfs ? "mapped" : slicedCfs ? "use_sliced" : null,
          cfs_acknowledged: slicedCfs,
          cfs_mapping: mappedCfs ? selections : [],
        },
      });
      setReceipt(result.submission);
      setTransferStage(result.submission?.message || "Printer responded.");
      if (result.submission?.status === "unknown") {
        if (mappedCfs && result.submission?.message?.includes("mapping and print-start commands dispatched")) {
          setNotice("CFS print commands were sent. Check the K2 display and filament selection; the printer does not acknowledge the command.");
        } else if (result.submission?.message?.startsWith("Awaiting native Creality start verification") ||
                   result.submission?.message?.startsWith("Print-start sent without acknowledgement; awaiting live job verification")) {
          setNotice("Print command sent. Checking the printer's live status for the selected file; no further print command will be sent.");
        } else {
          setError("Printer outcome is uncertain. Inspect the printer before trying anything else.");
        }
      }
      // A temporary UI refresh failure must not turn a confirmed submission
      // into an apparent printer error or tempt a second submission.
      try { await onChanged?.(); } catch (_refreshError) { /* Submission receipt is authoritative. */ }
      if (isConfirmedSubmission(result.submission, operation)) {
        onSubmissionConfirmed?.(result.submission);
      }
    } catch (err) { setError(err.message); setTransferStage("Submission failed or could not be verified."); }
    finally { window.clearInterval(statusTimer); setBusy(false); }
  }

  return <Modal title={"G-code printing · " + printer.name}
    subtitle="Select one source and explicitly confirm upload or start. Nothing runs automatically."
    onClose={onClose} wide>
    <div className="gcodePrintModalContent">
    {error && <div className="formError" role="alert">{error}</div>}
    {notice && (connection.adapter === "creality_local" && notice.includes("Diagnostic:")
      ? <details className="settingsCallout">
          <summary><strong>Native printer storage listing unavailable — view diagnostics</strong></summary>
          <p style={{ overflowWrap: "anywhere" }}>{notice}</p>
          <small>Native HTTP upload can be verified independently using an enabled Moonraker storage connection on this same printer.</small>
        </details>
      : <div className="settingsCallout">{notice}</div>)}
    {connection.adapter === "prusa" && <div className="settingsCallout"><strong>PrusaLink file transfer</strong><p>Native PrusaLink v1 file listing, upload and start support is unverified on physical hardware. Unsupported firmware returns an error; never assume print acceptance until confirmed on the printer.</p></div>}
    {connection.adapter === "bambu_local" && <div className="printingManageForm">
      <strong>Bambu LAN storage — file browser</strong>
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
      <strong>Printer file submission unavailable</strong>
      <p>This source supports monitoring, but its storage and start-print protocol is not implemented or verified here. Bambu storage listing is read-only; Bambu print-start, proprietary Creality and other manufacturer transfer paths still require dedicated implementation and hardware validation.</p>
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
      {source === "makervault" && <>
        <label>MakerVault file<select value={assetId} onChange={e => setAssetId(e.target.value)}>
          <option value="">Choose a G-code file…</option>
          {initialAsset && !files.some(f => String(f.id) === String(initialAsset.id)) && <option value={initialAsset.id}>{initialAsset.name} · selected G-code</option>}
          {files.map(f => <option value={f.id} key={f.id}>{f.name} · {f.privateSlice ? "Private slice (not in library)" : (f.project || "Standalone")}</option>)}
        </select></label>
        {!files.length && !initialAsset && <p role="status">No library G-code or completed private slices were returned. Check the G-code Library and slicing jobs.</p>}
      </>}
      {source === "printer" && <>
        <label>Printer storage<select value={remotePath} onChange={e => setRemotePath(e.target.value)}>
          <option value="">Choose a printer file…</option>
          {remoteFiles.map(f => <option key={f.path} value={f.path}>{f.path}</option>)}
        </select></label>
        <button type="button" disabled={busy} onClick={() => load()}>Refresh printer storage</button>
      </>}
    {source !== "new" && (source === "printer" ? !!printerInspection : !!assetId) && <div className="settingsCallout">
      <strong>Sliced print settings</strong>
      <p><strong>Nozzle:</strong> {selectedSetup?.nozzle_diameters_mm?.length
        ? selectedSetup.nozzle_diameters_mm.map(value => `${value} mm`).join(", ")
        : "Not specified"} · <strong>Build plate:</strong> {selectedSetup?.bed_type || "Not specified"}</p>
      <small>These are the slicer's recorded settings, not detected printer hardware. They are provided for reference and never restrict submission.</small>
    </div>}
    {cfs?.applicable && !(capabilities?.k1_native_model && cfs.connected === false) && <div className="settingsCallout">
      <strong>Creality CFS · Live loaded filaments</strong>
      <p>{cfs.connected === true
        ? "These materials were reported by the K2's native LAN telemetry. Match the sliced filaments against the loaded CFS slots before printing."
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
        {source !== "new" && (source === "printer" ? !!remotePath : !!assetId) && ((checking || printerInspecting) ? <p>Reading sliced filament requirements…</p> : requirements.length ? <>
          <strong>Filaments used by this print</strong>
          <p>Only tools with detected extrusion are listed. Choose the loaded filament to use for each tool; changing colour within the same material is allowed.</p>
          {requirements.map(requirement => {
            const chosen = cfsAssignments[requirement.tool_index] ?? suggestedSlot(requirement);
            const selected = (cfs.slots || []).find(slot => slot.label === chosen);
            const materialMatch = selected && matches(requirement, selected);
            const colourMatch = materialMatch && !!requirement.color_hex && selected.color_hex?.toLowerCase() === requirement.color_hex.toLowerCase();
            return <div key={requirement.tool_index} style={{ margin: "12px 0", padding: 12, border: "1px solid var(--border-color, #344255)", borderRadius: 10 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <strong>Used slicer filament {requirement.tool_index + 1}</strong>
                {requirement.color_hex && <span style={{ width: 18, height: 18, borderRadius: 5, border: "1px solid #718096", background: requirement.color_hex }} />}
                <span>{requirement.material || "Unknown material"}{requirement.color_hex ? " · " + requirement.color_hex : ""}</span>
              </div>
              {requirement.preset && <small>Profile: {requirement.preset}</small>}
              {source !== "new" && mappingMode === "mapped" && cfsMappedAvailable ? <label style={{ display: "block", marginTop: 8 }}>Print with CFS slot
                <select value={chosen} onChange={e => setCfsAssignments(previous => ({ ...previous, [requirement.tool_index]: e.target.value }))}>
                  <option value="">Unassigned</option>
                  {(cfs.slots || []).map(slot => <option key={slot.label} value={slot.label}>
                    {slot.label} · {slot.material || "Unknown material"} · {slot.product_name || "Unknown filament"}{slot.color_hex ? " · " + slot.color_hex : ""}
                  </option>)}
                </select>
              </label> : <p>Original slicer mapping retained; this selection is not overridden.</p>}
              <small role="status">{!selected ? "No CFS slot selected." : !requirement.material ? "Material unknown — cannot check compatibility." : !materialMatch ? "Material mismatch — do not print using this selection." : colourMatch ? "Material and colour match the slicer metadata (advisory only)." : "Material matches, but colour differs or is unknown."}</small>
            </div>;
          })}
          {!selectedAnalysis?.used_complete && <p role="status">Slicer metadata for at least one used filament is incomplete. Check the intended material and colour carefully; mapped printing requires a known material type for every tool.</p>}
        </> : <div>
          <p>{usageUnknown ? "MakerVault cannot confirm which filament profiles are actually used. Unverified overrides are disabled; the original slicer mapping remains available where supported." : "No depositing filament requirements could be identified. You can upload without printing, or use the original slicer mapping where supported."}</p>
          {selectedAnalysis && <details>
            <summary>Tool detection details</summary>
            <p>{selectedAnalysis.usage_reason || "Slicer tool usage was not available."}</p>
            <small>Declared profiles: {(selectedAnalysis.requirements || []).length}; tools selected: {(selectedAnalysis.toolpath_evidence?.selected_tools || []).map(i => i + 1).join(", ") || "none"}; depositing tools found: {(selectedAnalysis.toolpath_evidence?.extruding_tools || []).map(i => i + 1).join(", ") || "none"}; unassigned extrusion moves: {selectedAnalysis.toolpath_evidence?.unassigned_extrusions ?? "unknown"}; detection: {selectedAnalysis.usage_source || "unknown"}</small>
          </details>}
        </div>)}
        {source === "printer" && !printerInspection && !printerInspecting && <p>{printerInspectNotice || "Read-only G-code inspection is unavailable for this printer file. Use its original slicer mapping or save the file in MakerVault to review its materials."}</p>}
        <small>In mapped-print mode, selections are sent to the K2. The proprietary protocol does not confirm acceptance, so check its display after submitting.</small>
      </>}
    </div>}
    {source !== "new" && (cfs?.connected === true || cfsOriginalSupported || cfsMappedAvailable) && <div className="settingsCallout">
      <strong>CFS print preparation</strong>
      <p>Review the sliced filament and select the correct loaded CFS slot. You can send these selections to the K2 or use its original slicer mapping.</p>
      <label>Filament mapping
        <select value={mappingMode === "mapped" && (!cfsMappedAvailable || !requirements.length || usageUnknown) ? "original" : mappingMode} onChange={e => setMappingMode(e.target.value)}>
          {cfsMappedAvailable && requirements.length > 0 && !usageUnknown && <option value="mapped">Use selected CFS slots — send mapping to K2</option>}
          <option value="original" disabled={!cfsOriginalSupported}>Use original mapping embedded by the slicer{!cfsOriginalSupported ? " — unavailable on this connection" : ""}</option>
        </select>
      </label>
      <small>{requirements.length > 0 && mappingMode === "mapped"
        ? "MakerVault will send a new native K2 filament mapping before print-start. Check the printer display."
        : cfsOriginalSupported
          ? "The original slicer assignments are retained." + (!cfsSlicedAvailable ? " Wait until the printer is ready before starting." : "")
          : "Original mapping requires a supported printer connection; you can still choose loaded CFS slots manually."}</small>
    </div>}
      {source === "makervault" && (checking ? <p>Analysing printer metadata…</p> : verdict && <div className="settingsCallout" role="status">
        <strong>{verdict.status === "mismatch" ? "Printer mismatch — blocked" : verdict.status === "metadata_match" ? "Printer name matches; full safety not verified" : "Printer identity unknown"}</strong>
        <p>{verdict.reason}</p>
      </div>)}
      {source !== "new" && <>
        {capabilities?.k1_native_model && capabilities?.can_start === false && <div className="settingsCallout" role="status">
          <strong>K1 native print-start unavailable</strong>
          {(capabilities.k1_start_blockers || []).map((reason, index) => <p key={index}>{reason}</p>)}
          <button type="button" disabled={busy || checking} onClick={() => load(true)}>
            Refresh K1 readiness (read-only)
          </button>
        </div>}
        {source === "makervault" && <label>Operation<select value={action} onChange={e => setAction(e.target.value)}>
          <option value="upload">Upload only — do not print</option>
          <option value="print" disabled={cfs?.applicable && !capabilities?.can_start && !cfsSlicedAvailable && !cfsMappedAvailable}>Upload and start print{cfsMappedAvailable ? " — review CFS slots" : cfsSlicedAvailable ? " — original sliced CFS mapping" : cfs?.applicable && !capabilities?.can_start ? " — CFS mode unavailable" : ""}</option>
        </select></label>}
        <div className="formActions">
          {connection.adapter === "creality_local" && <details style={{ marginRight: "auto", alignSelf: "center", maxWidth: "min(100%, 370px)", textAlign: "left" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.85rem" }}>Other connection option</summary>
            <div style={{ paddingTop: 8, fontSize: "0.85rem" }}>
              <p>Moonraker / Klipper is an optional additional printer connection. Native Creality monitoring, CFS detection and uploads do not require it.</p>
              {onConfigureMoonraker && <button type="button" onClick={onConfigureMoonraker}>Configure Moonraker connection</button>}
            </div>
          </details>}
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="button" className="primary" onClick={submit}
            disabled={busy || checking || printerInspecting || !canEdit || !capabilities?.supported ||
              (source === "printer" ? !remotePath || !(capabilities.can_start || cfsSlicedAvailable || (cfsMappedAvailable && requirements.length > 0 && !!printerInspection)) : !assetId || !capabilities.can_upload ||
                (action === "print" && !(capabilities.can_start || cfsSlicedAvailable || cfsMappedAvailable))) || verdict?.status === "mismatch"}>
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
      <strong>{receipt.status === "unknown" && (receipt.message?.startsWith("Awaiting native Creality start verification") || receipt.message?.startsWith("Print-start sent without acknowledgement; awaiting live job verification"))
        ? "Print command sent — checking live status"
        : receipt.status === "started" && receipt.message?.startsWith("Print-start command accepted; awaiting live job verification")
          ? "Print command accepted — checking live status"
        : receipt.status === "started" && (receipt.message?.includes("confirmed by live Creality telemetry") || receipt.message?.startsWith("Print started — verified by live printer telemetry"))
          ? "Print started — verified"
          : receipt.status === "unknown" && receipt.message?.includes("mapping and print-start commands dispatched")
            ? "Print command sent — verify on K2" : "Submission: " + receipt.status}</strong><p>{receipt.message}</p>
      <small>Request ID {receipt.request_id} — uncertain requests are never resent automatically.</small>
    </div>}
    </div>
  </Modal>;
}
