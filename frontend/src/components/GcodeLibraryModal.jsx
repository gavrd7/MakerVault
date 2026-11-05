import React, { useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import GcodeViewerModal from "./GcodeViewerModal";

export default function GcodeLibraryModal({ files = [], projects = [], canUpload = false, onClose, onSaved }) {
  const [selected, setSelected] = useState(null);
  const [upload, setUpload] = useState(null);
  const [projectId, setProjectId] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const rows = files.filter(file => [file.name, file.filename, file.project]
    .join(" ").toLowerCase().includes(query.trim().toLowerCase()));

  async function submit(event) {
    event.preventDefault();
    if (!upload) return;
    setBusy(true); setError("");
    try {
      const body = new FormData();
      body.append("file", upload);
      body.append("category", "gcode");
      body.append("project_id", projectId);
      body.append("name", upload.name.replace(/\.gcode$/i, ""));
      await apiFetch("/api/files/", { method: "POST", body });
      setUpload(null);
      await onSaved?.();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <Modal title="G-code library" subtitle="Stored in MakerVault Files, shared across projects, model revisions and print history." onClose={onClose} wide>
    {error && <div className="formError">{error}</div>}
    {canUpload && <form className="formGrid" onSubmit={submit}>
      <label className="full">Upload G-code<input type="file" accept=".gcode" required onChange={e => setUpload(e.target.files?.[0] || null)} /></label>
      <label>Project<select value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">Standalone</option>{projects.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
      <div className="formActions"><button type="submit" disabled={!upload || busy} className="primary">{busy ? "Uploading…" : "Add G-code"}</button></div>
    </form>}
    <input className="searchInput" style={{ width: "100%", margin: "12px 0" }} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search G-code files and projects…" />
    <div className="printingRevisionList">
      {rows.map(file => <div className="filesRow" key={file.id}>
        <div className="filesRowMain"><strong>{file.name}</strong><small>{file.filename} · {file.project || "Standalone"}</small></div>
        <div className="projectAssetActions">
          <button type="button" onClick={() => setSelected(file)}>Inspect</button>
          <a href={file.url} className="assetButton">Download</a>
        </div>
      </div>)}
      {!rows.length && <p>{query ? "No matching G-code files." : "No G-code files yet. Upload a plain .gcode file to start."}</p>}
    </div>
    {selected && <GcodeViewerModal file={selected} onClose={() => setSelected(null)} onSaved={async () => { setSelected(null); await onSaved?.(); }} />}
    <div className="formActions"><button type="button" onClick={onClose}>Close</button></div>
  </Modal>;
}
