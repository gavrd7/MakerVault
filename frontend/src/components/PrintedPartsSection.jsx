import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, Modal } from "./Common";

const STATES = { available: "Available", installed: "Installed / in use", spare: "Spare", failed: "Failed", scrapped: "Scrapped", retired: "Retired" };

export default function PrintedPartsSection({ config, projects = [], projectId = "", createJob = null, onCreateConsumed, focusId = "", refreshToken = 0 }) {
  const [rows, setRows] = useState([]);
  const [options, setOptions] = useState(null);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  async function load() {
    try {
      const result = await apiFetch("/api/printing/parts/" + (projectId ? "?project_id=" + projectId : ""));
      setRows(result.rows);
    } catch (err) { setError(err.message); }
  }
  async function open(part = null, job = null) {
    setError("");
    try {
      const [overview, history] = await Promise.all([apiFetch("/api/printing/"), apiFetch("/api/printing/jobs/")]);
      setOptions({ ...overview, jobs: history.rows });
      const current = part ? (await apiFetch(`/api/printing/parts/${part.id}/`)).part : null;
      setEditing({ part: current, job });
    } catch (err) { setError(err.message); }
  }
  useEffect(() => { load(); }, [projectId, refreshToken]);
  useEffect(() => { if (createJob) { open(null, createJob); onCreateConsumed?.(); } }, [createJob?.id]);
  useEffect(() => {
    if (!focusId) return;
    apiFetch(`/api/printing/parts/${focusId}/`).then(result => open(result.part)).catch(err => setError(err.message));
  }, [focusId]);
  const visible = rows.filter(part => (!status || part.status === status) && [part.name, part.model, part.project, part.location].join(" ").toLowerCase().includes(search.toLowerCase()));
  return <section className="panel printingSection" id="printed-parts">
    <div className="panelHead"><div><h3>Printed parts</h3><p>Only parts you choose to keep here. All monitored prints remain in filament analytics.</p></div>
      {config?.permissions?.add_printedpart && <button onClick={() => open()}>＋ Record printed part</button>}
    </div>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="formGrid" style={{ marginBottom: 16 }}>
      <label>Find parts<input value={search} onChange={e => setSearch(e.target.value)} placeholder="Name, model, project or location" /></label>
      <label>Status<select value={status} onChange={e => setStatus(e.target.value)}><option value="">All states</option>{Object.entries(STATES).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
    </div>
    <div className="printingList">{visible.map(part => <article className="printingListRow" key={part.id}>
      <div><strong>{part.name} · {part.quantity}</strong><small>{part.project || "No project"} · {part.location || "No location"}{part.model ? ` · ${part.model} ${part.revision || ""}` : ""}</small></div>
      <Badge tone={part.status === "installed" ? "good" : "neutral"}>{part.status_label}</Badge>
      <button onClick={() => open(part)}>{config?.permissions?.change_printedpart ? "Manage" : "View"}</button>
    </article>)}{!visible.length && <p className="muted">No retained parts match. Successful prints never add parts automatically.</p>}</div>
    {editing && options && <PartModal {...editing} options={options} rows={rows} projects={projects} projectId={projectId} canEditPrintJob={Boolean(config?.permissions?.change_printjob)} canEdit={Boolean(editing.part ? config?.permissions?.change_printedpart : config?.permissions?.add_printedpart)} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); }} />}
  </section>;
}

function PartModal({ part, job, options, rows, projects, projectId, canEditPrintJob, canEdit, onClose, onSaved }) {
  const [form, setForm] = useState({ name: part?.name || job?.model || job?.filename || "", quantity: part?.quantity || 1, status: part?.status || "available", project_id: part?.project_id || projectId || job?.project_id || "", location_id: part?.location_id || "", replaces_id: part?.replaces_id || "", print_job_id: job?.id || "", print_job_quantity: job?.quantity || "", model_revision_id: part?.model_revision_id || "", notes: part?.notes || "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const selected = options.jobs.find(item => item.id === form.print_job_id);
  const production = part?.production || selected;
  const clearFieldError = (...keys) => setFieldErrors(current => {
    const next = { ...current };
    keys.forEach(key => delete next[key]);
    return next;
  });
  const set = (key, value, ...errorKeys) => {
    setForm(current => ({ ...current, [key]: value }));
    clearFieldError(key, ...errorKeys);
  };
  const fieldError = (...keys) => keys.flatMap(key => fieldErrors[key] || []);
  const fieldErrorText = (...keys) => fieldError(...keys).join(" ");
  const fieldInvalid = (...keys) => fieldError(...keys).length > 0;

  async function save(e) {
    e.preventDefault();
    setError("");
    setFieldErrors({});
    if (form.status === "installed" && !form.project_id) {
      setError("Please correct the highlighted fields.");
      setFieldErrors({ project: ["Choose the project where this part is installed."] });
      return;
    }
    setBusy(true);
    try {
      await apiFetch(part ? `/api/printing/parts/${part.id}/` : "/api/printing/parts/", { method: part ? "PATCH" : "POST", body: form });
      await onSaved();
    } catch (err) {
      setError(err.message);
      setFieldErrors(err.fields || {});
    } finally {
      setBusy(false);
    }
  }
  return <Modal title={part ? "Printed part" : "Create printed parts"} onClose={onClose} wide>
    <form onSubmit={save} className="formGrid">
      {error && <div className="error full" role="alert">{error}</div>}
      {!part && <label className="full">Successful print (optional)<select disabled={!canEdit || busy} value={form.print_job_id} onChange={e => {
        const found = options.jobs.find(item => item.id === e.target.value);
        setForm(current => ({ ...current, print_job_id: e.target.value, name: found?.model || found?.filename || current.name, project_id: found?.project_id || current.project_id, model_revision_id: found?.model_revision_id || "", print_job_quantity: found?.quantity || "" }));
      }}><option value="">Existing physical part / no print history link</option>{options.jobs.filter(item => item.status === "success").map(item => <option key={item.id} value={item.id}>{item.model || item.filename || "Unlinked print"} · {item.printer} · {new Date(item.created_at).toLocaleDateString()}</option>)}</select><small>Print tracking and filament usage do not require you to retain a part or save a model.</small></label>}
      {!part && selected && canEditPrintJob && <label className="full">Total items successfully produced by this print<input className={fieldInvalid("print_job_quantity") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("print_job_quantity") || undefined} type="number" min="1" step="1" disabled={!canEdit || busy} value={form.print_job_quantity} onChange={e => set("print_job_quantity", e.target.value)} /><small>Confirm the plate quantity; the retained quantity can be smaller. This updates the print record without multiplying its filament total.</small>{fieldInvalid("print_job_quantity") && <small className="fieldValidationError">{fieldErrorText("print_job_quantity")}</small>}</label>}
      <label>Name<input className={fieldInvalid("name") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("name") || undefined} required maxLength={200} disabled={!canEdit || busy} value={form.name} onChange={e => set("name", e.target.value)} />{fieldInvalid("name") && <small className="fieldValidationError">{fieldErrorText("name")}</small>}</label>
      <label>Quantity<input className={fieldInvalid("quantity") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("quantity") || undefined} required type="number" min="1" step="1" disabled={!canEdit || busy} value={form.quantity} onChange={e => set("quantity", e.target.value)} />{fieldInvalid("quantity") && <small className="fieldValidationError">{fieldErrorText("quantity")}</small>}</label>
      <label>Status<select className={fieldInvalid("status") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("status") || undefined} disabled={!canEdit || busy} value={form.status} onChange={e => set("status", e.target.value)}>{Object.entries(STATES).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select>{fieldInvalid("status") && <small className="fieldValidationError">{fieldErrorText("status")}</small>}</label>
      <label>Project / installation<select className={fieldInvalid("project", "project_id") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("project", "project_id") || undefined} disabled={!canEdit || busy} value={form.project_id} onChange={e => set("project_id", e.target.value, "project")}><option value="">No project</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{fieldInvalid("project", "project_id") && <small className="fieldValidationError">{fieldErrorText("project", "project_id")}</small>}</label>
      <label>Location<select className={fieldInvalid("location", "location_id") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("location", "location_id") || undefined} disabled={!canEdit || busy} value={form.location_id} onChange={e => set("location_id", e.target.value, "location")}><option value="">No location</option>{options.locations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{fieldInvalid("location", "location_id") && <small className="fieldValidationError">{fieldErrorText("location", "location_id")}</small>}</label>
      <label>Replaces (optional)<select className={fieldInvalid("replaces", "replaces_id") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("replaces", "replaces_id") || undefined} disabled={!canEdit || busy} value={form.replaces_id} onChange={e => set("replaces_id", e.target.value, "replaces")}><option value="">No replacement link</option>{rows.filter(item => item.id !== part?.id).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{fieldInvalid("replaces", "replaces_id") && <small className="fieldValidationError">{fieldErrorText("replaces", "replaces_id")}</small>}</label>
      {!part && !form.print_job_id && <label className="full">Model revision (optional)<select className={fieldInvalid("model_revision", "model_revision_id") ? "fieldInvalid" : ""} aria-invalid={fieldInvalid("model_revision", "model_revision_id") || undefined} disabled={!canEdit || busy} value={form.model_revision_id} onChange={e => set("model_revision_id", e.target.value, "model_revision")}><option value="">No saved model</option>{options.models.flatMap(model => model.revisions.map(revision => <option key={revision.id} value={revision.id}>{model.name} · {revision.version}</option>))}</select>{fieldInvalid("model_revision", "model_revision_id") && <small className="fieldValidationError">{fieldErrorText("model_revision", "model_revision_id")}</small>}</label>}
      <label className="full">Notes<textarea disabled={!canEdit || busy} value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      {production && <div className="settingsCallout full"><strong>Production context</strong><p>{production.printer || "Printer not recorded"} · {production.filename || production.model || "Print job"}</p><p>{production.filament_used_g == null ? "Filament not recorded" : `${production.filament_used_g} g${production.filament_usage_estimated ? " estimated" : " recorded"}`} · Whole print job; this is not an allocation to each part.</p>{production.material_cost != null && <p>Material cost: {production.currency || ""} {production.material_cost} for the whole print.</p>}</div>}
      {!!part?.events?.length && <details className="full"><summary>Part history</summary>{part.events.map(event => <p key={event.id}><small>{new Date(event.created_at).toLocaleString()}</small> · {Object.entries(event.changes).map(([key, change]) => `${key}: ${change.to ?? JSON.stringify(change)}`).join("; ")}</p>)}</details>}
      <div className="modalActions full"><button type="button" onClick={onClose}>Close</button>{canEdit && <button className="primary" disabled={busy}>{busy ? "Saving…" : part ? "Save changes" : "Create printed parts"}</button>}</div>
    </form>
  </Modal>;
}
