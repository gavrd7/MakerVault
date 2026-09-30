import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock, Modal } from "./Common";

function uid(prefix) {
  const value = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  return prefix + "-" + value;
}

function downloadWiringFile(filename, contents, type) {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function safeFilename(value) {
  return String(value || "wiring-diagram").trim().replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "wiring-diagram";
}

function xmlEscape(value) {
  return String(value ?? "").replace(/[<>&"']/g, char => ({
    "<": "&lt;",
    ">": "&gt;",
    "&": "&amp;",
    '"': "&quot;",
    "'": "&apos;",
  }[char]));
}

function referenceRows(type, boards, components, inventory) {
  if (type === "board") return (boards || []).map(row => ({
    id: row.id,
    label: row.display_name || row.name,
    subtitle: [row.family, row.mcu].filter(Boolean).join(" · "),
  }));
  if (type === "component") return (components || []).map(row => ({
    id: row.id,
    label: row.name,
    subtitle: row.category || "",
  }));
  if (type === "inventory") return (inventory || []).map(row => ({
    id: row.id,
    label: row.name || row.display_name || row.inventory_id,
    subtitle: [row.inventory_id, row.status_label].filter(Boolean).join(" · "),
  }));
  return [];
}

export default function ProjectWiringSection({ project, boards, components, inventory, config }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [active, setActive] = useState(null);

  const canAdd = Boolean(config?.permissions?.add_wiring_diagram);
  const canChange = Boolean(config?.permissions?.change_wiring_diagram);
  const canDelete = Boolean(config?.permissions?.delete_wiring_diagram);

  async function load() {
    setLoading(true); setError("");
    try {
      const result = await apiFetch("/api/projects/" + project.id + "/wiring/");
      setRows(result.rows || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [project.id]);

  async function openDiagram(diagram) {
    setError("");
    try {
      const result = await apiFetch("/api/projects/" + project.id + "/wiring/" + diagram.id + "/");
      setActive(result.item);
    } catch (err) {
      setError(err.message);
    }
  }

  async function removeDiagram(diagram) {
    if (!window.confirm('Delete wiring diagram "' + diagram.name + '"?')) return;
    try {
      await apiFetch("/api/projects/" + project.id + "/wiring/" + diagram.id + "/", { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return <section className="projectSection projectWiringSection">
    <div className="projectSectionHead">
      <div><h3>Interactive wiring</h3><p>Structured pin-to-pin wiring diagrams for this project.</p></div>
      <div className="projectSectionActions">
        <span>{rows.length}</span>
        {canAdd && <button type="button" onClick={() => setCreateOpen(true)}>＋ Diagram</button>}
      </div>
    </div>

    {error && <div className="inlineError">{error}</div>}
    {loading ? <LoadingBlock label="Loading wiring diagrams…" /> : <div className="wiringDiagramList">
      {rows.map(diagram => <article className="wiringDiagramCard" key={diagram.id}>
        <div>
          <strong>{diagram.name}</strong>
          <small>{diagram.node_count} node{diagram.node_count === 1 ? "" : "s"} · {diagram.connection_count} connection{diagram.connection_count === 1 ? "" : "s"} · rev {diagram.revision}</small>
          {diagram.description && <p>{diagram.description}</p>}
        </div>
        <div>
          <button type="button" onClick={() => openDiagram(diagram)}>Open editor</button>
          {canDelete && <button type="button" className="assetDanger" onClick={() => removeDiagram(diagram)}>Delete</button>}
        </div>
      </article>)}
      {!rows.length && <div className="projectAssetEmpty">No interactive wiring diagrams yet. Uploaded schematics remain available in Files &amp; assets.</div>}
    </div>}

    {createOpen && <CreateDiagramModal
      project={project}
      onClose={() => setCreateOpen(false)}
      onCreated={async item => { setCreateOpen(false); setActive(item); await load(); }}
    />}

    {active && <WiringEditor
      project={project}
      diagram={active}
      boards={boards}
      components={components}
      inventory={inventory}
      canChange={canChange}
      onClose={async () => { setActive(null); await load(); }}
      onSaved={item => setActive(item)}
    />}
  </section>;
}

function CreateDiagramModal({ project, onClose, onCreated }) {
  const [name, setName] = useState("Main wiring");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const result = await apiFetch("/api/projects/" + project.id + "/wiring/", {
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

  return <Modal title="New wiring diagram" subtitle="Create an editable structured wiring workspace for this project." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">Name<input required value={name} onChange={e => setName(e.target.value)} /></label>
      <label className="full">Description<textarea rows="3" value={description} onChange={e => setDescription(e.target.value)} placeholder="Power, control wiring, sensor bus…" /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create diagram"}</button></div>
    </form>
  </Modal>;
}

function WiringEditor({ project, diagram, boards, components, inventory, canChange, onClose, onSaved }) {
  const [draft, setDraft] = useState(() => ({ ...diagram, nodes: diagram.nodes || [], connections: diagram.connections || [], canvas: diagram.canvas || {} }));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [nodeType, setNodeType] = useState("board");
  const [referenceId, setReferenceId] = useState("");
  const [customLabel, setCustomLabel] = useState("");
  const [connection, setConnection] = useState({ from_node: "", from_pin: "", to_node: "", to_pin: "", label: "", color: "#7c5cff" });
  const [editingConnectionId, setEditingConnectionId] = useState("");
  const [drag, setDrag] = useState(null);
  const canvasRef = useRef(null);

  const refs = useMemo(() => referenceRows(nodeType, boards, components, inventory), [nodeType, boards, components, inventory]);
  useEffect(() => {
    if (nodeType === "custom") return;
    if (!referenceId || !refs.some(row => row.id === referenceId)) setReferenceId(refs[0]?.id || "");
  }, [nodeType, refs.length]);

  function mutate(updater) {
    setDraft(current => updater(current));
    setDirty(true);
  }

  function addNode(event) {
    event.preventDefault();
    if (!canChange) return;
    const ref = refs.find(row => row.id === referenceId);
    const label = nodeType === "custom" ? customLabel.trim() : (customLabel.trim() || ref?.label || "");
    if (!label) return;
    const index = draft.nodes.length;
    const node = {
      id: uid("node"),
      type: nodeType,
      reference_id: nodeType === "custom" ? "" : referenceId,
      label,
      x: 28 + (index % 3) * 220,
      y: 28 + Math.floor(index / 3) * 130,
      notes: "",
      reference: ref ? { label: ref.label, subtitle: ref.subtitle, pin_hints: [] } : undefined,
    };
    mutate(current => ({ ...current, nodes: [...current.nodes, node] }));
    setCustomLabel("");
  }

  function removeNode(nodeId) {
    mutate(current => ({
      ...current,
      nodes: current.nodes.filter(node => node.id !== nodeId),
      connections: current.connections.filter(edge => edge.from_node !== nodeId && edge.to_node !== nodeId),
    }));
  }

  function addConnection(event) {
    event.preventDefault();
    if (!canChange || !connection.from_node || !connection.to_node || !connection.from_pin.trim() || !connection.to_pin.trim()) return;
    const nextEdge = {
      id: editingConnectionId || uid("wire"),
      from_node: connection.from_node,
      from_pin: connection.from_pin.trim(),
      to_node: connection.to_node,
      to_pin: connection.to_pin.trim(),
      label: connection.label.trim(),
      color: connection.color,
      notes: "",
    };
    mutate(current => ({
      ...current,
      connections: editingConnectionId
        ? current.connections.map(edge => edge.id === editingConnectionId ? nextEdge : edge)
        : [...current.connections, nextEdge],
    }));
    setEditingConnectionId("");
    setConnection({ from_node: "", from_pin: "", to_node: "", to_pin: "", label: "", color: "#7c5cff" });
  }

  function editConnection(edge) {
    setEditingConnectionId(edge.id);
    setConnection({
      from_node: edge.from_node,
      from_pin: edge.from_pin,
      to_node: edge.to_node,
      to_pin: edge.to_pin,
      label: edge.label || "",
      color: edge.color || "#7c5cff",
    });
  }

  function cancelConnectionEdit() {
    setEditingConnectionId("");
    setConnection({ from_node: "", from_pin: "", to_node: "", to_pin: "", label: "", color: "#7c5cff" });
  }

  function startDrag(event, node) {
    if (!canChange || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    setDrag({
      id: node.id,
      dx: event.clientX - rect.left + canvasRef.current.scrollLeft - node.x,
      dy: event.clientY - rect.top + canvasRef.current.scrollTop - node.y,
    });
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function moveDrag(event) {
    if (!drag || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1600, event.clientX - rect.left + canvasRef.current.scrollLeft - drag.dx));
    const y = Math.max(0, Math.min(1000, event.clientY - rect.top + canvasRef.current.scrollTop - drag.dy));
    mutate(current => ({
      ...current,
      nodes: current.nodes.map(node => node.id === drag.id ? { ...node, x: Math.round(x), y: Math.round(y) } : node),
    }));
  }

  async function save() {
    setBusy(true); setError("");
    try {
      const result = await apiFetch("/api/projects/" + project.id + "/wiring/" + diagram.id + "/", {
        method: "PATCH",
        body: {
          name: draft.name,
          description: draft.description,
          nodes: draft.nodes.map(({ reference, ...node }) => node),
          connections: draft.connections,
          canvas: draft.canvas,
        },
      });
      setDraft(result.item);
      setDirty(false);
      onSaved(result.item);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function close() {
    if (dirty && !window.confirm("Close without saving wiring changes?")) return;
    onClose();
  }

  const nodeById = Object.fromEntries(draft.nodes.map(node => [node.id, node]));
  const diagnosticByConnection = draft.diagnostic_summary?.connections || {};
  const diagnosticCounts = draft.diagnostic_summary?.counts || {};
  const canvasWidth = Math.max(960, ...draft.nodes.map(node => Number(node.x || 0) + 220));
  const canvasHeight = Math.max(560, ...draft.nodes.map(node => Number(node.y || 0) + 140));

  function exportJson() {
    const payload = {
      format: "makervault-wiring",
      version: 1,
      project: { id: project.id, name: project.name },
      diagram: {
        id: draft.id,
        name: draft.name,
        description: draft.description,
        revision: draft.revision,
        nodes: draft.nodes.map(({ reference, ...node }) => node),
        connections: draft.connections,
        canvas: draft.canvas,
      },
    };
    downloadWiringFile(
      safeFilename(project.name + "-" + draft.name) + ".wiring.json",
      JSON.stringify(payload, null, 2) + "\n",
      "application/json",
    );
  }

  function exportSvg() {
    const pad = 30;
    const width = Math.max(520, canvasWidth + pad * 2);
    const height = Math.max(360, canvasHeight + pad * 2);
    const lines = draft.connections.map(edge => {
      const from = nodeById[edge.from_node];
      const to = nodeById[edge.to_node];
      if (!from || !to) return "";
      const x1 = Number(from.x) + 90 + pad;
      const y1 = Number(from.y) + 42 + pad;
      const x2 = Number(to.x) + 90 + pad;
      const y2 = Number(to.y) + 42 + pad;
      const colour = /^#[0-9a-f]{6}$/i.test(edge.color || "") ? edge.color : "#7c5cff";
      const midX = (x1 + x2) / 2;
      const midY = (y1 + y2) / 2;
      return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${colour}" stroke-width="3" stroke-linecap="round"/>` +
        (edge.label ? `<text x="${midX}" y="${midY - 6}" fill="#4c5563" font-size="12" text-anchor="middle">${xmlEscape(edge.label)}</text>` : "");
    }).join("");

    const nodes = draft.nodes.map(node => {
      const x = Number(node.x) + pad;
      const y = Number(node.y) + pad;
      return `<g><rect x="${x}" y="${y}" width="180" height="84" rx="12" fill="#f7f8fb" stroke="#667085"/><text x="${x + 12}" y="${y + 25}" fill="#667085" font-size="10" font-weight="700">${xmlEscape(node.type.toUpperCase())}</text><text x="${x + 12}" y="${y + 49}" fill="#111827" font-size="14" font-weight="700">${xmlEscape(node.label)}</text></g>`;
    }).join("");

    const svg = `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#ffffff"/><text x="${pad}" y="22" fill="#111827" font-family="system-ui,sans-serif" font-size="16" font-weight="700">${xmlEscape(project.name)} — ${xmlEscape(draft.name)}</text><g font-family="system-ui,sans-serif">${lines}${nodes}</g></svg>`;
    downloadWiringFile(
      safeFilename(project.name + "-" + draft.name) + ".svg",
      svg,
      "image/svg+xml",
    );
  }

  return <div className="wiringEditorBackdrop">
    <section className="wiringEditor">
      <div className="wiringEditorHeader">
        <div>
          <span className="settingsEyebrow">Interactive wiring · {project.name}</span>
          <input className="wiringTitleInput" value={draft.name} disabled={!canChange} onChange={e => { setDraft(current => ({ ...current, name: e.target.value })); setDirty(true); }} />
          <small>Revision {draft.revision} · {draft.nodes.length} nodes · {draft.connections.length} connections</small>
        </div>
        <div className="wiringHeaderActions">
          {dirty && <Badge tone="accent">Unsaved</Badge>}
          <button onClick={exportJson}>Export JSON</button>
          <button onClick={exportSvg}>Export SVG</button>
          {canChange && <button className="primary" disabled={busy || !dirty} onClick={save}>{busy ? "Saving…" : "Save"}</button>}
          <button onClick={close}>Close</button>
        </div>
      </div>

      {error && <div className="wiringEditorError formError">{error}</div>}

      <div className="wiringEditorBody">
        <aside className="wiringToolbox">
          <section>
            <h3>Add node</h3>
            <form onSubmit={addNode}>
              <label>Type<select value={nodeType} disabled={!canChange} onChange={e => { setNodeType(e.target.value); setReferenceId(""); }}>
                <option value="board">Board catalogue</option>
                <option value="component">Component catalogue</option>
                <option value="inventory">Inventory item</option>
                <option value="custom">Custom node</option>
              </select></label>
              {nodeType !== "custom" && <label>Record<select value={referenceId} disabled={!canChange} onChange={e => setReferenceId(e.target.value)}>
                {!refs.length && <option value="">No records available</option>}
                {refs.map(row => <option key={row.id} value={row.id}>{row.label}{row.subtitle ? " · " + row.subtitle : ""}</option>)}
              </select></label>}
              <label>{nodeType === "custom" ? "Label" : "Label override"}<input value={customLabel} disabled={!canChange} onChange={e => setCustomLabel(e.target.value)} placeholder={nodeType === "custom" ? "Power supply, terminal block…" : "Optional"} /></label>
              <button className="primary" disabled={!canChange || (nodeType !== "custom" && !referenceId) || (nodeType === "custom" && !customLabel.trim())}>＋ Add node</button>
            </form>
          </section>

          <section>
            <h3>{editingConnectionId ? "Edit connection" : "Add connection"}</h3>
            <form onSubmit={addConnection}>
              <label>From<select value={connection.from_node} disabled={!canChange} onChange={e => setConnection(current => ({ ...current, from_node: e.target.value }))}><option value="">Choose node…</option>{draft.nodes.map(node => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
              <PinInput label="From pin" node={nodeById[connection.from_node]} value={connection.from_pin} disabled={!canChange} onChange={value => setConnection(current => ({ ...current, from_pin: value }))} listId="wiring-from-pins" />
              <label>To<select value={connection.to_node} disabled={!canChange} onChange={e => setConnection(current => ({ ...current, to_node: e.target.value }))}><option value="">Choose node…</option>{draft.nodes.map(node => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
              <PinInput label="To pin" node={nodeById[connection.to_node]} value={connection.to_pin} disabled={!canChange} onChange={value => setConnection(current => ({ ...current, to_pin: value }))} listId="wiring-to-pins" />
              <label>Label<input value={connection.label} disabled={!canChange} onChange={e => setConnection(current => ({ ...current, label: e.target.value }))} placeholder="I²C SDA, 5V power…" /></label>
              <label>Wire colour<input type="color" value={connection.color} disabled={!canChange} onChange={e => setConnection(current => ({ ...current, color: e.target.value }))} /></label>
              <div className="wiringConnectionFormActions">
                {editingConnectionId && <button type="button" onClick={cancelConnectionEdit}>Cancel</button>}
                <button className="primary" disabled={!canChange || !connection.from_node || !connection.to_node || !connection.from_pin.trim() || !connection.to_pin.trim()}>{editingConnectionId ? "Save connection" : "＋ Connect"}</button>
              </div>
            </form>
          </section>
        </aside>

        <div className="wiringWorkspace">
          <section className="wiringDiagnostics">
            <div className="wiringDiagnosticsHead">
              <div><strong>Circuit checks</strong><small>Rule-based sanity checks use catalogue pin metadata where available.</small></div>
              <div className="wiringDiagnosticCounts">
                <span className="diagError">{diagnosticCounts.error || 0} errors</span>
                <span className="diagWarning">{diagnosticCounts.warning || 0} warnings</span>
                <span className="diagValid">{diagnosticCounts.valid || 0} validated</span>
              </div>
            </div>
            {(draft.diagnostics || []).filter(item => item.severity !== "valid").map((item, index) => <div className={"wiringDiagnostic wiringDiagnostic-" + item.severity} key={item.code + "-" + item.connection_id + "-" + index}>
              <strong>{item.severity === "error" ? "Error" : item.severity === "warning" ? "Warning" : "Check"}</strong>
              <span>{item.message}</span>
            </div>)}
            {draft.connections.length > 0 && !(draft.diagnostics || []).some(item => item.severity !== "valid") && <div className="wiringDiagnostic wiringDiagnostic-valid"><strong>OK</strong><span>No high-confidence electrical conflicts detected in the connections MakerVault can classify.</span></div>}
          </section>
          <div
            className={"wiringCanvasScroll" + (draft.canvas?.show_grid === false ? " noGrid" : "")}
            ref={canvasRef}
            onPointerMove={moveDrag}
            onPointerUp={() => setDrag(null)}
            onPointerCancel={() => setDrag(null)}
          >
            <div className="wiringCanvas" style={{ width: canvasWidth, height: canvasHeight }}>
              <svg className="wiringLines" width={canvasWidth} height={canvasHeight} aria-hidden="true">
                {draft.connections.map(edge => {
                  const from = nodeById[edge.from_node];
                  const to = nodeById[edge.to_node];
                  if (!from || !to) return null;
                  const severity = diagnosticByConnection[edge.id] || "unknown";
                  const x1 = Number(from.x) + 90;
                  const y1 = Number(from.y) + 42;
                  const x2 = Number(to.x) + 90;
                  const y2 = Number(to.y) + 42;
                  const midX = (x1 + x2) / 2;
                  const midY = (y1 + y2) / 2;
                  return <g key={edge.id} className={"wiringLine wiringLine-" + severity}>
                    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={severity === "unknown" ? (edge.color || "#7c5cff") : undefined} strokeWidth="3" />
                    <rect className="wiringLineLabelBg" x={midX - 70} y={midY - 13} width="140" height="26" rx="7" />
                    <text className="wiringLineLabel" x={midX} y={midY - 2} textAnchor="middle">{edge.from_pin} → {edge.to_pin}</text>
                    {edge.label && <text className="wiringLineSubLabel" x={midX} y={midY + 9} textAnchor="middle">{edge.label}</text>}
                  </g>;
                })}
              </svg>
              {draft.nodes.map(node => <div
                className={"wiringNode wiringNode-" + node.type}
                key={node.id}
                style={{ left: node.x, top: node.y }}
                onPointerDown={event => startDrag(event, node)}
              >
                <div className="wiringNodeHead"><span>{node.type}</span>{canChange && <button type="button" title="Remove node" onPointerDown={e => e.stopPropagation()} onClick={() => removeNode(node.id)}>×</button>}</div>
                <strong>{node.label}</strong>
                <small>{node.reference?.subtitle || (node.type === "custom" ? "Custom wiring node" : "Catalogue / inventory reference")}</small>
                {(node.reference?.pins || []).length > 0 && <div className="wiringNodePins">
                  {(node.reference.pins || []).slice(0, 18).map(pin => {
                    const used = draft.connections.some(edge =>
                      (edge.from_node === node.id && edge.from_pin.toLowerCase() === pin.name.toLowerCase()) ||
                      (edge.to_node === node.id && edge.to_pin.toLowerCase() === pin.name.toLowerCase())
                    );
                    return <span className={used ? "used" : ""} key={pin.name}><b>{pin.name}</b>{pin.role && pin.role !== "unknown" ? <em>{pin.role.replaceAll("_", " ")}</em> : null}</span>;
                  })}
                  {node.reference.pins.length > 18 && <small>+{node.reference.pins.length - 18} more pins</small>}
                </div>}
              </div>)}
              {!draft.nodes.length && <div className="wiringCanvasEmpty">Add boards, components, inventory or custom nodes from the toolbox.</div>}
            </div>
          </div>

          <section className="wiringConnectionList">
            <div className="projectSectionHead"><h3>Connections</h3><span>{draft.connections.length}</span></div>
            {draft.connections.map(edge => {
              const severity = diagnosticByConnection[edge.id] || "unknown";
              return <div className={"wiringConnectionRow wiringConnection-" + severity} key={edge.id}>
              <span className="wiringColourDot" style={severity === "unknown" ? { background: edge.color || "#7c5cff" } : undefined} />
              <div>
                <strong>{nodeById[edge.from_node]?.label || edge.from_node} · {edge.from_pin} → {nodeById[edge.to_node]?.label || edge.to_node} · {edge.to_pin}</strong>
                <small>{edge.label || "Unlabelled connection"}</small>
              </div>
              <div className="wiringConnectionActions">
                <span className={"wiringConnectionStatus " + severity}>{severity}</span>
                {canChange && <button type="button" onClick={() => editConnection(edge)}>Edit</button>}
                {canChange && <button type="button" onClick={() => mutate(current => ({ ...current, connections: current.connections.filter(item => item.id !== edge.id) }))}>Remove</button>}
              </div>
            </div>;
            })}
            {!draft.connections.length && <p className="muted">No pin-to-pin connections yet.</p>}
          </section>
        </div>
      </div>
    </section>
  </div>;
}

function PinInput({ label, node, value, onChange, disabled, listId }) {
  const hints = node?.reference?.pin_hints || [];
  return <label>{label}<input list={hints.length ? listId : undefined} value={value} disabled={disabled} onChange={e => onChange(e.target.value)} placeholder="GPIO4, GND, SDA…" />{hints.length > 0 && <datalist id={listId}>{hints.map(pin => <option key={pin} value={pin} />)}</datalist>}</label>;
}
