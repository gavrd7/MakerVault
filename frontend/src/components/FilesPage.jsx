import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock, Modal } from "./Common";
import FileVersionModal from "./FileVersionModal";
import { FileModelViewerModal, ModelThumbnail, isViewableModelFile } from "./ModelViewer";

const CATEGORY_ORDER = ["source", "firmware", "binary", "cad", "mesh", "slicer", "pcb", "wiring", "document", "archive", "other"];
const ALLOWED_FILE_TYPES = [
  ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".txt", ".md",
  ".zip", ".7z", ".tar", ".gz", ".ino", ".cpp", ".h", ".hpp", ".py", ".yaml", ".yml",
  ".json", ".toml", ".bin", ".hex", ".uf2", ".elf", ".exe", ".msi",
  ".stl", ".3mf", ".obj", ".step", ".stp", ".iges", ".igs", ".f3d", ".fcstd",
  ".sldprt", ".scad", ".dxf", ".gcode", ".bgcode", ".kicad_pcb", ".kicad_sch",
].join(",");

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function inferFileCategory(filename) {
  const ext = (filename.split(".").pop() || "").toLowerCase();
  if (["ino", "cpp", "h", "hpp", "py", "yaml", "yml", "json", "toml", "md", "txt"].includes(ext)) return "source";
  if (["bin", "hex", "uf2", "elf"].includes(ext)) return "firmware";
  if (["exe", "msi"].includes(ext)) return "binary";
  if (["stl", "obj"].includes(ext)) return "mesh";
  if (["3mf", "gcode", "bgcode"].includes(ext)) return "slicer";
  if (["step", "stp", "iges", "igs", "f3d", "fcstd", "sldprt", "scad", "dxf"].includes(ext)) return "cad";
  if (ext === "kicad_pcb") return "pcb";
  if (ext === "kicad_sch") return "wiring";
  if (ext === "pdf") return "document";
  if (["zip", "7z", "tar", "gz"].includes(ext)) return "archive";
  return "other";
}

export default function FilesPage({ projects, onOpenProject, config }) {
  const [rows, setRows] = useState([]);
  const [categories, setCategories] = useState([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [projectId, setProjectId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [versioning, setVersioning] = useState(null);
  const [viewerFile, setViewerFile] = useState(null);

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
      if (projectId === "__standalone__" && file.project_id) return false;
      if (projectId && projectId !== "__standalone__" && file.project_id !== projectId) return false;
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

  async function removeFile(file) {
    if (!window.confirm(`Delete "${file.name}" from MakerVault? The stored file will also be removed.`)) return;
    try {
      await apiFetch(`/api/files/${file.id}/`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return <div className="filesStack">
    <section className="panel filesHero">
      <div>
        <span className="settingsEyebrow">Digital build library</span>
        <h2>Files &amp; assets</h2>
        <p>Store standalone code and maker files here, or link an upload to a project. Project-linked assets remain the same FileAsset record everywhere in MakerVault.</p>
      </div>
      <div className="filesHeroActions">
        <div className="filesHeroCount"><strong>{filtered.length}</strong><span>{filtered.length === 1 ? "asset" : "assets"}</span></div>
        {config?.permissions?.add_file && <button className="primary" onClick={() => setUploadOpen(true)}>＋ Upload file</button>}
      </div>
    </section>

    <section className="panel filesBrowser">
      <div className="filesToolbar">
        <input className="searchInput" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search files, projects, versions…" />
        <select value={category} onChange={e => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {categories.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select value={projectId} onChange={e => setProjectId(e.target.value)}>
          <option value="">All files</option>
          <option value="__standalone__">Standalone files</option>
          {(projects || []).map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
        <button onClick={load}>Refresh</button>
      </div>

      {error && <div className="inlineError">{error}</div>}
      {loading ? <LoadingBlock label="Loading files…" /> : <div className="filesCategoryGrid">
        {groups.map(group => <section className="filesCategory" key={group.value}>
          <div className="filesCategoryHead"><div><h3>{group.label}</h3><p>{group.rows.length} {group.rows.length === 1 ? "asset" : "assets"}</p></div><Badge>{group.value}</Badge></div>
          <div className="filesRows">
            {group.rows.map(file => <article className="filesRow" key={file.id}>
              {isViewableModelFile(file)
                ? <button className="modelThumbnailButton" type="button" onClick={() => setViewerFile(file)} title={"View " + file.filename}><ModelThumbnail file={file} /></button>
                : <div className="projectFileBadge">{(file.filename?.split(".").pop() || "FILE").slice(0,5).toUpperCase()}</div>}
              <div className="filesRowMain">
                <div className="filesNameRow"><strong>{file.name}</strong>{!file.project_id && <Badge tone="accent">Standalone</Badge>}</div>
                <small>{file.filename}{file.version ? ` · v${file.version}` : ""} · {formatBytes(file.size_bytes)}</small>
                {file.description && <p>{file.description}</p>}
                <div className="filesRowLinks">
                  {file.project ? <button className="linkButton" onClick={() => onOpenProject?.(file.project_id)}>Project: {file.project}</button> : <span>Not assigned to a project</span>}
                  {file.board && <span>Board: {file.board}</span>}
                  {file.component && <span>Component: {file.component}</span>}
                </div>
              </div>
              <div className="projectAssetActions">
                {isViewableModelFile(file) && <button type="button" onClick={() => setViewerFile(file)}>View</button>}
                <a href={file.url} className="assetButton">Download</a>
                {config?.permissions?.change_file && <button onClick={() => setVersioning(file)}>Upload new version</button>}
                {config?.permissions?.change_file && <button onClick={() => setEditing(file)}>Manage</button>}
                {config?.permissions?.change_file && <button className="assetDanger" onClick={() => removeFile(file)}>Remove</button>}
              </div>
            </article>)}
          </div>
        </section>)}
        {!groups.length && <div className="projectEmpty"><strong>No matching files.</strong><span>Upload a standalone file, add a project asset, or change the current filters.</span></div>}
      </div>}
    </section>

    {uploadOpen && <FileUploadModal
      categories={categories}
      projects={projects}
      onClose={() => setUploadOpen(false)}
      onSaved={async () => { setUploadOpen(false); await load(); }}
    />}
    {editing && <FileManageModal
      file={editing}
      categories={categories}
      projects={projects}
      onClose={() => setEditing(null)}
      onSaved={async () => { setEditing(null); await load(); }}
    />}
    {versioning && <FileVersionModal
      file={versioning}
      onClose={() => setVersioning(null)}
      onSaved={async () => { setVersioning(null); await load(); }}
    />}
    {viewerFile && <FileModelViewerModal file={viewerFile} onClose={() => setViewerFile(null)} />}
  </div>;
}

function FileUploadModal({ categories, projects, onClose, onSaved }) {
  const [file, setFile] = useState(null);
  const [category, setCategory] = useState("other");
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function chooseFile(selected) {
    setFile(selected);
    if (!selected) return;
    setCategory(inferFileCategory(selected.name));
    if (!name) setName(selected.name.replace(/\.[^.]+$/, ""));
  }

  async function submit(event) {
    event.preventDefault();
    if (!file) return;
    setBusy(true); setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("category", category);
      body.append("project_id", projectId);
      body.append("name", name);
      body.append("version", version);
      body.append("description", description);
      await apiFetch("/api/files/", { method: "POST", body });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Upload file" subtitle="Leave Project as Standalone to keep this asset independent of any project." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">File<input type="file" accept={ALLOWED_FILE_TYPES} required onChange={e => chooseFile(e.target.files?.[0] || null)} /></label>
      <label>Category<select value={category} onChange={e => setCategory(e.target.value)}>{categories.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label>Project<select value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">Standalone</option>{(projects || []).map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      <label>Version<input value={version} onChange={e => setVersion(e.target.value)} placeholder="Optional" /></label>
      <label>Display name<input value={name} onChange={e => setName(e.target.value)} placeholder={file?.name || "File name"} /></label>
      <label className="full">Description<textarea rows="4" value={description} onChange={e => setDescription(e.target.value)} placeholder="What this file contains or is used for." /></label>
      <div className="projectUploadHint full">Uploads use MakerVault's existing supported file-type list and authenticated storage rules. Unsupported extensions are still rejected by the backend.</div>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={!file || busy}>{busy ? "Uploading…" : "Upload file"}</button></div>
    </form>
  </Modal>;
}

function FileManageModal({ file, categories, projects, onClose, onSaved }) {
  const [category, setCategory] = useState(file.category || "other");
  const [projectId, setProjectId] = useState(file.project_id || "");
  const [name, setName] = useState(file.name || "");
  const [version, setVersion] = useState(file.version || "");
  const [description, setDescription] = useState(file.description || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await apiFetch(`/api/files/${file.id}/`, {
        method: "PATCH",
        body: { category, project_id: projectId, name, version, description },
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={`Manage ${file.name}`} subtitle={file.filename} onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Category<select value={category} onChange={e => setCategory(e.target.value)}>{categories.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label>Project<select value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">Standalone</option>{(projects || []).map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      <label>Version<input value={version} onChange={e => setVersion(e.target.value)} /></label>
      <label>Display name<input required value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="full">Description<textarea rows="4" value={description} onChange={e => setDescription(e.target.value)} /></label>
      <div className="projectUploadHint full">Changing the project moves the same stored asset between standalone and project-linked use; it does not duplicate the file.</div>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button></div>
    </form>
  </Modal>;
}
