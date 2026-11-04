import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";

// Read-only analysis is evidence, not proof of safe G-code or firmware compatibility.
export default function GcodeViewerModal({ file, canEdit = false, onClose, onSaved }) {
  const [report, setReport] = useState(null);
  const [text, setText] = useState("");
  const [mode, setMode] = useState("visual");
  const [edited, setEdited] = useState(false);
  const [version, setVersion] = useState("");
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
  return <Modal title={`G-code · ${file.name}`} subtitle="Read-only analysis. A matching printer must be verified separately before uploading or printing." onClose={onClose} wide>
    {error && <div className="formError">{error}</div>}
    {loading ? <p>Inspecting G-code…</p> : report && <>
      <div className="formActions" style={{ justifyContent: "flex-start" }}>
        <button type="button" className={mode === "visual" ? "primary" : ""} onClick={() => setMode("visual")}>Visual toolpath</button>
        <button type="button" className={mode === "code" ? "primary" : ""} onClick={() => setMode("code")}>G-code text</button>
        <a className="assetButton" href={file.url}>Download original</a>
      </div>
      <p><strong>Intended printer:</strong> {analysis.printer_hints?.join(", ") || "Unknown — no verified printer metadata"}</p>
      {analysis.slicer_hints?.length > 0 && <p><strong>Slicer:</strong> {analysis.slicer_hints.join(", ")}</p>}
      <p><strong>XY moves:</strong> {analysis.xy_moves?.toLocaleString() || 0} · <strong>Coordinates:</strong> {["X", "Y", "Z"].map(axis => bounds[axis]?.[0] == null ? `${axis} unknown` : `${axis} ${bounds[axis][0].toFixed(1)}–${bounds[axis][1].toFixed(1)} mm`).join(" · ")}</p>
      {(analysis.warnings || []).map((warning, i) => <div className="projectUploadHint" key={i}>{warning}</div>)}
      {mode === "visual" ? <div style={{ maxWidth: 600, margin: "12px auto" }}>
        {preview ? <svg viewBox="0 0 590 590" role="img" aria-label="Top-down XY toolpath preview; non-authoritative" style={{ width: "100%", background: "#101820", borderRadius: 10 }}>
          <polyline points={preview} fill="none" stroke="#b0a2ff" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        </svg> : <p>No XY movements found.</p>}
        <small>Top-down XY trajectory only; not a validated print preview. {analysis.xy_preview_sampled ? "Only the first 3,000 moves are shown." : ""} Extrusion, machine-specific instructions and clearance are not fully simulated.</small>
      </div> : <div>
        <textarea value={text} onChange={e => { setText(e.target.value); setEdited(true); }} readOnly={!canEdit || report.preview_truncated} spellCheck={false} aria-label="G-code source" rows={17} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }} />
        {report.preview_truncated && <p>Only the beginning of this file is displayed. Editing is disabled to prevent saving a truncated file.</p>}
        {canEdit && !report.preview_truncated && <>
          <label>New file version<input value={version} onChange={e => setVersion(e.target.value)} placeholder="e.g. 1.1" /></label>
          <button type="button" disabled={!edited || !version.trim() || busy} onClick={saveRevision}>{busy ? "Saving…" : "Save as new file version"}</button>
          <small>Original G-code is retained. Always revalidate edited instructions before printing.</small>
        </>}
      </div>}
      <p><strong>Printer submission:</strong> Not yet enabled. Printer capability detection, readiness, and an explicit confirmation workflow must pass before upload/start controls are made available.</p>
    </>}
    <div className="formActions"><button type="button" onClick={onClose}>Close</button></div>
  </Modal>;
}
