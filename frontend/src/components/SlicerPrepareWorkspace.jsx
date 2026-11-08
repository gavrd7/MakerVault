import React, { useCallback, useEffect, useRef, useState } from "react";
import SlicerPlateEditor from "./SlicerPlateEditor";

/**
 * Interactive Prepare shell. All slicing still goes through the existing
 * engine-specific, isolated queue. Disabled tools are intentionally visible:
 * none are represented as supported until their model transformation and
 * native format round-trip have been implemented and tested.
 */
const TOOLS = [
  { name: "Add model", target: "import" },
  { name: "Move", target: "x_mm" },
  { name: "Rotate", target: "rotation_deg" },
  { name: "Scale", target: "scale_percent" },
  { name: "Auto-arrange", target: "arrange" },
  { name: "Duplicate", target: "duplicate" },
  { name: "Remove", target: "remove" },
  { name: "Add plate", pending: "Multi-plate project persistence and native plate export" },
  { name: "Auto-orient", pending: "Geometry-based safe orientation solver" },
  { name: "Lay on face", pending: "Mesh face selection and normal alignment" },
  { name: "Split", pending: "Connected-component mesh separation" },
  { name: "Individual XYZ scale", pending: "Nonuniform 3MF transforms and bed clearance" },
  { name: "Hollow", pending: "Watertight offset geometry and drain holes" },
  { name: "Drill", pending: "Validated boolean subtraction" },
  { name: "Cut", pending: "Robust planar mesh cutting" },
  { name: "Mesh boolean", pending: "Robust union, intersection and difference" },
  { name: "Measure", pending: "Face, edge and coordinate measurement" },
  { name: "Support painting", pending: "Native per-face support annotations" },
  { name: "Seam painting", pending: "Native seam-region annotations" },
  { name: "Variable layer height", pending: "Native variable layer representation" },
  { name: "Colour painting", pending: "Native multi-material annotations and tool mapping" },
];
const GROUPS = ["Quality", "Strength", "Speed", "Supports", "Multifilament", "Others"];

export default function SlicerPrepareWorkspace({
  objects, onChange, files, plate, onPrimaryChange, onFilesUploaded,
  defaultColor, onManualColorChange, canEdit, busy, error, notice,
  onBackToSetup, onSaveDraft, onSlice, onSaveAndSlice, engine, printer,
  selectedProfiles, workerConfigured,
}) {
  const editorRef = useRef(null);
  const latest = useRef(objects);
  const undoRef = useRef([]);
  const redoRef = useRef([]);
  const [, setHistoryVersion] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [scope, setScope] = useState("global");
  const [group, setGroup] = useState("Quality");
  latest.current = objects;

  const updatePlate = useCallback(next => {
    const old = latest.current;
    if (JSON.stringify(next) === JSON.stringify(old)) return;
    undoRef.current = [...undoRef.current.slice(-49), old.map(row => ({ ...row }))];
    redoRef.current = [];
    latest.current = next;
    onChange(next);
    if (next[0]?.asset_id !== old[0]?.asset_id) onPrimaryChange?.(next[0]?.asset_id || "");
    setHistoryVersion(value => value + 1);
  }, [onChange, onPrimaryChange]);
  const undo = useCallback(() => {
    if (!undoRef.current.length) return;
    const previous = undoRef.current.pop();
    redoRef.current.push(latest.current.map(row => ({ ...row })));
    const before = latest.current;
    latest.current = previous;
    onChange(previous);
    if (previous[0]?.asset_id !== before[0]?.asset_id) onPrimaryChange?.(previous[0]?.asset_id || "");
    setHistoryVersion(value => value + 1);
  }, [onChange, onPrimaryChange]);
  const redo = useCallback(() => {
    if (!redoRef.current.length) return;
    const next = redoRef.current.pop();
    undoRef.current.push(latest.current.map(row => ({ ...row })));
    const before = latest.current;
    latest.current = next;
    onChange(next);
    if (next[0]?.asset_id !== before[0]?.asset_id) onPrimaryChange?.(next[0]?.asset_id || "");
    setHistoryVersion(value => value + 1);
  }, [onChange, onPrimaryChange]);

  useEffect(() => {
    const listener = event => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const tag = event.target?.tagName?.toLowerCase();
      if (["input", "textarea", "select"].includes(tag) ||
          event.target?.isContentEditable) return;
      if (event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
      } else if (event.key.toLowerCase() === "y") {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [undo, redo]);

  const active = objects.find(row => row.instance_id === selectedId) || objects[0];
  const itemName = object => files.find(file => String(file.id) === String(object.asset_id))
    ?.name || "STL model";
  function selectTool(tool) {
    const el = editorRef.current?.querySelector(
      tool.target === "import" ? 'input[type="file"][accept=".stl"]' :
        tool.target === "arrange" ? '[data-slicer-action="arrange"]' :
          tool.target === "duplicate" ? '[data-slicer-action="duplicate"]' :
            tool.target === "remove" ? '[data-slicer-action="remove"]' :
              '[data-slicer-field="' + tool.target + '"]'
    );
    if (["import", "arrange", "duplicate", "remove"].includes(tool.target)) el?.click();
    else {
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      el?.focus();
    }
  }
  const plateReady = canEdit && !!objects.length && !busy;
  return <section className="panel printingSection slicerPrepareWorkspace"
    aria-label="Interactive slicer Prepare workspace">
    <div className="slicerPrepareHeader">
      <div>
        <span className="settingsEyebrow">MakerVault Slicer · Prepare</span>
        <h3>Interactive model editor</h3>
        <p>Engine: {engine || "Not selected"} · Printer: {printer || "Not selected"} ·
          Native profiles remain engine-specific.</p>
      </div>
      <button type="button" onClick={onBackToSetup}>← Slicer setup</button>
    </div>
    <div className="slicerPrepareTools" role="toolbar" aria-label="Model editing tools">
      <button type="button" disabled={!undoRef.current.length || busy} onClick={undo}
        title="Undo model edit (Ctrl+Z)">Undo</button>
      <button type="button" disabled={!redoRef.current.length || busy} onClick={redo}
        title="Redo model edit (Ctrl+Y)">Redo</button>
      {TOOLS.map(tool => <button key={tool.name} type="button"
        disabled={!!tool.pending || !canEdit || busy || (tool.target !== "import" && !objects.length)}
        title={tool.pending ? "Not implemented: " + tool.pending : tool.name}
        onClick={() => selectTool(tool)}>{tool.name}</button>)}
    </div>
    <div className="slicerPrepareStructure">
      <aside className="slicerPrepareTree" aria-label="Build plate object tree">
        <h4>Plate 1 · Models ({objects.length})</h4>
        {objects.length === 0 && <p>Add an STL to start editing.</p>}
        {objects.map((object, index) => <button key={object.instance_id} type="button"
          className={active?.instance_id === object.instance_id ? "selected" : ""}
          onClick={() => setSelectedId(object.instance_id)}
          aria-pressed={active?.instance_id === object.instance_id}>
          <span style={{ background: object.color }} aria-hidden="true" />
          <span>{index + 1}. {itemName(object)}</span>
        </button>)}
        <small>All instances are editable. Multi-plate output and modifier trees are not implemented yet.</small>
      </aside>
      <div className="slicerPrepareScene" ref={editorRef}>
        <SlicerPlateEditor files={files} objects={objects} onChange={updatePlate}
          onPrimaryChange={onPrimaryChange} onFilesUploaded={onFilesUploaded}
          onManualColorChange={onManualColorChange} defaultColor={defaultColor}
          plate={plate} canEdit={canEdit && !busy} selectedInstanceId={selectedId}
          onSelectedInstanceChange={setSelectedId} />
      </div>
      <aside className="slicerPrepareSettings" aria-label="Process settings categories">
        <h4>Print settings</h4>
        <div className="slicerPrepareScopes" role="group" aria-label="Setting scope">
          <button type="button" className={scope === "global" ? "selected" : ""}
            aria-pressed={scope === "global"} onClick={() => setScope("global")}>Global</button>
          <button type="button" className={scope === "objects" ? "selected" : ""}
            aria-pressed={scope === "objects"} onClick={() => setScope("objects")}>Objects</button>
        </div>
        <nav aria-label="Process settings groups">
          {GROUPS.map(name => <button key={name} type="button"
            className={group === name ? "selected" : ""}
            onClick={() => setGroup(name)}>{name}</button>)}
        </nav>
        <h4>{group}</h4>
        <p>{scope === "global"
          ? "The selected native process profile provides the current global settings."
          : "Per-object overrides require native engine support and are not editable yet."}</p>
        <p><strong>Process:</strong> {selectedProfiles?.process || "Not selected"}</p>
        <p><strong>Filament:</strong> {selectedProfiles?.filament || "Not selected"}</p>
        <p className="projectUploadHint">Native setting editors will appear here after their engine-specific
          schema, inheritance, validation and round-trip tests are ready. Use Slicer setup to edit a profile.</p>
      </aside>
    </div>
    <div className="slicerPrepareActions">
      <div aria-live="polite">
        {error && <p role="alert" className="integrationError">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </div>
      <div className="settingsActions">
        <button type="button" disabled={!plateReady} onClick={onSaveDraft}>Save draft</button>
        <button type="button" disabled={!plateReady || !workerConfigured} onClick={onSlice}>Slice</button>
        <button type="button" className="primary" disabled={!plateReady || !workerConfigured}
          onClick={onSaveAndSlice}>Save and slice</button>
      </div>
    </div>
  </section>;
}
