import React, { useMemo, useState } from "react";
import { apiFetch } from "../api";
import { insertGcodeAfterLayer } from "../utils/gcodeLayerInsertion";

const MAX_SOURCE_BYTES = 32 * 1024 * 1024;

/** Explicit, reversible G-code edits at a verified layer transition only. */
export default function GcodeLayerInsert({ file, selectedZ, nextZ, onSaved, onCancel }) {
  const [code, setCode] = useState("");
  const [version, setVersion] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const target = useMemo(() =>
    Number.isFinite(selectedZ) && Number.isFinite(nextZ)
      ? `After Z ${selectedZ.toFixed(2)} mm, before Z ${nextZ.toFixed(2)} mm`
      : "Final layer cannot be followed by a new layer",
    [selectedZ, nextZ]);
  const canInsert = Number.isFinite(selectedZ) && Number.isFinite(nextZ) && nextZ > selectedZ;

  async function loadAndPreview() {
    if (!canInsert || !code.trim()) return;
    setBusy(true); setError(""); setPreview(null);
    try {
      // Always inspect the full, stored source; the sampled visualiser data and
      // bounded quick-inspection text cannot safely identify an insertion point.
      const response = await fetch(
        `/api/files/${encodeURIComponent(file.id)}/gcode/source/`,
        { credentials: "same-origin" },
      );
      if (!response.ok) throw new Error(`Complete G-code retrieval failed (HTTP ${response.status}).`);
      const blob = await response.blob();
      if (!blob.size || blob.size > MAX_SOURCE_BYTES)
        throw new Error("Only complete G-code files of 32 MiB or less can be edited here.");
      const source = await blob.text();
      // Reject a truncated/invalid source as well as ambiguous layer markers.
      const proposed = insertGcodeAfterLayer(source, selectedZ, nextZ, code);
      setPreview(proposed);
    } catch (err) { setError(err.message || "Unable to prepare this insertion."); }
    finally { setBusy(false); }
  }

  async function saveRevision() {
    if (!preview || !acknowledged || !version.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const payload = new FormData();
      payload.append("file", new File(
        [preview.text], file.filename || file.name || "layer-edited.gcode",
        { type: "text/plain" },
      ));
      payload.append("version", version.trim());
      payload.append("description",
        `Manual layer G-code insertion after Z ${preview.selectedZ.toFixed(3)} mm; original G-code retained.`);
      // Existing immutable asset version endpoint; this does not replace the
      // original slicer output, queue a print or submit commands to a printer.
      await apiFetch(`/api/files/${encodeURIComponent(file.id)}/versions/`, {
        method: "POST", body: payload,
      });
      await onSaved?.();
      onCancel?.();
    } catch (err) { setError(err.message || "Unable to save the edited version."); }
    finally { setBusy(false); }
  }

  return <section className="slicerGcodeLayerInsert" aria-label="Insert G-code after selected layer">
    <div className="settingsActions" style={{ justifyContent: "space-between", alignItems: "center" }}>
      <strong>Insert G-code at layer boundary</strong>
      <button type="button" onClick={onCancel} disabled={busy} aria-label="Close layer insertion">Close</button>
    </div>
    <p className="projectUploadHint">
      {target}. This inserts the commands immediately before the next layer marker,
      not at an approximate position from the sampled toolpath preview.
    </p>
    {!canInsert && <p className="formError">Choose a layer that has another layer above it.</p>}
    <label>Commands for this printer
      <textarea aria-label="Commands to insert after selected layer" value={code}
        onChange={e => { setCode(e.target.value); setPreview(null); setAcknowledged(false); }}
        rows={5} maxLength={2048} spellCheck={false} placeholder={"Example (only if supported by your printer):\nM0"}
        disabled={!canInsert || busy} />
    </label>
    <p className="projectUploadHint">
      Pauses are firmware-specific: Marlin M0, Klipper PAUSE, and other
      mechanisms are not interchangeable. Confirm the correct command for your
      printer before adding it. Machine commands can affect motion and temperature.
    </p>
    {error && <div className="formError" role="alert">{error}</div>}
    <div className="settingsActions">
      <button type="button" onClick={loadAndPreview} disabled={!canInsert || !code.trim() || busy}>
        {busy ? "Processing…" : "Preview insertion"}
      </button>
    </div>
    {preview && <>
      <p role="status">
        Insertion verified at complete G-code line {preview.line.toLocaleString()}.
        Original sliced file remains unchanged.
      </p>
      <pre className="slicerGcodeInsertSnippet">{preview.code}</pre>
      <label>New file version
        <input value={version} maxLength={50} placeholder="e.g. 1.1-pause"
          onChange={e => setVersion(e.target.value)} disabled={busy} />
      </label>
      <label className="checkRow">
        <input type="checkbox" checked={acknowledged} disabled={busy}
          onChange={e => setAcknowledged(e.target.checked)} />
        I have checked these commands against the selected printer's firmware.
      </label>
      <button type="button" className="primary" disabled={!acknowledged || !version.trim() || busy}
        onClick={saveRevision}>
        {busy ? "Saving…" : "Save as new G-code version"}
      </button>
      <small>Reopen the saved version and inspect it before transfer. An edited version is
        not automatically approved, uploaded or started. Slicer time estimates
        will not automatically account for inserted pauses.</small>
    </>}
  </section>;
}
