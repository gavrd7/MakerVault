import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import PrinterStartGcodeModal from "./PrinterStartGcodeModal";
import SlicerGcodePreview from "./SlicerGcodePreview";
import GcodeFullSource from "./GcodeFullSource";

// Read-only analysis is evidence, not proof of safe G-code or firmware compatibility.
export default function GcodeViewerModal({ file, canEdit = false, onClose, onSaved, onOpenModel, embedded = false, bedSize = null, objectSettings = null, globalProcessOverrides = null }) {
  const [report, setReport] = useState(null);
  const [text, setText] = useState("");
  const [mode, setMode] = useState("visual");
  const [fullSource, setFullSource] = useState(false);
  const [edited, setEdited] = useState(false);
  const [version, setVersion] = useState("");
  const [printerId, setPrinterId] = useState("");
  const [printerCheck, setPrinterCheck] = useState(null);
  const [checkingPrinter, setCheckingPrinter] = useState(false);
  const [transfer, setTransfer] = useState(null);
  const [findingConnection, setFindingConnection] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setLoading(true);
    apiFetch(`/api/files/${file.id}/gcode/inspect/`).then(data => {
      if (!live) return;
      setReport(data);
      setText(data.preview || "");
      setLoading(false);
    }).catch(err => {
      if (live) { setError(err.message); setLoading(false); }
    });
    return () => { live = false; };
  }, [file.id]);

  const preview = useMemo(() => {
    const points = report?.analysis?.xy_preview || [];
    if (!points.length) return "";
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const scale = Math.max(maxX - minX, maxY - minY, 0.01);
    return points.map(p => `${((p[0] - minX) / scale * 550 + 20).toFixed(1)},${((maxY - p[1]) / scale * 550 + 20).toFixed(1)}`).join(" ");
  }, [report]);

  async function choosePrinter(id) {
    setPrinterId(id); setPrinterCheck(null);
    if (!id) return;
    setCheckingPrinter(true); setError("");
    try {
      const result = await apiFetch(`/api/files/${file.id}/gcode/inspect/?printer_id=${encodeURIComponent(id)}`);
      setPrinterCheck(result.compatibility);
    } catch (err) { setError(err.message); }
    finally { setCheckingPrinter(false); }
  }

  async function sendToPrinter() {
    if (!printerId || checkingPrinter || !printerCheck || printerCheck.status === "mismatch" || edited) return;
    setFindingConnection(true); setError("");
    try {
      const response = await apiFetch("/api/printing/printers/" + encodeURIComponent(printerId) + "/connections/");
      const connections = (response.rows || []).filter(item => item.enabled !== false);
      // Prefer the manufacturer's native transport; Moonraker remains an optional alternative.
      const native = connections.find(item => item.adapter === "creality_local");
      const connection = native || connections.find(item => ["moonraker", "octoprint", "prusa", "flashforge"].includes(item.adapter));
      if (!connection) throw new Error("No enabled G-code transfer connection is configured for this printer. Configure a printer connection under 3D Printing first.");
      const printer = (report?.printers || []).find(item => String(item.id) === String(printerId));
      if (!printer) throw new Error("The selected printer is no longer available.");
      setTransfer({ printer, connection });
    } catch (err) { setError(err.message); }
    finally { setFindingConnection(false); }
  }

  async function saveRevision() {
    if (!version.trim() || !edited || !report || report.preview_truncated) return;
    setBusy(true); setError("");
    try {
      // Never mutate the original: store an explicit immutable file revision.
      const body = new FormData();
      body.append("file", new File([text], file.filename || "edited.gcode", { type: "text/plain" }));
      body.append("version", version.trim());
      body.append("description", "Edited in MakerVault G-code viewer");
      await apiFetch(`/api/files/${file.id}/versions/`, { method: "POST", body });
      await onSaved?.();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const analysis = report?.analysis || {};
  const bounds = analysis.bounds_mm || {};
  if (transfer && !embedded) return <PrinterStartGcodeModal
    printer={transfer.printer} connection={transfer.connection} canEdit
    initialAsset={file}
    onClose={() => setTransfer(null)}
  />;

  const content = <>
    {embedded && <h3>G-code preview · {file.name}</h3>}
    {error && <div className="formError">{error}</div>}
    {loading ? <p>Inspecting G-code…</p> : report && <>
      <div className="formActions" style={{ justifyContent: "flex-start" }}>
        <button type="button" className={mode === "visual" ? "primary" : ""} onClick={() => setMode("visual")}>Visual toolpath</button>
        <button type="button" className={mode === "code" ? "primary" : ""} onClick={() => setMode("code")}>G-code text</button>
        <a className="assetButton" href={`/api/files/${encodeURIComponent(file.id)}/gcode/source/?download=1`}>Download complete G-code</a>
      </div>
      <p><strong>Linked model:</strong> {report.linked_models?.length
        ? report.linked_models.map(link => <button key={link.revision_id} type="button" onClick={() => onOpenModel?.(link.model_id)} disabled={!onOpenModel}>{link.model_name} · revision {link.revision}</button>)
        : "Not linked — attach this file to a model revision in Model Library."}</p>
      {!embedded && <label>Check against a MakerVault printer
        <select value={printerId} onChange={e => choosePrinter(e.target.value)}>
          <option value="">Choose printer for advisory compatibility check</option>
          {(report.printers || []).map(printer => <option value={printer.id} key={printer.id}>{printer.name} · {printer.model}</option>)}
        </select>
      </label>}
      {!embedded && checkingPrinter && <p>Checking explicit printer metadata…</p>}
      {!embedded && printerCheck && <p role="status"><strong>{printerCheck.status === "mismatch" ? "Printer mismatch — block printing" : printerCheck.status === "metadata_match" ? "Printer metadata matches (not safety-verified)" : "Printer compatibility unknown — do not start"}:</strong> {printerCheck.reason}</p>}
      <p><strong>Intended printer:</strong> {analysis.printer_hints?.join(", ") || "Unknown — no verified printer metadata"}</p>
      {analysis.slicer_hints?.length > 0 && <p><strong>Slicer:</strong> {analysis.slicer_hints.join(", ")}</p>}
      <p><strong>Sliced nozzle:</strong> {analysis.print_setup?.nozzle_diameters_mm?.length
        ? analysis.print_setup.nozzle_diameters_mm.map(size => `${size} mm`).join(", ")
        : "Not specified"} · <strong>Build plate:</strong> {analysis.print_setup?.bed_type || "Not specified"}</p>
      <p><strong>XY moves:</strong> {analysis.xy_moves?.toLocaleString() || 0} · <strong>Coordinates:</strong> {["X", "Y", "Z"].map(axis => bounds[axis]?.[0] == null ? `${axis} unknown` : `${axis} ${bounds[axis][0].toFixed(1)}–${bounds[axis][1].toFixed(1)} mm`).join(" · ")}</p>
      {Array.isArray(objectSettings) && objectSettings.length > 0 && <div className="settingsCallout">
        <strong>Settings saved with this slicing job</strong>
        <p>These are the requested plate overrides from the saved draft, not independently measured values from the generated G-code. Compare with the per-object extrusion evidence in Complete G-code.</p>
        <div style={{ overflowX: "auto" }}>
          <table className="dataTable" style={{ width: "100%" }}>
            <thead><tr><th>Plate instance</th><th>Wall loops</th><th>Sparse infill</th><th>Additional overrides</th></tr></thead>
            <tbody>{objectSettings.map((item, index) => {
              const overrides = item.process_overrides || {};
              const global = globalProcessOverrides || {};
              const other = Object.entries(overrides).filter(([key]) => !["wall_loops", "sparse_infill_density"].includes(key));
              return <tr key={item.instance_id || index}>
                <td>Object {index + 1}</td>
                <td>{overrides.wall_loops ?? global.wall_loops ?? "Native profile"}</td>
                <td>{overrides.sparse_infill_density ?? global.sparse_infill_density ?? "Native profile"}{(overrides.sparse_infill_density ?? global.sparse_infill_density) != null ? "%" : ""}</td>
                <td>{other.length ? other.map(([key, value]) => `${key}: ${value}`).join(" · ") : "None"}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
      </div>}
      {(analysis.warnings || []).map((warning, i) => <div className="projectUploadHint" key={i}>{warning}</div>)}
      {mode === "visual" && embedded && analysis.slicer_preview
        ? <SlicerGcodePreview fileId={file.id} preview={analysis.slicer_preview} bedSize={bedSize}
            file={file} canEdit={canEdit} onSaved={onSaved} />
        : mode === "visual" ? <div style={{ maxWidth: 600, margin: "12px auto" }}>
        {preview ? <svg viewBox="0 0 590 590" role="img" aria-label="Top-down XY toolpath preview; non-authoritative" style={{ width: "100%", background: "#101820", borderRadius: 10 }}>
          <polyline points={preview} fill="none" stroke="#b0a2ff" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        </svg> : <p>No XY movements found.</p>}
        <small>Top-down XY trajectory only; not a validated print preview. {analysis.xy_preview_sampled ? "Only the first 3,000 moves are shown." : ""} Extrusion, machine-specific instructions and clearance are not fully simulated.</small>
      </div> : <div>
        <div className="formActions" style={{ justifyContent: "flex-start" }}>
          <button type="button" className={!fullSource ? "primary" : ""} onClick={() => setFullSource(false)}>Quick inspection</button>
          <button type="button" className={fullSource ? "primary" : ""} onClick={() => setFullSource(true)}>Complete G-code</button>
        </div>
        {fullSource ? <GcodeFullSource fileId={file.id} /> : <textarea value={text} onChange={e => { setText(e.target.value); setEdited(true); setPrinterCheck(null); }} readOnly={!canEdit || report.preview_truncated} spellCheck={false} aria-label="G-code source" rows={17} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }} />}
        {!fullSource && report.preview_truncated && <p>This quick inspection is limited to the beginning of the file. Open <strong>Complete G-code</strong> to search, inspect, copy or download all lines. Editing remains disabled to protect the original.</p>}
        {!fullSource && canEdit && !report.preview_truncated && <>
          <label>New file version<input value={version} onChange={e => setVersion(e.target.value)} placeholder="e.g. 1.1" /></label>
          <button type="button" disabled={!edited || !version.trim() || busy} onClick={saveRevision}>{busy ? "Saving…" : "Save as new file version"}</button>
          <small>Original G-code is retained. Always revalidate edited instructions before printing.</small>
        </>}
      </div>}
      {!embedded && <div className="settingsCallout">
        <strong>Send to printer</strong>
        <p>Use the selected printer to upload this original G-code file. Upload only is the default; starting a print requires separate confirmation and available printer capabilities.</p>
        {edited && <p>Unsaved editor changes will not be sent. Save a new file version and inspect it before sending.</p>}
        <button type="button" className="primary" disabled={!printerId || !printerCheck || checkingPrinter || findingConnection || edited || printerCheck.status === "mismatch"} onClick={sendToPrinter}>
          {findingConnection ? "Checking printer connection…" : "Send to printer"}
        </button>
      </div>}
    </>}
    {!embedded && <div className="formActions"><button type="button" onClick={onClose}>Close</button></div>}
  </>;
  return embedded ? content : <Modal title={`G-code · ${file.name}`}
    subtitle="Read-only analysis. A matching printer must be verified separately before uploading or printing."
    onClose={onClose} wide className={mode === "visual" && analysis.slicer_preview ? "slicerPreviewModal" : ""}>{content}</Modal>;
}
