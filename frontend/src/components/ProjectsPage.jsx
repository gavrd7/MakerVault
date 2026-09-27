import React, { useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, BoardImage, ImageViewer, LoadingBlock, Modal } from "./Common";

const STATUS = {
  idea: "Idea",
  planning: "Planning",
  active: "Active",
  paused: "Paused",
  complete: "Complete",
  archived: "Archived",
};

function money(value, currency) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "GBP" }).format(Number(value || 0));
}

export default function ProjectsPage({ projects, setProjects, config, refreshDashboard }) {
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

  return <div className={`projectLayout ${selected ? "hasDetail" : ""}`}>
    <section className="panel projectPanel">
      <div className="panelHead panelHeadWrap">
        <div><h3>Projects</h3><p>Track builds, assigned inventory, photos, notes and project costs.</p></div>
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
              <span>{project.inventory_count || 0} inventory item(s)</span>
              <span>{project.gallery_count || 0} photo(s)</span>
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

function ProjectDetail({ project, loading, canEdit, onClose, onRefresh, onUpdated }) {
  const [editing, setEditing] = useState(false);
  const [coverOpen, setCoverOpen] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [viewer, setViewer] = useState(null);

  if (loading) return <aside className="projectDetailPane"><div className="detailHead"><h3>Project</h3><button className="iconButton" onClick={onClose}>×</button></div><LoadingBlock label="Loading project…" /></aside>;

  return <aside className="projectDetailPane">
    <div className="projectDetailHead"><div><span className="projectEyebrow">Project workspace</span><h2>{project.name}</h2></div><button className="iconButton" onClick={onClose}>×</button></div>
    <div className="projectDetailScroll">
      <button className="projectHero" onClick={() => project.cover_image && setViewer({ src: project.cover_image, title: project.name })}>
        {project.cover_image ? <img src={project.cover_image} alt={project.name} /> : <span>No cover image</span>}
      </button>

      <div className="projectTitleActions">
        <div className="badgeRow"><Badge tone={project.status === "active" ? "good" : project.status === "idea" ? "accent" : "neutral"}>{project.status_label}</Badge>{(project.tags || []).map(tag => <Badge key={tag}>{tag}</Badge>)}</div>
        {canEdit && <div className="detailActions"><button onClick={() => setEditing(true)}>Edit</button><button onClick={() => setCoverOpen(true)}>Cover</button><button onClick={() => setGalleryOpen(true)}>＋ Photo</button></div>}
      </div>

      {project.summary && <p className="projectSummary">{project.summary}</p>}
      <div className="projectMetrics">
        <div><span>Assigned inventory</span><strong>{project.inventory?.length || project.inventory_count || 0}</strong></div>
        <div><span>Inventory cost</span><strong>{money(project.inventory_cost, project.currency)}</strong></div>
        <div><span>Started</span><strong>{project.started_on || "—"}</strong></div>
        <div><span>Completed</span><strong>{project.completed_on || "—"}</strong></div>
      </div>

      <section className="projectSection"><h3>Description</h3><div className="projectRichText">{project.description || "No description yet."}</div></section>
      <section className="projectSection"><h3>Build notes</h3><div className="projectRichText">{project.notes || "No build notes yet."}</div></section>

      <section className="projectSection">
        <div className="projectSectionHead"><h3>Assigned inventory</h3><span>{project.inventory?.length || 0}</span></div>
        <div className="projectInventoryList">
          {(project.inventory || []).map(item => <div key={item.id} className="projectInventoryRow"><BoardImage src={item.image} alt="" size="tiny" placeholder="INV" /><div><strong>{item.name}</strong><small>{item.inventory_id} · {item.status_label}</small></div><span>{item.quantity}</span></div>)}
          {!project.inventory?.length && <p className="muted">No physical inventory is assigned yet. Assign items from the Inventory page.</p>}
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
    <form onSubmit={upload} className="imageSourceBox"><input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => setFile(e.target.files?.[0] || null)} /><button className="primary" disabled={!file || busy}>Upload cover</button></form>
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
      <label className="full">Image<input type="file" required accept="image/jpeg,image/png,image/webp" onChange={e => setFile(e.target.files?.[0] || null)} /></label>
      <label className="full">Name<input value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="full">Description<textarea rows="3" value={description} onChange={e => setDescription(e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={!file || busy}>{busy ? "Uploading…" : "Add photo"}</button></div>
    </form>
  </Modal>;
}
