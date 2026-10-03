import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, BoardImage, ImageViewer, LoadingBlock, Modal } from "./Common";
import PrintedPartsSection from "./PrintedPartsSection";
import ProjectBomSection from "./ProjectBomSection";
import ProjectWiringSection from "./ProjectWiringSection";
import FileVersionModal from "./FileVersionModal";
import { FileModelViewerModal, ModelThumbnail, isViewableModelFile } from "./ModelViewer";

const STATUS = {
  idea: "Idea",
  planning: "Planning",
  active: "Active",
  paused: "Paused",
  complete: "Complete",
  archived: "Archived",
};

const FILE_CATEGORIES = {
  source: "Source code",
  firmware: "Firmware",
  binary: "Executable / binary",
  cad: "CAD",
  mesh: "STL / mesh",
  slicer: "3MF / slicer project",
  pcb: "PCB",
  wiring: "Wiring / schematic",
  document: "Document",
  archive: "Archive",
  other: "Other",
};

const CATEGORY_ORDER = ["source", "firmware", "binary", "cad", "mesh", "slicer", "pcb", "wiring", "document", "archive", "other"];

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
  if (["kicad_pcb"].includes(ext)) return "pcb";
  if (["kicad_sch"].includes(ext)) return "wiring";
  if (["pdf"].includes(ext)) return "document";
  if (["zip", "7z", "tar", "gz"].includes(ext)) return "archive";
  return "other";
}

function money(value, currency) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "GBP" }).format(Number(value || 0));
}

export default function ProjectsPage({ projects, setProjects, config, refreshDashboard, refreshInventory, boards, components, inventory, openProjectId, onOpenConsumed }) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");

  const filtered = useMemo(() => projects.filter(project => {
    const hay = [project.name, project.summary, project.status_label].join(" ").toLowerCase();
    return hay.includes(search.toLowerCase());
  }), [projects, search]);

  async function openProject(project) {
    setSelected(project);
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch(`/api/projects/${project.id}/`);
      setSelected(result.project);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function refreshProject(project) {
    const result = await apiFetch(`/api/projects/${project.id}/`);
    setSelected(result.project);
    setProjects(rows => rows.map(row => row.id === project.id ? { ...row, ...result.project } : row));
    await refreshDashboard();
  }

  useEffect(() => {
    if (!openProjectId) return;
    const project = projects.find(row => row.id === openProjectId);
    if (!project) return;
    openProject(project);
    onOpenConsumed?.();
  }, [openProjectId, projects]);

  return <div className={`projectLayout ${selected ? "hasDetail" : ""}`}>
    <section className="panel projectPanel">
      <div className="panelHead panelHeadWrap">
        <div><h3>Projects</h3><p>Track builds, inventory, photos, code, firmware, fabrication files and project costs.</p></div>
        <div className="toolbarActions">
          <input className="searchInput" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search projects…" />
          {config?.permissions?.add_project && <button className="primary" onClick={() => setShowCreate(true)}>＋ New project</button>}
        </div>
      </div>
      {error && <div className="inlineError">{error}</div>}
      <div className="projectGrid">
        {filtered.map(project => <button className="projectCard" key={project.id} onClick={() => openProject(project)}>
          <div className="projectCardCover">
            {project.cover_image ? <img src={project.cover_image} alt="" /> : <span>PROJECT</span>}
          </div>
          <div className="projectCardBody">
            <div className="projectCardHead"><h3>{project.name}</h3><Badge tone={project.status === "active" ? "good" : project.status === "idea" ? "accent" : "neutral"}>{project.status_label}</Badge></div>
            <p>{project.summary || "No project summary yet."}</p>
            <div className="projectCardMeta">
              <span>{project.inventory_count || 0} inventory item(s) · {project.bom_count || 0} BOM line(s)</span>
              <span>{project.file_count || 0} file(s) · {project.gallery_count || 0} photo(s)</span>
              <strong>{money(project.inventory_cost, project.currency || config?.currency)}</strong>
            </div>
          </div>
        </button>)}
        {!filtered.length && <div className="projectEmpty"><strong>No projects found.</strong><span>Create a project to start linking inventory and documenting builds.</span></div>}
      </div>
    </section>

    {selected && <ProjectDetail
      project={selected}
      loading={loading}
      canEdit={config?.permissions?.change_project}
      config={config}
      boards={boards}
      components={components}
      inventory={inventory}
      refreshInventory={refreshInventory}
      onClose={() => setSelected(null)}
      onRefresh={refreshProject}
      onUpdated={project => {
        setSelected(project);
        setProjects(rows => rows.map(row => row.id === project.id ? { ...row, ...project } : row));
      }}
    />}

    {showCreate && <ProjectFormModal
      title="Create project"
      project={null}
      onClose={() => setShowCreate(false)}
      onSaved={async project => {
        setProjects(rows => [...rows, project].sort((a,b) => a.name.localeCompare(b.name)));
        setShowCreate(false);
        setSelected(project);
        await refreshDashboard();
      }}
    />}
  </div>;
}

function ProjectDetail({ project, loading, canEdit, config, boards, components, inventory, refreshInventory, onClose, onRefresh, onUpdated }) {
  const [editing, setEditing] = useState(false);
  const [coverOpen, setCoverOpen] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [fileOpen, setFileOpen] = useState(false);
  const [fileVersioning, setFileVersioning] = useState(null);
  const [modelViewerFile, setModelViewerFile] = useState(null);
  const [repositoryOpen, setRepositoryOpen] = useState(false);
  const [viewer, setViewer] = useState(null);

  const filesByCategory = CATEGORY_ORDER.map(category => ({
    category,
    label: FILE_CATEGORIES[category] || category,
    files: (project.files || []).filter(file => file.category === category),
  })).filter(group => group.files.length);

  async function removeFile(file) {
    if (!window.confirm(`Remove "${file.name}" from this project? The stored file will be deleted.`)) return;
    await apiFetch(`/api/projects/${project.id}/files/${file.id}/`, { method: "DELETE" });
    await onRefresh(project);
  }

  async function removeRepository(repository) {
    if (!window.confirm(`Remove repository link "${repository.name}" from this project?`)) return;
    await apiFetch(`/api/projects/${project.id}/repositories/${repository.id}/`, { method: "DELETE" });
    await onRefresh(project);
  }

  if (loading) return <aside className="projectDetailPane"><div className="detailHead"><h3>Project</h3><button className="iconButton" onClick={onClose}>×</button></div><LoadingBlock label="Loading project…" /></aside>;

  return <aside className="projectDetailPane">
    <div className="projectDetailHead"><div><span className="projectEyebrow">Project workspace</span><h2>{project.name}</h2></div><button className="iconButton" onClick={onClose}>×</button></div>
    <div className="projectDetailScroll">
      <button className="projectHero" onClick={() => project.cover_image && setViewer({ src: project.cover_image, title: project.name })}>
        {project.cover_image ? <img src={project.cover_image} alt={project.name} /> : <span>No cover image</span>}
      </button>

      <div className="projectTitleActions">
        <div className="badgeRow"><Badge tone={project.status === "active" ? "good" : project.status === "idea" ? "accent" : "neutral"}>{project.status_label}</Badge>{(project.tags || []).map(tag => <Badge key={tag}>{tag}</Badge>)}</div>
        {canEdit && <div className="detailActions"><button onClick={() => setEditing(true)}>Edit</button><button onClick={() => setCoverOpen(true)}>Cover</button><button onClick={() => setGalleryOpen(true)}>＋ Photo</button><button onClick={() => setFileOpen(true)}>＋ File</button><button onClick={() => setRepositoryOpen(true)}>＋ Repository</button></div>}
      </div>

      {project.summary && <p className="projectSummary">{project.summary}</p>}
      <div className="projectMetrics">
        <div><span>Assigned inventory</span><strong>{project.inventory?.length || project.inventory_count || 0}</strong></div>
        <div><span>Inventory cost</span><strong>{money(project.inventory_cost, project.currency)}</strong></div>
        <div><span>BOM coverage</span><strong>{project.bom_summary?.line_count ? `${project.bom_summary.complete_lines}/${project.bom_summary.line_count}` : "—"}</strong></div>
        <div><span>Project files</span><strong>{project.files?.length || project.file_count || 0}</strong></div>
        <div><span>Repositories</span><strong>{project.repositories?.length || project.repository_count || 0}</strong></div>
        <div><span>Started</span><strong>{project.started_on || "—"}</strong></div>
        <div><span>Completed</span><strong>{project.completed_on || "—"}</strong></div>
      </div>

      <section className="projectSection"><h3>Description</h3><div className="projectRichText">{project.description || "No description yet."}</div></section>
      <section className="projectSection"><h3>Build notes</h3><div className="projectRichText">{project.notes || "No build notes yet."}</div></section>

      <ProjectBomSection
        project={project}
        boards={boards}
        components={components}
        inventory={inventory}
        canEdit={canEdit}
        config={config}
        onRefresh={onRefresh}
        refreshInventory={refreshInventory}
      />

      <PrintedPartsSection config={config} projectId={project.id} projects={[project]} />

      <ProjectWiringSection
        project={project}
        boards={boards}
        components={components}
        inventory={inventory}
        config={config}
      />

      <section className="projectSection">
        <div className="projectSectionHead"><h3>Assigned inventory</h3><span>{project.inventory?.length || 0}</span></div>
        <div className="projectInventoryList">
          {(project.inventory || []).map(item => <div key={item.id} className="projectInventoryRow"><BoardImage src={item.image} alt="" size="tiny" placeholder="INV" /><div><strong>{item.name}</strong><small>{item.inventory_id} · {item.status_label}</small></div><span>{item.quantity}</span></div>)}
          {!project.inventory?.length && <p className="muted">No physical inventory is assigned yet. Assign items from the Inventory page.</p>}
        </div>
      </section>

      <section className="projectSection">
        <div className="projectSectionHead"><h3>Files &amp; assets</h3><span>{project.files?.length || 0}</span></div>
        <p className="projectSectionIntro">Code, firmware, fabrication, electronics and documentation attached to this build.</p>
        <div className="projectAssetGroups">
          {filesByCategory.map(group => <div className="projectAssetGroup" key={group.category}>
            <div className="projectAssetGroupHead"><strong>{group.label}</strong><span>{group.files.length}</span></div>
            <div className="projectAssetList">
              {group.files.map(file => <div className="projectAssetRow" key={file.id}>
                {isViewableModelFile(file)
                  ? <button className="modelThumbnailButton" type="button" onClick={() => setModelViewerFile(file)} title={"View " + file.filename}><ModelThumbnail file={file} /></button>
                  : <div className="projectFileBadge">{(file.filename?.split(".").pop() || "FILE").slice(0,5).toUpperCase()}</div>}
                <div className="projectAssetMain">
                  <strong>{file.name}</strong>
                  <small>{file.filename}{file.version ? ` · v${file.version}` : ""} · {formatBytes(file.size_bytes)}</small>
                  {file.description && <p>{file.description}</p>}
                </div>
                <div className="projectAssetActions">
                  {isViewableModelFile(file) && <button type="button" onClick={() => setModelViewerFile(file)}>View</button>}
                  <a href={file.url} className="assetButton">Download</a>
                  {canEdit && <button type="button" onClick={() => setFileVersioning(file)}>Upload new version</button>}
                  {canEdit && <button className="assetDanger" onClick={() => removeFile(file)}>Remove</button>}
                </div>
              </div>)}
            </div>
          </div>)}
          {!filesByCategory.length && <div className="projectAssetEmpty">No code, firmware, STL/CAD, PCB or document files have been added yet.</div>}
        </div>
      </section>

      <section className="projectSection">
        <div className="projectSectionHead"><h3>Repositories</h3><span>{project.repositories?.length || 0}</span></div>
        <div className="projectRepositoryList">
          {(project.repositories || []).map(repository => <div className="projectRepositoryRow" key={repository.id}>
            <div className="projectRepoProvider">{repository.provider_label || repository.provider}</div>
            <div className="projectAssetMain">
              <strong>{repository.name}</strong>
              <small>{repository.default_branch ? `Default branch: ${repository.default_branch}` : repository.local_path || "Repository link"}</small>
            </div>
            <div className="projectAssetActions">
              {repository.url && <a href={repository.url} target="_blank" rel="noreferrer" className="assetButton">Open ↗</a>}
              {canEdit && <button className="assetDanger" onClick={() => removeRepository(repository)}>Remove</button>}
            </div>
          </div>)}
          {!project.repositories?.length && <p className="muted">No source repositories are linked to this project yet.</p>}
        </div>
      </section>

      <section className="projectSection">
        <div className="projectSectionHead"><h3>Gallery</h3><span>{project.gallery?.length || 0}</span></div>
        <div className="projectGallery">
          {(project.gallery || []).map(image => <button key={image.id} className="projectGalleryItem" onClick={() => setViewer({ src: image.url, title: image.name })}><img src={image.url} alt={image.name} /><span>{image.name}</span></button>)}
          {!project.gallery?.length && <p className="muted">No project photos yet.</p>}
        </div>
      </section>

      {project.reference_url && <a className="detailLink" href={project.reference_url} target="_blank" rel="noreferrer">Open project reference ↗</a>}
    </div>

    {editing && <ProjectFormModal title={`Edit ${project.name}`} project={project} onClose={() => setEditing(false)} onSaved={updated => { setEditing(false); onUpdated(updated); }} />}
    {coverOpen && <ProjectCoverModal project={project} onClose={() => setCoverOpen(false)} onSaved={async updated => { setCoverOpen(false); onUpdated(updated); await onRefresh(updated); }} />}
    {galleryOpen && <ProjectGalleryModal project={project} onClose={() => setGalleryOpen(false)} onSaved={async () => { setGalleryOpen(false); await onRefresh(project); }} />}
    {fileOpen && <ProjectFileModal project={project} categories={project.file_categories || Object.entries(FILE_CATEGORIES).map(([value,label]) => ({ value, label }))} onClose={() => setFileOpen(false)} onSaved={async () => { setFileOpen(false); await onRefresh(project); }} />}
    {fileVersioning && <FileVersionModal
      file={fileVersioning}
      onClose={() => setFileVersioning(null)}
      onSaved={async () => { setFileVersioning(null); await onRefresh(project); }}
    />}
    {modelViewerFile && <FileModelViewerModal file={modelViewerFile} onClose={() => setModelViewerFile(null)} />}
    {repositoryOpen && <ProjectRepositoryModal project={project} onClose={() => setRepositoryOpen(false)} onSaved={async () => { setRepositoryOpen(false); await onRefresh(project); }} />}
    {viewer && <ImageViewer src={viewer.src} alt={viewer.title} title={viewer.title} onClose={() => setViewer(null)} />}
  </aside>;
}

function ProjectFormModal({ title, project, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: project?.name || "",
    status: project?.status || "idea",
    summary: project?.summary || "",
    description: project?.description || "",
    notes: project?.notes || "",
    tags: (project?.tags || []).join(", "),
    reference_url: project?.reference_url || "",
    started_on: project?.started_on || "",
    completed_on: project?.completed_on || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await apiFetch(project ? `/api/projects/${project.id}/` : "/api/projects/", {
        method: project ? "PATCH" : "POST",
        body: form,
      });
      onSaved(result.project);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return <Modal title={title} subtitle="Project metadata, build notes and dates." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">Name<input required value={form.name} onChange={e => set("name", e.target.value)} /></label>
      <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}>{Object.entries(STATUS).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Tags<input value={form.tags} onChange={e => set("tags", e.target.value)} placeholder="ESP32, Home Assistant, sensor" /></label>
      <label>Started<input type="date" value={form.started_on} onChange={e => set("started_on", e.target.value)} /></label>
      <label>Completed<input type="date" value={form.completed_on} onChange={e => set("completed_on", e.target.value)} /></label>
      <label className="full">Summary<input value={form.summary} onChange={e => set("summary", e.target.value)} /></label>
      <label className="full">Description<textarea rows="6" value={form.description} onChange={e => set("description", e.target.value)} /></label>
      <label className="full">Build notes<textarea rows="7" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <label className="full">Reference URL<input type="url" value={form.reference_url} onChange={e => set("reference_url", e.target.value)} placeholder="https://…" /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save project"}</button></div>
    </form>
  </Modal>;
}

function ProjectCoverModal({ project, onClose, onSaved }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function upload(event) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError("");
    try {
      const body = new FormData(); body.append("image", file);
      const result = await apiFetch(`/api/projects/${project.id}/cover/`, { method: "POST", body });
      onSaved(result.project);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  async function remove() {
    setBusy(true); setError("");
    try {
      const result = await apiFetch(`/api/projects/${project.id}/cover/`, { method: "DELETE" });
      onSaved(result.project);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title="Project cover" onClose={onClose}>
    {error && <div className="formError">{error}</div>}
    {project.cover_image && <img className="projectCoverPreview" src={project.cover_image} alt="" />}
    <form onSubmit={upload} className="imageSourceBox"><input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.JPG,.JPEG,.png,.PNG,.webp,.WEBP,.heic,.HEIC,.heif,.HEIF" onChange={e => setFile(e.target.files?.[0] || null)} /><small>JPEG/JPG, PNG, WebP, HEIF and HEIC are supported. MakerVault converts uploads to WebP for display.</small><button className="primary" disabled={!file || busy}>Upload cover</button></form>
    {project.cover_image && <button className="dangerButton" disabled={busy} onClick={remove}>Remove cover</button>}
  </Modal>;
}

function ProjectGalleryModal({ project, onClose, onSaved }) {
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function upload(event) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setError("");
    try {
      const body = new FormData();
      body.append("image", file); body.append("name", name); body.append("description", description);
      await apiFetch(`/api/projects/${project.id}/gallery/`, { method: "POST", body });
      onSaved();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title="Add project photo" onClose={onClose}>
    <form onSubmit={upload} className="formGrid">
      {error && <div className="formError full">{error}</div>}
      <label className="full">Image<input type="file" required accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.JPG,.JPEG,.png,.PNG,.webp,.WEBP,.heic,.HEIC,.heif,.HEIF" onChange={e => setFile(e.target.files?.[0] || null)} /><small>JPEG/JPG, PNG, WebP, HEIF and HEIC are supported. MakerVault converts uploads to WebP for display.</small></label>
      <label className="full">Name<input value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="full">Description<textarea rows="3" value={description} onChange={e => setDescription(e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={!file || busy}>{busy ? "Uploading…" : "Add photo"}</button></div>
    </form>
  </Modal>;
}


function ProjectFileModal({ project, categories, onClose, onSaved }) {
  const [file, setFile] = useState(null);
  const [category, setCategory] = useState("other");
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

  async function upload(event) {
    event.preventDefault();
    if (!file) return;
    setBusy(true); setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("category", category);
      body.append("name", name);
      body.append("version", version);
      body.append("description", description);
      await apiFetch(`/api/projects/${project.id}/files/`, { method: "POST", body });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add project file" subtitle="Store a project asset in MakerVault and classify it for the relevant project section." onClose={onClose} wide>
    <form className="formGrid" onSubmit={upload}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">File<input type="file" required onChange={e => chooseFile(e.target.files?.[0] || null)} /></label>
      <label>Category<select value={category} onChange={e => setCategory(e.target.value)}>{categories.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label>Version<input value={version} onChange={e => setVersion(e.target.value)} placeholder="e.g. 1.0, rev B" /></label>
      <label className="full">Display name<input value={name} onChange={e => setName(e.target.value)} placeholder={file?.name || "Project file"} /></label>
      <label className="full">Description<textarea rows="4" value={description} onChange={e => setDescription(e.target.value)} placeholder="What this file is for, build notes, compatibility, etc." /></label>
      <div className="projectUploadHint full">MakerVault will keep the original file, record its SHA-256 hash and make non-image assets download-only.</div>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={!file || busy}>{busy ? "Uploading…" : "Add file"}</button></div>
    </form>
  </Modal>;
}

function ProjectRepositoryModal({ project, onClose, onSaved }) {
  const [provider, setProvider] = useState("github");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await apiFetch(`/api/projects/${project.id}/repositories/`, {
        method: "POST",
        body: { provider, name, url, local_path: localPath, default_branch: defaultBranch },
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Link repository" subtitle="Keep the source repository alongside the project assets it produces." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Provider<select value={provider} onChange={e => setProvider(e.target.value)}><option value="github">GitHub</option><option value="gitlab">GitLab</option><option value="local">Local</option><option value="other">Other</option></select></label>
      <label>Default branch<input value={defaultBranch} onChange={e => setDefaultBranch(e.target.value)} placeholder="main" /></label>
      <label className="full">Name<input required value={name} onChange={e => setName(e.target.value)} placeholder="Smart speaker firmware" /></label>
      <label className="full">Repository URL<input type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://github.com/…" /></label>
      <label className="full">Local path<input value={localPath} onChange={e => setLocalPath(e.target.value)} placeholder="/projects/smart-speaker (optional)" /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !name || (!url && !localPath)}>{busy ? "Saving…" : "Link repository"}</button></div>
    </form>
  </Modal>;
}

