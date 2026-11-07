import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";

/** Owner-scoped slice history, usable independently of an installed engine. */
export default function SavedSlicerJobsModal({ onClose, onOpenSlicer, assetIds = null, title = "Saved slicing drafts" }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  const [showAll, setShowAll] = useState(false);
  const allowedIds = useMemo(() => assetIds ? new Set(assetIds.map(String)) : null,
    [assetIds]);

  async function reload() {
    setLoading(true); setError("");
    try {
      const data = await apiFetch("/api/printing/slicer/jobs/");
      setJobs(data.jobs || []);
    } catch (err) {
      setError(err.message || "Could not load saved slicing drafts.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); }, []);

  const matching = jobs.filter(job => !allowedIds ||
    allowedIds.has(String(job.input_asset?.id)) ||
    (job.settings?.plate_objects || []).some(part => allowedIds.has(String(part.asset_id))));
  const visible = matching.filter(job => showAll || job.status === "draft");

  async function addGcodeToLibrary(job) {
    if (job.status !== "completed" || !job.output_asset_id || job.gcode_in_library) return;
    setBusyId(job.id); setError("");
    try {
      await apiFetch("/api/printing/slicer/jobs/" + job.id + "/save-gcode/", {
        method: "POST", body: {},
      });
      await reload();
    } catch (err) {
      setError(err.message || "Could not add the generated G-code to your library.");
    } finally {
      setBusyId("");
    }
  }

  async function cancel(job) {
    if (!["draft", "queued"].includes(job.status)) return;
    setBusyId(job.id); setError("");
    try {
      await apiFetch("/api/printing/slicer/jobs/" + job.id + "/cancel/", { method: "POST", body: {} });
      await reload();
    } catch (err) {
      setError(err.message || "Could not cancel this draft.");
    } finally {
      setBusyId("");
    }
  }

  return <Modal title={title} subtitle="Your saved slicer configurations" onClose={onClose} wide>
    <div className="printingHeroActions">
      <button type="button" onClick={reload} disabled={loading}>Refresh</button>
      <label><input type="checkbox" checked={showAll} onChange={event => setShowAll(event.target.checked)} /> Show completed and other jobs</label>
      <button type="button" className="primary" onClick={() => { onClose(); onOpenSlicer?.(); }}>Open MakerVault Slicer</button>
    </div>
    {error && <p role="alert" className="integrationError">{error}</p>}
    {loading ? <p role="status">Loading saved slicing drafts…</p> :
      visible.length ? <div className="printingStack">{visible.map(job =>
        <div key={job.id} className="cameraSourceRow">
          <div className="cameraSourceIdentity">
            <strong>{job.input_asset?.name || "Model"} · {job.printer?.name || "Printer"}</strong>
            <small>{job.engine} · {job.engine_version} · {job.status}</small>
            <small>{job.process_preset || "No process selected"} · {job.spool?.name || "No linked spool"}</small>
            <small>{job.message || (job.status === "draft" ? "Saved configuration; not sliced" : "Slice job recorded")}</small>
          </div>
          <div className="cameraSourceActions">
            <button type="button" onClick={() => { onClose(); onOpenSlicer?.(job.id); }}>Open in slicer</button>
            {job.status === "draft" && job.can_slice &&
              <span title="A verified engine is available. Open the slicer to start this draft.">Ready to slice</span>}
            {job.status === "completed" && job.output_asset_id && !job.gcode_in_library &&
              <button type="button" disabled={Boolean(busyId)} onClick={() => addGcodeToLibrary(job)}>
                {busyId === job.id ? "Saving…" : "Add G-code to library"}
              </button>}
            {job.status === "completed" && job.gcode_in_library && <small>G-code in library</small>}
            {["draft", "queued"].includes(job.status) &&
              <button type="button" disabled={Boolean(busyId)} onClick={() => cancel(job)}>
                {busyId === job.id ? "Cancelling…" : "Cancel draft"}
              </button>}
          </div>
        </div>
      )}</div> : <p>{allowedIds
        ? "No matching saved slice drafts for this model."
        : showAll ? "No slicing jobs saved yet." : "No active slice drafts. Show completed and other jobs to view history."}</p>}
  </Modal>;
}
