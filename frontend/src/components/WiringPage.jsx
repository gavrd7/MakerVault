import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { LoadingBlock, Modal } from "./Common";
import { WiringEditor } from "./ProjectWiringSection";

export default function WiringPage({ boards, components, inventory, projects, config, onOpenProject }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [active, setActive] = useState(null);
  const [assigning, setAssigning] = useState(null);

  const canAdd = Boolean(config?.permissions?.add_wiring_diagram);
  const canChange = Boolean(config?.permissions?.change_wiring_diagram);
  const canDelete = Boolean(config?.permissions?.delete_wiring_diagram);

  async function load() {
    setLoading(true); setError("");
    try {
      const result = await apiFetch("/api/wiring/");
      setRows(result.rows || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function openDiagram(row) {
    try {
      const result = await apiFetch("/api/wiring/" + row.id + "/");
      setActive(result.item);
    } catch (err) {
      setError(err.message);
    }
  }

  async function removeDiagram(row) {
    if (!window.confirm('Delete standalone wiring diagram "' + row.name + '"?')) return;
    try {
      await apiFetch("/api/wiring/" + row.id + "/", { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return <section className="wiringLabPage">
    <div className="settingsHero">
      <div>
        <span className="settingsEyebrow">Wiring Lab</span>
        <h2>Experiment before committing to a project</h2>
        <p>Build and validate standalone circuits using MakerVault catalogue data. A finished diagram can be moved into one of your projects later.</p>
      </div>
      {canAdd && <button className="primary" onClick={() => setCreateOpen(true)}>＋ New diagram</button>}
    </div>

    {error && <div className="inlineError">{error}</div>}
    {loading ? <LoadingBlock label="Loading Wiring Lab…" /> : <div className="wiringDiagramList wiringLabList">
      {rows.map(row => <article className="wiringDiagramCard" key={row.id}>
        <div>
          <strong>{row.name}</strong>
          <small>{row.node_count} nodes · {row.connection_count} connections · rev {row.revision}</small>
          {row.description && <p>{row.description}</p>}
        </div>
        <div>
          <button onClick={() => openDiagram(row)}>Open editor</button>
          {canChange && <button onClick={() => setAssigning(row)}>Add to project</button>}
          {canDelete && <button className="assetDanger" onClick={() => removeDiagram(row)}>Delete</button>}
        </div>
      </article>)}
      {!rows.length && <div className="projectAssetEmpty">No standalone diagrams yet. Create one to experiment with boards, components and inventory without creating a project first.</div>}
    </div>}

    {createOpen && <StandaloneCreateModal onClose={() => setCreateOpen(false)} onCreated={async item => { setCreateOpen(false); setActive(item); await load(); }} />}
    {assigning && <AssignProjectModal diagram={assigning} projects={projects} onClose={() => setAssigning(null)} onAssigned={item => { setAssigning(null); load(); onOpenProject?.(item.project_id); }} />}

    {active && <WiringEditor
      diagram={active}
      boards={boards}
      components={components}
      inventory={inventory}
      canChange={canChange}
      endpointBase={"/api/wiring/" + active.id + "/"}
      workspaceName="Wiring Lab"
      onClose={async () => { setActive(null); await load(); }}
      onSaved={item => setActive(item)}
    />}
  </section>;
}

function StandaloneCreateModal({ onClose, onCreated }) {
  const [name, setName] = useState("Experiment");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const result = await apiFetch("/api/wiring/", {
        method: "POST",
        body: { name, description, nodes: [], connections: [], canvas: { show_grid: true, zoom: 1 } },
      });
      onCreated(result.item);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="New Wiring Lab diagram" subtitle="Start independently; you can assign the finished diagram to a project later." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">Name<input required value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="full">Description<textarea rows="3" value={description} onChange={e => setDescription(e.target.value)} placeholder="Prototype, experiment, circuit idea…" /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create diagram"}</button></div>
    </form>
  </Modal>;
}

function AssignProjectModal({ diagram, projects, onClose, onAssigned }) {
  const [projectId, setProjectId] = useState(projects?.[0]?.id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (!projectId) return;
    setBusy(true); setError("");
    try {
      const result = await apiFetch("/api/wiring/" + diagram.id + "/assign-project/", {
        method: "POST",
        body: { project_id: projectId },
      });
      onAssigned(result.item);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add diagram to project" subtitle="The diagram will leave Wiring Lab and become part of the selected project." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">Project<select value={projectId} onChange={e => setProjectId(e.target.value)}>
        {!projects?.length && <option value="">No projects available</option>}
        {(projects || []).map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !projectId}>{busy ? "Moving…" : "Add to project"}</button></div>
    </form>
  </Modal>;
}
