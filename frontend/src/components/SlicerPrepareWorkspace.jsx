import React, { useCallback, useEffect, useRef, useState } from "react";
import SlicerPlateEditor from "./SlicerPlateEditor";
import SlicerUiIcon from "./SlicerUiIcon";
import { apiFetch } from "../api";

/**
 * Interactive Prepare shell. All slicing still goes through the existing
 * engine-specific, isolated queue. Disabled tools are intentionally visible:
 * none are represented as supported until their model transformation and
 * native format round-trip have been implemented and tested.
 */
const TOOLS = [
  { name: "Add model", target: "import", icon: "add" },
  { name: "Move", target: "x_mm", icon: "move" },
  { name: "Rotate", target: "rotation_deg", icon: "rotate" },
  { name: "Scale", target: "scale_percent", icon: "scale" },
  { name: "Auto-arrange", target: "arrange", icon: "arrange" },
  { name: "Duplicate", target: "duplicate", icon: "duplicate" },
  { name: "Remove", target: "remove", icon: "remove" },
  { name: "Add plate", icon: "add", pending: "Multi-plate project persistence and native plate export" },
  { name: "Auto-orient", icon: "orient", pending: "Geometry-based safe orientation solver" },
  { name: "Lay on face", icon: "face", pending: "Mesh face selection and normal alignment" },
  { name: "Split", icon: "split", pending: "Connected-component mesh separation" },
  { name: "Individual XYZ scale", target: "scale_xyz_percent", icon: "scale" },
  { name: "Hollow", icon: "hollow", pending: "Watertight offset geometry and drain holes" },
  { name: "Drill", icon: "drill", pending: "Validated boolean subtraction" },
  { name: "Cut", icon: "cut", pending: "Robust planar mesh cutting" },
  { name: "Mesh boolean", icon: "boolean", pending: "Robust union, intersection and difference" },
  { name: "Measure", icon: "measure", pending: "Face, edge and coordinate measurement" },
  { name: "Support painting", icon: "paint", pending: "Native per-face support annotations" },
  { name: "Seam painting", icon: "paint", pending: "Native seam-region annotations" },
  { name: "Variable layer height", icon: "layers", pending: "Native variable layer representation" },
  { name: "Colour painting", icon: "paint", pending: "Native multi-material annotations and tool mapping" },
];
const GROUPS = [["Quality", "quality"], ["Strength", "strength"], ["Speed", "speed"],
  ["Supports", "supports"], ["Multifilament", "multifilament"], ["Others", "others"]];

export default function SlicerPrepareWorkspace({
  objects, onChange, files, plate, onPrimaryChange, onFilesUploaded,
  defaultColor, onManualColorChange, canEdit, busy, error, notice,
  onChangeProfiles, onSaveDraft, onSlice, engine, printer,
  selectedProfiles, workerConfigured, printerId,
  localAssets = [], onLocalAssetsChange,
}) {
  const editorRef = useRef(null);
  const latest = useRef(objects);
  const undoRef = useRef([]);
  const redoRef = useRef([]);
  const [, setHistoryVersion] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [scope, setScope] = useState("global");
  const [group, setGroup] = useState("Quality");
  const [toolMode, setToolMode] = useState("select");
  const [liveMaterials, setLiveMaterials] = useState([]);
  const [materialRefreshing, setMaterialRefreshing] = useState(false);
  const [materialMessage, setMaterialMessage] = useState("Select Refresh to read current printer filament slots.");
  const requestRef = useRef(0);
  const refreshPrinterMaterials = useCallback(async () => {
    const requestId = ++requestRef.current;
    if (!printerId) {
      setLiveMaterials([]);
      setMaterialMessage("Choose a printer to view loaded filament slots.");
      return;
    }
    setMaterialRefreshing(true);
    try {
      // Reuse MakerVault's provider-neutral live slot inventory. No printer
      // commands or RFID writes are issued by this operation.
      const data = await apiFetch("/api/printing/?include_filaments=0");
      if (requestId !== requestRef.current) return;
      const selectedPrinter = (data.printers || []).find(p => String(p.id) === String(printerId));
      const loaded = (selectedPrinter?.slots || []).filter(slot => slot.is_loaded);
      setLiveMaterials(loaded);
      setMaterialMessage(loaded.length
        ? "Live slots are informational until native multi-material mapping is implemented."
        : "No loaded slots reported for this printer.");
    } catch (err) {
      if (requestId !== requestRef.current) return;
      setLiveMaterials([]);
      setMaterialMessage(err?.message || "Live printer filament information is unavailable.");
    } finally {
      if (requestId === requestRef.current) setMaterialRefreshing(false);
    }
  }, [printerId]);
  useEffect(() => {
    refreshPrinterMaterials();
    return () => { requestRef.current += 1; };
  }, [refreshPrinterMaterials]);
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

  const active = selectedId ? objects.find(row => row.instance_id === selectedId) : null;
  const itemName = object => {
    const file = [...localAssets, ...files].find(row => String(row.id) === String(object.asset_id));
    return file?.name || file?.filename || "STL model";
  };
  function selectTool(tool) {
    if (tool.target === "x_mm" || tool.target === "rotation_deg") {
      // Selecting a handle-based tool should show its gizmo immediately,
      // including for the first model before it has been explicitly clicked.
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setToolMode(current => current === (tool.target === "x_mm" ? "move" : "rotate")
        ? "select" : (tool.target === "x_mm" ? "move" : "rotate"));
      return;
    }
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
      <button type="button" className="slicerChangeProfiles" onClick={onChangeProfiles}>
        <SlicerUiIcon name="others" /> Change profiles
      </button>
    </div>
    <div className="slicerPrepareTools" role="toolbar" aria-label="Model editing tools">
      <span className="slicerToolTooltip" data-tooltip="Undo · Ctrl+Z">
        <button type="button" disabled={!undoRef.current.length || busy} onClick={undo}
          aria-label="Undo"><SlicerUiIcon name="undo" /></button>
      </span>
      <span className="slicerToolTooltip" data-tooltip="Redo · Ctrl+Y">
        <button type="button" disabled={!redoRef.current.length || busy} onClick={redo}
          aria-label="Redo"><SlicerUiIcon name="redo" /></button>
      </span>
      {TOOLS.map(tool => <span className="slicerToolTooltip" key={tool.name}
        data-tooltip={tool.pending ? tool.name + " · Not yet available: " + tool.pending
          : tool.name}>
        <button type="button"
          className={((tool.target === "x_mm" && toolMode === "move") ||
            (tool.target === "rotation_deg" && toolMode === "rotate")) ? "isActive" : ""}
          aria-pressed={tool.target === "x_mm" || tool.target === "rotation_deg"
            ? (tool.target === "x_mm" ? toolMode === "move" : toolMode === "rotate") : undefined}
          aria-label={tool.name}
          disabled={!!tool.pending || !canEdit || busy || (tool.target !== "import" && !objects.length)}
          onClick={() => selectTool(tool)}><SlicerUiIcon name={tool.icon || "others"} /></button>
      </span>)}
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
        <SlicerPlateEditor files={files} localAssets={localAssets}
          onLocalAssetsChange={onLocalAssetsChange} objects={objects} onChange={updatePlate}
          onPrimaryChange={onPrimaryChange} onFilesUploaded={onFilesUploaded}
          onManualColorChange={onManualColorChange} defaultColor={defaultColor}
          plate={plate} canEdit={canEdit && !busy} toolMode={toolMode} selectedInstanceId={selectedId}
          onSelectedInstanceChange={setSelectedId} onExitToolMode={() => setToolMode("select")} />
      </div>
      <aside className="slicerPrepareSettings" aria-label="Process settings categories">
        <h4>Print settings</h4>
        <div className="slicerPrepareScopes" role="group" aria-label="Setting scope">
          <button type="button" className={scope === "global" ? "selected" : ""}
            aria-pressed={scope === "global"} onClick={() => setScope("global")}>Global</button>
          <button type="button" className={scope === "objects" ? "selected" : ""}
            aria-pressed={scope === "objects"} onClick={() => setScope("objects")}>Object</button>
        </div>
        <nav aria-label="Process settings groups">
          {GROUPS.map(([name, icon]) => <button key={name} type="button"
            className={group === name ? "selected" : ""}
            onClick={() => setGroup(name)}><SlicerUiIcon name={icon} size={16} /><span>{name}</span></button>)}
        </nav>
        <h4>{group}</h4>
        <p>{scope === "global"
          ? "The selected native process profile provides the current global settings."
          : "Object-specific overrides will be available when supported by the selected engine."}</p>
        <p><strong>Printer:</strong> {selectedProfiles?.printer || "Not selected"}</p>
        <p><strong>Process:</strong> {selectedProfiles?.process || "Not selected"}</p>
        <p><strong>Filament:</strong> {selectedProfiles?.filament || "Not selected"}</p>
        <section className="slicerLiveMaterialSlots" aria-label="Loaded printer filament slots">
          <div className="slicerLiveMaterialHeader"><strong>Loaded printer filaments</strong>
            <button type="button" disabled={materialRefreshing || !printerId} onClick={refreshPrinterMaterials}>
              {materialRefreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          {liveMaterials.map(slot => <div className="slicerLiveMaterialSlot" key={slot.id}>
            <span className="slicerLiveMaterialSwatch" style={{ backgroundColor: /^#[0-9a-f]{6}$/i.test(slot.color_hex || "") ? slot.color_hex : "#697b91" }} aria-hidden="true" />
            <div><strong>{slot.product_name || slot.material || "Unknown filament"}</strong>
              <small>{slot.system_label || "Printer material"} · Slot {(slot.slot_index ?? 0) + 1}
                {slot.spool_code ? " · " + slot.spool_code : " · Unlinked spool"}</small>
              <small>{slot.material || "Unknown type"}{slot.remaining_percent != null ? " · " + Math.round(slot.remaining_percent) + "% remaining" : ""}</small>
            </div>
          </div>)}
          <p role="status">{materialMessage}</p>
        </section>
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
        <button type="button" className="primary" disabled={!plateReady || !workerConfigured}
          onClick={onSlice}>Slice and preview</button>
      </div>
    </div>
  </section>;
}
