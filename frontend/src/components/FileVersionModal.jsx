import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";


export function suggestNextVersion(value) {
  const text = String(value || "").trim();
  if (!/^\d+(?:\.\d+)*$/.test(text)) return "";
  const parts = text.split(".").map(Number);
  parts[parts.length - 1] += 1;
  return parts.join(".");
}


export default function FileVersionModal({ file, onClose, onSaved }) {
  const [upload, setUpload] = useState(null);
  const [version, setVersion] = useState(suggestNextVersion(file.version));
  const [description, setDescription] = useState(file.description || "");
  const [versions, setVersions] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    apiFetch("/api/files/" + file.id + "/versions/")
      .then(result => { if (active) setVersions(result.versions || []); })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoadingHistory(false); });
    return () => { active = false; };
  }, [file.id]);

  async function submit(event) {
    event.preventDefault();
    if (!upload || !version.trim()) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", upload);
      body.append("version", version.trim());
      body.append("description", description);
      const result = await apiFetch("/api/files/" + file.id + "/versions/", {
        method: "POST",
        body,
      });
      await onSaved?.(result.file);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal
    title={"Upload new version · " + file.name}
    subtitle="The previous file is kept as version history; MakerVault shows the newest version in Files and Projects."
    onClose={onClose}
    wide
  >
    <div className="fileVersionLayout">
      <form className="formGrid" onSubmit={submit}>
        {error && <div className="formError full">{error}</div>}
        <label className="full">New file
          <input type="file" required onChange={event => setUpload(event.target.files?.[0] || null)} />
          <small>{upload ? upload.name : "Choose the replacement file for this logical asset."}</small>
        </label>
        <label>Version
          <input required value={version} onChange={event => setVersion(event.target.value)} placeholder="e.g. 1.1, rev B" />
        </label>
        <label className="full">Description
          <textarea rows="3" value={description} onChange={event => setDescription(event.target.value)} />
        </label>
        <div className="formActions full">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!upload || !version.trim() || busy}>{busy ? "Uploading…" : "Upload new version"}</button>
        </div>
      </form>

      <section className="fileVersionHistory">
        <div className="fileVersionHistoryHead"><strong>Version history</strong><span>{loadingHistory ? "Loading…" : versions.length + " version" + (versions.length === 1 ? "" : "s")}</span></div>
        {!loadingHistory && versions.map((item, index) => <div className="fileVersionHistoryRow" key={item.id}>
          <div>
            <strong>{item.version ? "v" + item.version : index === 0 ? "Current" : "Unlabelled"}</strong>
            <small>{item.filename}</small>
          </div>
          <a href={item.url} className="assetButton">Download</a>
        </div>)}
      </section>
    </div>
  </Modal>;
}
