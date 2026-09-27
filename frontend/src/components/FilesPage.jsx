import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock } from "./Common";

const CATEGORY_ORDER = ["source", "firmware", "binary", "cad", "mesh", "slicer", "pcb", "wiring", "document", "archive", "other"];

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export default function FilesPage({ projects, onOpenProject }) {
  const [rows, setRows] = useState([]);
  const [categories, setCategories] = useState([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [projectId, setProjectId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch("/api/files/");
      setRows(result.rows || []);
      setCategories(result.categories || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows.filter(file => {
      if (category && file.category !== category) return false;
      if (projectId && file.project_id !== projectId) return false;
      if (!needle) return true;
      return [file.name, file.filename, file.description, file.version, file.project, file.category_label]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [rows, search, category, projectId]);

  const groups = CATEGORY_ORDER.map(value => ({
    value,
    label: categories.find(item => item.value === value)?.label || value,
    rows: filtered.filter(file => file.category === value),
  })).filter(group => group.rows.length);

  return <div className="filesStack">
    <section className="panel filesHero">
      <div>
        <span className="settingsEyebrow">Digital build library</span>
        <h2>Files &amp; assets</h2>
        <p>Every technical file stored here is the same asset shown inside its linked project. Upload from a project workspace, then browse it here by category or project.</p>
      </div>
      <div className="filesHeroCount"><strong>{filtered.length}</strong><span>{filtered.length === 1 ? "asset" : "assets"}</span></div>
    </section>

    <section className="panel filesBrowser">
      <div className="filesToolbar">
        <input className="searchInput" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search files, projects, versions…" />
        <select value={category} onChange={e => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {categories.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select value={projectId} onChange={e => setProjectId(e.target.value)}>
          <option value="">All projects</option>
          {(projects || []).map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
        <button onClick={load}>Refresh</button>
      </div>

      {error && <div className="inlineError">{error}</div>}
      {loading ? <LoadingBlock label="Loading project files…" /> : <div className="filesCategoryGrid">
        {groups.map(group => <section className="filesCategory" key={group.value}>
          <div className="filesCategoryHead"><div><h3>{group.label}</h3><p>{group.rows.length} {group.rows.length === 1 ? "asset" : "assets"}</p></div><Badge>{group.value}</Badge></div>
          <div className="filesRows">
            {group.rows.map(file => <article className="filesRow" key={file.id}>
              <div className="projectFileBadge">{(file.filename?.split(".").pop() || "FILE").slice(0,5).toUpperCase()}</div>
              <div className="filesRowMain">
                <strong>{file.name}</strong>
                <small>{file.filename}{file.version ? ` · v${file.version}` : ""} · {formatBytes(file.size_bytes)}</small>
                {file.description && <p>{file.description}</p>}
                <div className="filesRowLinks">
                  {file.project && <button className="linkButton" onClick={() => onOpenProject?.(file.project_id)}>Project: {file.project}</button>}
                  {file.board && <span>Board: {file.board}</span>}
                  {file.component && <span>Component: {file.component}</span>}
                </div>
              </div>
              <div className="projectAssetActions">
                <a href={file.url} className="assetButton">Download</a>
              </div>
            </article>)}
          </div>
        </section>)}
        {!groups.length && <div className="projectEmpty"><strong>No matching files.</strong><span>Add files from a project workspace or change the current filters.</span></div>}
      </div>}
    </section>
  </div>;
}
