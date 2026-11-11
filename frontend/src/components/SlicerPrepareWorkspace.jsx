import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
  { name: "Centre selected", target: "center", icon: "center" },
  { name: "Fit selected", target: "focus", icon: "focus" },
  { name: "Add plate", icon: "add", pending: "Multi-plate project persistence and native plate export" },
  { name: "Auto-orient", target: "auto_orient", icon: "orient" },
  { name: "Lay on face", target: "lay_face", icon: "face" },
  { name: "Split", target: "split", icon: "split" },
  { name: "Individual XYZ scale", target: "scale_xyz_percent", icon: "scale" },
  { name: "Hollow", icon: "hollow", pending: "Watertight offset geometry and drain holes" },
  { name: "Drill", icon: "drill", pending: "Validated boolean subtraction" },
  { name: "Cut", icon: "cut", pending: "Robust planar mesh cutting" },
  { name: "Mesh boolean", icon: "boolean", pending: "Robust union, intersection and difference" },
  { name: "Measure", target: "measure", icon: "measure", expandable: true },
  { name: "Support painting", icon: "paint", pending: "Native per-face support annotations" },
  { name: "Seam painting", icon: "paint", pending: "Native seam-region annotations" },
  { name: "Variable layer height", icon: "layers", pending: "Native variable layer representation" },
  { name: "Colour painting", icon: "paint", pending: "Native multi-material annotations and tool mapping" },
];
const SECTION_ORDER = {
  Quality: ["Layer height", "Line width", "Seam", "Precision", "Ironing", "Z contouring", "Walls and surfaces", "Overhangs", "Bridging"],
  Strength: ["Walls", "Top/bottom shells", "Infill"],
  Speed: ["First layer speed", "Other layers speed", "Travel speed", "Acceleration"],
  Supports: ["Support", "Raft", "Support ironing", "Tree support", "Advanced"],
  Multifilament: ["Prime tower", "Flush options", "Ooze prevention"],
  Others: ["Skirt", "Brim", "Special mode", "Fuzzy skin", "G-code output"],
};
const GROUPS = [["Quality", "quality"], ["Strength", "strength"], ["Speed", "speed"],
  ["Supports", "supports"], ["Multifilament", "multifilament"], ["Others", "others"]];

export default function SlicerPrepareWorkspace({
  objects, onChange, files, plate, plateType = "default", plateLabel = "Plate 1",
  onPlateLabelChange, onPrimaryChange, onFilesUploaded,
  defaultColor, onManualColorChange, canEdit, busy, error, notice,
  onChangeProfiles, onOpenDevice, onSaveDraft, onSlice, engine, printer,
  selectedProfiles, workerConfigured, printerId,
  processOverrides = {}, onProcessOverridesChange, onSaveCustomProcessProfile,
  processProfiles = [], onSelectProcessProfile, onResetProcessSettings,
  printerDetails, nozzleMm, selectedPlateType = "Native / profile default",
  localAssets = [], onLocalAssetsChange,
}) {
  const editorRef = useRef(null);
  const [sceneHeight, setSceneHeight] = useState(0);
  const latest = useRef(objects);
  const undoRef = useRef([]);
  const redoRef = useRef([]);
  const [, setHistoryVersion] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [selectedIds, setSelectedIds] = useState([]);
  const selectSingle = id => { setSelectedId(id); setSelectedIds(id ? [id] : []); };
  const selectMultiple = (id, additive = false) => {
    const item = objects.find(row => row.instance_id === id);
    if (!item) return;
    if (!additive) {
      const ids = item.assembly_id
        ? objects.filter(row => row.assembly_id === item.assembly_id).map(row => row.instance_id)
        : [id];
      setSelectedIds(ids);
      setSelectedId(id);
      return;
    }
    setSelectedIds(current => {
      const next = current.includes(id) ? current.filter(value => value !== id) : [...current, id];
      setSelectedId(next.at(-1) || "");
      return next;
    });
  };
  const [scope, setScope] = useState("global");
  const [group, setGroup] = useState("Quality");
  const [toolMode, setToolMode] = useState("select");
  const [splitRequest, setSplitRequest] = useState(0);
  const [autoOrientMenuOpen, setAutoOrientMenuOpen] = useState(false);
  const [autoOrientGoal, setAutoOrientGoal] = useState("balanced");
  const [autoOrientRequest, setAutoOrientRequest] = useState(0);
  const [measurementVisible, setMeasurementVisible] = useState(false);
  const [measureOptionsOpen, setMeasureOptionsOpen] = useState(false);
  const [measureMode, setMeasureMode] = useState("distance");
  const [measureUnit, setMeasureUnit] = useState("mm");
  const [measureSnapMode, setMeasureSnapMode] = useState("auto");
  const [measureClearVersion, setMeasureClearVersion] = useState(0);
  const [nativeProcessFields, setNativeProcessFields] = useState({});
  const [settingsSearch, setSettingsSearch] = useState("");
  const [settingsLevel, setSettingsLevel] = useState("basic");
  const [settingsExpanded, setSettingsExpanded] = useState(false);
  const [mobilePane, setMobilePane] = useState("plate");
  const [nativeFieldDrafts, setNativeFieldDrafts] = useState({});
  const [nativeProcessError, setNativeProcessError] = useState("");
  const [nativeProcessLoading, setNativeProcessLoading] = useState(false);
  const [showCustomProfileSave, setShowCustomProfileSave] = useState(false);
  const [customProfileName, setCustomProfileName] = useState("");
  const [customProfileError, setCustomProfileError] = useState("");
  const [savingCustomProfile, setSavingCustomProfile] = useState(false);
  const saveCustomProfile = async event => {
    event.preventDefault();
    if (!onSaveCustomProcessProfile || savingCustomProfile) return;
    setCustomProfileError("");
    setSavingCustomProfile(true);
    try {
      await onSaveCustomProcessProfile(customProfileName);
      setShowCustomProfileSave(false);
      setCustomProfileName("");
      setNativeFieldDrafts({});
    } catch (err) {
      setCustomProfileError(err?.message || "Could not save the custom profile.");
    } finally {
      setSavingCustomProfile(false);
    }
  };
  useEffect(() => {
    const id = selectedProfiles?.process_id;
    if (!id || !String(engine || "").startsWith("orcaslicer ")) {
      setNativeProcessFields({});
      setNativeProcessError("");
      return undefined;
    }
    let live = true;
    setNativeFieldDrafts({});
    setNativeProcessLoading(true);
    setNativeProcessError("");
    apiFetch("/api/printing/slicer/profiles/" + id + "/settings/")
      .then(result => { if (live) setNativeProcessFields(result.fields || {}); })
      .catch(err => {
        if (live) {
          setNativeProcessFields({});
          setNativeProcessError(err?.message || "Native process settings could not be inspected.");
        }
      })
      .finally(() => { if (live) setNativeProcessLoading(false); });
    return () => { live = false; };
  }, [engine, selectedProfiles?.process_id]);
  const selectedObject = objects.find(row => row.instance_id === selectedId) || null;
  const objectOverrides = selectedObject?.process_overrides || {};
  const editingObject = scope === "objects";
  const editingOverrides = editingObject ? objectOverrides : processOverrides;
  const inheritedValue = (key, spec) => processOverrides[key] ?? spec.current;
  const changeEditingOverrides = updater => {
    if (editingObject) {
      if (!selectedObject) return;
      updatePlate(latest.current.map(item => {
        if (item.instance_id !== selectedObject.instance_id) return item;
        const changed = updater(item.process_overrides || {});
        const { process_overrides: _old, ...rest } = item;
        return Object.keys(changed).length ? { ...rest, process_overrides: changed } : rest;
      }));
    } else onProcessOverridesChange?.(updater);
  };
  useEffect(() => { setNativeFieldDrafts({}); }, [scope, selectedId]);
  const updateNativeChoice = (key, value) => {
    const spec = nativeProcessFields[key];
    if (!spec?.options?.some(option => option.value === value)) return;
    changeEditingOverrides(current => {
      const next = { ...current };
      if (value === String(editingObject ? inheritedValue(key, spec) : spec.current)) delete next[key];
      else next[key] = value;
      return next;
    });
  };
  const updateNativeField = (key, raw) => {
    const spec = nativeProcessFields[key];
    setNativeFieldDrafts(current => ({ ...current, [key]: raw }));
    const value = Number(raw);
    if (!spec || raw === "" || !Number.isFinite(value) ||
        value < spec.minimum || value > spec.maximum ||
        (spec.integer && !Number.isInteger(value))) return;
    changeEditingOverrides(current => {
      const next = { ...current };
      if (value === Number(editingObject ? inheritedValue(key, spec) : spec.current)) delete next[key];
      else next[key] = value;
      return next;
    });
  };
  const resetSettings = () => {
    if (editingObject) {
      changeEditingOverrides(() => ({}));
    } else onResetProcessSettings?.();
    setNativeFieldDrafts({});
    setShowCustomProfileSave(false);
    setCustomProfileError("");
  };
  const visibleNativeFields = Object.entries(nativeProcessFields)
    .filter(([key, spec]) => {
      const conditions = spec.enabled_when
        ? (Array.isArray(spec.enabled_when) ? spec.enabled_when : [spec.enabled_when])
        : [];
      const enabled = conditions.every(condition => {
        const master = nativeProcessFields[condition.key];
        if (!master) return true; // A missing native control must never be fabricated.
        const value = String(editingOverrides[condition.key] ?? (editingObject ? inheritedValue(condition.key, master) : master.current));
        if (condition.not !== undefined && value === condition.not) return false;
        if (Array.isArray(condition.in) && !condition.in.includes(value)) return false;
        return true;
      });
      if (!enabled) return false;
      return (settingsLevel === "expert" ||
              (settingsLevel === "advanced" && spec.level !== "expert") ||
              spec.level === "basic") &&
        (settingsSearch.trim()
          ? (key + " " + spec.label + " " + spec.category + " " + (spec.section || ""))
            .toLowerCase().includes(settingsSearch.trim().toLowerCase())
          : spec.category === group);
    })
    // Keep the controlling setting above its dependents regardless of the
    // order in which the backend schema declares numeric and choice fields.
    .sort(([a, sa], [b, sb]) => {
      const depKeys = spec => (Array.isArray(spec.enabled_when)
        ? spec.enabled_when : spec.enabled_when ? [spec.enabled_when] : [])
        .map(condition => condition.key);
      if (depKeys(sb).includes(a)) return -1;
      if (depKeys(sa).includes(b)) return 1;
      return 0;
    });
  const nativeSections = [...new Set(visibleNativeFields.map(([, spec]) => spec.section || "Other"))]
    .sort((a, b) => {
      const order = SECTION_ORDER[group] || [];
      const rank = section => order.includes(section) ? order.indexOf(section) : order.length;
      return rank(a) - rank(b) || a.localeCompare(b);
    });
  const [liveMaterials, setLiveMaterials] = useState([]);
  const [filamentPickerId, setFilamentPickerId] = useState("");
  const [filamentNotice, setFilamentNotice] = useState("");
  const validSlotColor = slot => /^#[0-9a-f]{6}$/i.test(slot?.color_hex || "")
    ? slot.color_hex.toUpperCase() : null;
  const slotName = slot => (slot.product_name || slot.material || "Unknown filament") +
    " · " + (slot.system_label || "Printer") + " slot " + ((slot.slot_index ?? 0) + 1);
  const changeModelPreviewFilament = (instanceId, slot) => {
    const hex = validSlotColor(slot);
    if (!hex) {
      setFilamentNotice("This loaded slot has no valid recorded colour. No change was made.");
      return;
    }
    updatePlate(latest.current.map(item => item.instance_id === instanceId
      ? { ...item, color: hex } : item));
    onManualColorChange?.(instanceId);
    setFilamentPickerId("");
    setFilamentNotice("Preview colour set from " + slotName(slot) +
      ". The actual sliced material still comes from the global native filament profile.");
  };
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

  const validSelection = selectedIds.filter(id => objects.some(row => row.instance_id === id));
  const selectedModels = objects.filter(row => validSelection.includes(row.instance_id));
  const activeAssembly = selectedModels.length > 0 && selectedModels.every(row =>
    row.assembly_id && row.assembly_id === selectedModels[0].assembly_id)
    ? selectedModels[0].assembly_id : "";
  function assembleSelected() {
    if (!canEdit || busy || selectedModels.length < 2) return;
    // Logical groups preserve original STL sources and object settings.
    const id = "assembly:" + (typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID() : Math.random().toString(36).slice(2));
    updatePlate(objects.map(row => validSelection.includes(row.instance_id)
      ? { ...row, assembly_id: id } : row));
  }
  function disassembleSelected() {
    if (!canEdit || busy || !activeAssembly) return;
    updatePlate(objects.map(row => row.assembly_id === activeAssembly
      ? { ...row, assembly_id: null } : row));
  }
  const active = selectedId ? objects.find(row => row.instance_id === selectedId) : null;
  const itemName = object => {
    const file = [...localAssets, ...files].find(row => String(row.id) === String(object.asset_id));
    return file?.name || file?.filename || "STL model";
  };
  function selectTool(tool) {
    if (tool.target === "measure") {
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setToolMode("select");
      if (measurementVisible) {
        setMeasureOptionsOpen(current => !current);
      } else {
        setMeasurementVisible(true);
        setMeasureOptionsOpen(true);
      }
      return;
    }
    setMeasurementVisible(false);
    setMeasureOptionsOpen(false);
    if (tool.target === "auto_orient") {
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setAutoOrientMenuOpen(current => !current);
      setMobilePane("plate");
      return;
    }
    setAutoOrientMenuOpen(false);
    if (tool.target === "split") {
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setToolMode("select");
      setSplitRequest(value => value + 1);
      setMobilePane("plate");
      return;
    }
    if (tool.target === "lay_face") {
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setToolMode(current => current === "lay_face" ? "select" : "lay_face");
      return;
    }
    if (["x_mm", "rotation_deg", "scale_percent", "scale_xyz_percent"].includes(tool.target)) {
      // Selecting a handle-based tool should show its gizmo immediately,
      // including for the first model before it has been explicitly clicked.
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      const next = tool.target === "x_mm" ? "move" :
        tool.target === "rotation_deg" ? "rotate" : "scale";
      setToolMode(current => current === next ? "select" : next);
      return;
    }
    const el = editorRef.current?.querySelector(
      tool.target === "import" ? 'input[type="file"][accept=".stl,.3mf"]' :
        tool.target === "arrange" ? '[data-slicer-action="arrange"]' :
        tool.target === "center" ? '[data-slicer-action="center"]' :
        tool.target === "focus" ? '[data-slicer-action="focus"]' :
          tool.target === "duplicate" ? '[data-slicer-action="duplicate"]' :
            tool.target === "remove" ? '[data-slicer-action="remove"]' :
              '[data-slicer-field="' + tool.target + '"]'
    );
    if (["import", "arrange", "duplicate", "remove", "center", "focus"].includes(tool.target)) el?.click();
    else {
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      el?.focus();
    }
  }
  const plateReady = canEdit && !!objects.length && !busy;
  const profilesReady = ["printer", "process", "filament"].every(
    kind => selectedProfiles?.[kind + "_id"]);
  const draftBlockReason = !canEdit
    ? "Your account cannot prepare slicing drafts."
    : busy ? "The slicer is still loading or processing a request."
    : !objects.length ? "Add a model to the build plate first."
    : !profilesReady ? "Select native printer, process and filament profiles in Slicer setup."
    : "";
  // Matches the bounded keys proven by the pinned Orca 2.4.2 real-binary
  // two-object G-code fixture. Object edits outside this set remain draft-only.
  const verifiedObjectSettings = new Set(["wall_loops", "sparse_infill_density"]);
  const objectSettingsPending = objects.some(item =>
    Object.keys(item.process_overrides || {}).some(key => !verifiedObjectSettings.has(key))
  );
  const sliceBlockReason = draftBlockReason ||
    (objectSettingsPending
      ? "Some Object settings are not yet verified for slicing. Wall loops and sparse infill density are supported; other Object overrides can be saved in drafts but cannot be sliced yet."
      : !workerConfigured
        ? "The selected slicing engine is not available in the verified worker. Check engine installations or choose an installed engine."
        : "");
  useEffect(() => {
    if (!settingsExpanded) return undefined;
    const closeOnEscape = event => {
      if (event.key === "Escape") setSettingsExpanded(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [settingsExpanded]);

  // Match the scroll limit to the actual adjacent visual build-plate panel.
  // Responsive changes and expandable model controls can alter its height.
  useEffect(() => {
    const scene = editorRef.current;
    if (!scene) return undefined;
    const updateHeight = () => {
      const measured = Math.round(scene.getBoundingClientRect().height);
      if (measured > 0) setSceneHeight(previous => previous === measured ? previous : measured);
    };
    updateHeight();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateHeight);
      return () => window.removeEventListener("resize", updateHeight);
    }
    const observer = new ResizeObserver(updateHeight);
    observer.observe(scene);
    return () => observer.disconnect();
  }, []);

  const settingsPanel = (
      <aside id="slicer-prepare-settings" className={"slicerPrepareSettings" + (settingsExpanded ? " slicerPrepareSettingsExpanded" : "")}
        style={!settingsExpanded && sceneHeight ? { maxHeight: sceneHeight + "px" } : undefined}
        aria-label="Process settings categories">
        <div className="slicerSettingsPanelHeader">
          <div><h4>Print settings</h4><small>{selectedProfiles?.process || "Choose a process profile"}</small></div>
        </div>
        <div className="slicerProcessQuickSelect">
          <label htmlFor="slicer-process-quick-select">Process profile</label>
          <div className="slicerProcessQuickSelectRow">
            <select id="slicer-process-quick-select"
              value={selectedProfiles?.process_id || ""}
              disabled={!canEdit || busy || savingCustomProfile || !processProfiles.length}
              onChange={event => {
                setNativeFieldDrafts({});
                setShowCustomProfileSave(false);
                onSelectProcessProfile?.(event.target.value);
              }}>
              {!processProfiles.some(profile => profile.id === selectedProfiles?.process_id) &&
                <option value="">Choose a process profile</option>}
              {processProfiles.map(profile => <option key={profile.id} value={profile.id}>
                {profile.name}{profile.status === "candidate" ? " · Unverified" : ""}
              </option>)}
            </select>
            <button type="button" disabled={!canEdit || busy ||
              !Object.keys(editingOverrides).length} onClick={resetSettings}
              title="Discard this draft's changes and restore values from the selected process profile">
              Reset edits
            </button>
          </div>
          <small>{Object.keys(processOverrides).length
            ? Object.keys(processOverrides).length + " unsaved setting change(s) from " + (selectedProfiles?.process || "selected profile")
            : "Showing the selected native process preset without overrides."}</small>
        </div>
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
        <h4>{settingsSearch.trim() ? "Search results" : group}</h4>
        <div className="slicerSettingsSearchRow">
          <label className="slicerSettingsSearchLabel">
            <span>Find a setting</span>
            <input type="search" value={settingsSearch}
              placeholder="Search native process settings"
              onChange={event => setSettingsSearch(event.target.value)} />
          </label>
          <label className="slicerSettingsLevelLabel">
            <span>Detail</span>
            <select value={settingsLevel} onChange={event => setSettingsLevel(event.target.value)}>
              <option value="basic">Simple</option>
              <option value="advanced">Advanced</option>
              <option value="expert">Expert</option>
            </select>
          </label>
          <button className="slicerExpandSettingsAction" type="button"
            aria-haspopup="dialog" aria-expanded={settingsExpanded}
            onClick={() => setSettingsExpanded(current => !current)}>
            {settingsExpanded ? "Close expanded settings" : "Expand settings"}
          </button>
        </div>
        {editingObject && <div className="slicerObjectSettingsInfo">
          <label htmlFor="slicer-object-settings-instance">Selected object</label>
          <select id="slicer-object-settings-instance" value={selectedObject?.instance_id || ""}
            onChange={event => setSelectedId(event.target.value)}>
            {!selectedObject && <option value="">Select a model</option>}
            {objects.map(item => <option key={item.instance_id} value={item.instance_id}>
              {itemName(item)}
            </option>)}
          </select>
          <small>Object overrides inherit Global values unless changed.
            Wall loops and sparse infill density have passed native Orca 2.4.2 slicing tests.
            Other Object settings can be saved in drafts but remain unavailable for slicing until verified.</small>
        </div>}
        <section aria-label={group + " native process controls"} className="slicerNativeSettingsFields">
            {nativeProcessLoading && <p role="status">Reading native process settings…</p>}
            {nativeProcessError && <p role="alert" className="integrationError">{nativeProcessError}</p>}
            {nativeSections.map(section => (
              <div key={section} className="slicerNativeSettingSection">
                <h5>{section}</h5>
                {visibleNativeFields.filter(([, spec]) => (spec.section || "Other") === section)
                  .map(([key, spec]) => (
                  <label key={key} className="slicerNativeSettingField">
                    <span>{spec.label} {spec.unit ? "(" + spec.unit + ")" : ""}
                      {settingsSearch.trim() && <small> · {spec.category}</small>}
                      {editingOverrides[key] !== undefined && <small className="slicerSettingModified">Modified</small>}
                    </span>
                    {spec.kind === "toggle" ? (
                      <input type="checkbox" aria-label={spec.label}
                        disabled={!canEdit || busy || (editingObject && !selectedObject)}
                        checked={String(editingOverrides[key] ?? (editingObject ? inheritedValue(key, spec) : spec.current)) === "1"}
                        onChange={event => updateNativeChoice(key, event.target.checked ? "1" : "0")} />
                    ) : spec.options ? (
                      <select aria-label={spec.label}
                        disabled={!canEdit || busy || (editingObject && !selectedObject)}
                        value={editingOverrides[key] ?? (editingObject ? inheritedValue(key, spec) : spec.current)}
                        onChange={event => updateNativeChoice(key, event.target.value)}>
                        {spec.options.map(option =>
                          <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    ) : (
                      <input type="number" min={spec.minimum} max={spec.maximum}
                        step={spec.integer ? 1 : 0.01}
                        disabled={!canEdit || busy || (editingObject && !selectedObject)}
                        value={nativeFieldDrafts[key] ?? editingOverrides[key] ?? (editingObject ? inheritedValue(key, spec) : spec.current)}
                        onChange={event => updateNativeField(key, event.target.value)}
                        onBlur={() => setNativeFieldDrafts(current => {
                          const next = { ...current };
                          delete next[key];
                          return next;
                        })}
                        aria-label={spec.label} />
                    )}
                  </label>
                ))}
              </div>
            ))}
            {visibleNativeFields.length === 0 &&
              !nativeProcessLoading && !nativeProcessError && <p>
                {group === "Multifilament"
                  ? "Multicolour tool mappings and flushing volumes require engine-native multi-material support."
                  : "No matching supported native settings are available. Try Advanced or another search."}
              </p>}
            {Object.keys(editingOverrides).length > 0 && <div className="slicerNativeSettingsActions">
              <span>{Object.keys(editingOverrides).length} {editingObject ? "object" : "global"} draft override(s) · Original profile unchanged</span>
              <div className="slicerNativeSettingsButtons">
                {!editingObject && <button type="button" disabled={!canEdit || busy || savingCustomProfile || !onSaveCustomProcessProfile}
                  onClick={() => {
                    setCustomProfileName((selectedProfiles?.process || "Custom process") + " - Custom");
                    setCustomProfileError("");
                    setShowCustomProfileSave(true);
                  }}>Save as custom profile</button>}
                <button type="button" disabled={!canEdit || busy || savingCustomProfile}
                  onClick={resetSettings}>
                  {editingObject ? "Clear object overrides" : "Restore profile defaults"}
                </button>
              </div>
            </div>}
            {!editingObject && showCustomProfileSave && Object.keys(processOverrides).length > 0 && <form
              className="slicerCustomProcessForm" onSubmit={saveCustomProfile}
              aria-label="Save custom process profile">
              <label htmlFor="slicer-custom-process-name">Custom profile name</label>
              <input id="slicer-custom-process-name" type="text"
                maxLength={200} required value={customProfileName}
                disabled={savingCustomProfile || busy}
                onChange={event => setCustomProfileName(event.target.value)}
                placeholder="e.g. 0.16mm Quality - PLA" />
              <small>The original profile will remain unchanged. The new profile is saved under this slicer engine and version.</small>
              {customProfileError && <p className="integrationError" role="alert">{customProfileError}</p>}
              <div className="slicerNativeSettingsButtons">
                <button type="submit" disabled={!canEdit || busy || savingCustomProfile ||
                  !customProfileName.trim()}>
                  {savingCustomProfile ? "Saving…" : "Save and select profile"}
                </button>
                <button type="button" disabled={savingCustomProfile} onClick={() => setShowCustomProfileSave(false)}>
                  Cancel
                </button>
              </div>
            </form>}
          </section>
        <p><strong>Printer:</strong> {selectedProfiles?.printer || "Not selected"}</p>
        <p><strong>Process:</strong> {selectedProfiles?.process || "Not selected"}</p>
        <p><strong>Filament:</strong> {selectedProfiles?.filament || "Not selected"}</p>
        <p className="projectUploadHint">Settings change only this draft and are validated by the native slicer.
          Other native process options remain available through custom profiles in Slicer setup.
          Printer startup and purge G-code are never changed here.</p>
      </aside>
  );
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
      {TOOLS.map(tool => <div className={"slicerToolTooltip" + (((tool.expandable && measureOptionsOpen) || (tool.target === "auto_orient" && autoOrientMenuOpen)) ? " slicerToolOptionsOpen" : "")} key={tool.name}
        data-tooltip={tool.pending ? tool.name + " · Not yet available: " + tool.pending
          : tool.expandable ? tool.name + " · Click for measurement options" : tool.name}>
        <button type="button"
          className={((tool.target === "x_mm" && toolMode === "move") ||
            (tool.target === "rotation_deg" && toolMode === "rotate") ||
            ((tool.target === "scale_percent" || tool.target === "scale_xyz_percent") && toolMode === "scale") ||
            (tool.target === "measure" && measurementVisible) ||
            (tool.target === "lay_face" && toolMode === "lay_face") ||
            (tool.target === "auto_orient" && autoOrientMenuOpen)) ? "isActive" : ""}
          aria-pressed={tool.target === "measure" ? measurementVisible :
            tool.target === "lay_face" ? toolMode === "lay_face" :
            tool.target === "auto_orient" ? autoOrientMenuOpen :
            ["x_mm", "rotation_deg", "scale_percent", "scale_xyz_percent"].includes(tool.target)
            ? (tool.target === "x_mm" ? toolMode === "move"
              : tool.target === "rotation_deg" ? toolMode === "rotate" : toolMode === "scale") : undefined}
          aria-label={tool.name}
          aria-expanded={tool.target === "auto_orient" ? autoOrientMenuOpen : tool.expandable ? measureOptionsOpen : undefined}
          aria-controls={tool.target === "auto_orient" ? "slicer-auto-orient-toolbar-options" : tool.expandable ? "slicer-measure-toolbar-options" : undefined}
          disabled={!!tool.pending || !canEdit || busy || (tool.target !== "import" && !objects.length)}
          onClick={() => selectTool(tool)}><SlicerUiIcon name={tool.icon || "others"} /></button>
        {tool.target === "auto_orient" && autoOrientMenuOpen && <div className="slicerToolOptions slicerAutoOrientMenu" id="slicer-auto-orient-toolbar-options" role="group" aria-label="Auto-orient choices">
          <div className="slicerToolOptionsHeader"><strong>Auto-orient</strong><button type="button" onClick={() => setAutoOrientMenuOpen(false)}>Close</button></div>
          {[
            ["balanced", "Balanced", "Balance estimated time, material, support need and failure risk"],
            ["supports", "Fewest supports", "Prefer orientations with less unsupported geometry"],
            ["speed", "Fastest print", "Prioritise estimated print time and model height"],
          ].map(([goal, name, description]) => <button key={goal} type="button" className="slicerAutoOrientMenuChoice"
            title={description} onClick={() => {
              setAutoOrientGoal(goal);
              setAutoOrientRequest(request => request + 1);
              setAutoOrientMenuOpen(false);
            }}><strong>{name}</strong><span aria-hidden="true">ⓘ</span></button>)}
          <small>Hover over ⓘ or a choice for details. Compare results before applying.</small>
        </div>}
        {tool.expandable && measureOptionsOpen && <div className="slicerToolOptions" id="slicer-measure-toolbar-options"
          role="group" aria-label="Measure tool options">
          <div className="slicerToolOptionsHeader"><strong>Measure</strong>
            <button type="button" aria-label="Hide Measure options" onClick={() => setMeasureOptionsOpen(false)}>Hide</button>
          </div>
          <label>Measurement mode
            <select value={measureMode} onChange={event => setMeasureMode(event.target.value)}>
              <option value="distance">Two-point distance</option>
              <option value="circle">Three-point circle</option>
              <option value="detect">Auto-detect mesh edge / face</option>
            </select>
          </label>
          <label>Snapping
            <select value={measureSnapMode} onChange={event => setMeasureSnapMode(event.target.value)}>
              <option value="auto">Automatic · nearby vertex or triangle edge</option>
              <option value="vertex">Vertex only · otherwise surface</option>
              <option value="edge">Triangle edge only · otherwise surface</option>
              <option value="surface">Surface point · no snapping</option>
            </select>
          </label>
          <label>Units
            <select value={measureUnit} onChange={event => setMeasureUnit(event.target.value)}>
              <option value="mm">Millimetres (mm)</option>
              <option value="in">Inches (in)</option>
            </select>
          </label>
          <button type="button" className="slicerToolOptionsAction" onClick={() => setMeasureClearVersion(value => value + 1)}>
            Clear pins
          </button>
          <small>{measureMode === "detect"
            ? "Click a feature to identify a sharp STL edge segment or connected planar patch. Values are mesh estimates, not original CAD dimensions."
            : "Click the model to place pins. Results appear in the top-left of the 3D view."}</small>
          <button type="button" className="slicerToolOptionsAction" onClick={() => {
            setMeasureOptionsOpen(false);
            setMeasurementVisible(false);
          }}>Finish measuring</button>
        </div>}
      </div>)}
    </div>
    <nav className="slicerMobilePaneTabs" role="tablist" aria-label="Mobile slicer workspace">
      {[
        ["plate", "Build", "slicer-prepare-plate"],
        ["models", "Printer & Filament", "slicer-prepare-models"],
        ["settings", "Print Settings", "slicer-prepare-settings"],
      ].map(([key, label, target]) => <button key={key} id={`slicer-mobile-tab-${key}`}
        type="button" role="tab" aria-selected={mobilePane === key}
        aria-controls={target} className={mobilePane === key ? "selected" : ""}
        onClick={() => setMobilePane(key)} title={label}>
        <SlicerUiIcon name={key === "models" ? "printer" : key} size={18} />
        <span className="slicerMobileTabLabel">{label}</span>
      </button>)}
    </nav>
    <div className="slicerPrepareStructure" data-mobile-pane={mobilePane}>
      <div id="slicer-prepare-models" className="slicerPrepareLeftRail" aria-labelledby="slicer-mobile-tab-models">
        <section className="slicerPreparePrinter" aria-label="Selected printer configuration">
          <span className="slicerPreparePrinterCaption">Printer</span>
          <div className="slicerPreparePrinterIdentity">
            {((printerDetails?.multi_material_installed && printerDetails?.catalogue?.image_multi_material)
              || printerDetails?.catalogue?.image) ? (
              <img src={(printerDetails.multi_material_installed && printerDetails.catalogue.image_multi_material)
                || printerDetails.catalogue.image}
                alt={printerDetails?.catalogue?.display_name || printerDetails?.model || "Selected printer"}
                loading="lazy" />
            ) : (
              <span className="slicerPreparePrinterFallback" aria-hidden="true">
                <svg viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="2.4">
                  <path d="M11 13h42v40H11zM19 22h26M16 45h32M32 22v20M21 45l6-7h10l6 7" />
                  <path d="M32 27l-5 7h10zM7 56h50" />
                </svg>
              </span>
            )}
            <strong>{printerDetails?.name || printer || "No printer selected"}</strong>
          </div>
          <div className="slicerPreparePrinterMeta">
            <span>Nozzle: {nozzleMm ? Number(nozzleMm).toFixed(2) + " mm" : "Not selected"}</span>
            <span>Build plate: {selectedPlateType}</span>
            <span>Build area: {Array.isArray(plate?.size_mm)
              ? plate.size_mm.slice(0, 2).join(" × ") + " mm" : "Unknown"}</span>
          </div>
          <span className="slicerPreparePrinterProfile">{selectedProfiles?.printer || "Native printer profile not selected"}</span>
          <button type="button" onClick={onChangeProfiles}>Change printer/profile</button>
          <button type="button" onClick={() => onOpenDevice?.(printerId)}
            disabled={!printerId || !onOpenDevice}
            title={printerId ? "Open this printer's live monitoring in 3D Printing" : "Select a physical printer first"}>
            Device
          </button>
        </section>
        <aside className="slicerPrepareTree" aria-label="Build plate object tree">
        <h4>{plateLabel || "Plate 1"} · Models ({objects.length})</h4>
        {objects.length === 0 && <p>Add an STL to start editing.</p>}
        {objects.length > 0 && <div className="slicerAssemblyActions">
          <small>{validSelection.length} selected · Ctrl/Cmd-click to select several models.
            Click an assembled object to select its group.</small>
          <div>
            <button type="button" disabled={!canEdit || busy || selectedModels.length < 2}
              onClick={assembleSelected}>Assemble selection</button>
            <button type="button" disabled={!canEdit || busy || !activeAssembly}
              onClick={disassembleSelected}>Disassemble</button>
          </div>
        </div>}
        {objects.map((object, index) => <div className="slicerPrepareModelEntry" key={object.instance_id}>
          <button type="button"
            className={validSelection.includes(object.instance_id) ? "selected" : ""}
            onClick={event => selectMultiple(object.instance_id, event.ctrlKey || event.metaKey || event.shiftKey)}
            aria-pressed={validSelection.includes(object.instance_id)}>
            <span className="slicerPrepareModelSwatch"
              style={{ background: object.color }} aria-hidden="true" />
            <span>{index + 1}. {itemName(object)}</span>
          </button>
          <button type="button" className="slicerModelChangeFilament"
            disabled={!canEdit || busy || !liveMaterials.length}
            aria-expanded={filamentPickerId === object.instance_id}
            onClick={() => {
              setSelectedId(object.instance_id);
              setFilamentPickerId(current => current === object.instance_id ? "" : object.instance_id);
              setFilamentNotice("");
            }}>Change filament</button>
          {filamentPickerId === object.instance_id && <div className="slicerModelFilamentChoices">
            <strong>Loaded filaments · preview colour only</strong>
            {liveMaterials.map(slot => <button type="button" key={slot.id}
              disabled={!canEdit || busy || !validSlotColor(slot)}
              onClick={() => changeModelPreviewFilament(object.instance_id, slot)}>
              <span className="slicerLiveMaterialSwatch"
                style={{ backgroundColor: validSlotColor(slot) || "#697b91" }} aria-hidden="true" />
              <span>{slotName(slot)}</span>
            </button>)}
            <small>Changing this swatch does not assign an extruder, modify G-code or change the slicer filament preset.</small>
          </div>}
        </div>)}
        {filamentNotice && <p className="slicerModelFilamentNotice" role="status">{filamentNotice}</p>}
        <small>One consistent model colour is now passed to OrcaSlicer as a single-filament colour. Different colours across models still need native multi-material mapping, and are preview-only. Multi-plate output and modifier trees are not implemented yet.</small>
        </aside>
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

      </div>
      <div id="slicer-prepare-plate" className="slicerPrepareScene" ref={editorRef} aria-labelledby="slicer-mobile-tab-plate">
        {toolMode === "lay_face" && <p className="projectUploadHint" role="status">
          <strong>Lay on face:</strong> Tap or click the model face you want touching the build plate.
          MakerVault will rotate the model and place it back on the bed. Select the tool again to cancel.
        </p>}
        <SlicerPlateEditor files={files} localAssets={localAssets}
          onLocalAssetsChange={onLocalAssetsChange} objects={objects} onChange={updatePlate}
          onPrimaryChange={onPrimaryChange} onFilesUploaded={onFilesUploaded}
          onManualColorChange={onManualColorChange} defaultColor={defaultColor}
          plate={plate} plateType={plateType} plateLabel={plateLabel}
          printerLabel={selectedProfiles?.printer || printerDetails?.model || printerDetails?.name || ""}
          onPlateLabelChange={onPlateLabelChange} canEdit={canEdit && !busy} toolMode={toolMode} selectedInstanceId={selectedId}
          autoOrientGoal={autoOrientGoal} autoOrientRequest={autoOrientRequest}
          splitRequest={splitRequest}
          selectedInstanceIds={validSelection} onSelectModel={selectMultiple}
          onSelectedInstanceChange={selectSingle} measurementVisible={measurementVisible}
          measureMode={measureMode} measureUnit={measureUnit} measureSnapMode={measureSnapMode}
          measureClearVersion={measureClearVersion}
          onMeasurePinPlaced={() => setMeasureOptionsOpen(false)}
          onExitToolMode={() => setToolMode("select")} />
      </div>
      {settingsExpanded ? createPortal(
        <div className="slicerSettingsModalBackdrop" role="presentation"
          onMouseDown={event => {
            if (event.target === event.currentTarget) setSettingsExpanded(false);
          }}>
          <div className="slicerSettingsModal" role="dialog" aria-modal="true"
            aria-label="Expanded print settings">
            {settingsPanel}
          </div>
        </div>, document.body
      ) : settingsPanel}
    </div>
    <div className="slicerPrepareActions">
      <div aria-live="polite">
        {error && <p role="alert" className="integrationError">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {!draftBlockReason && !error && <p className="slicerActionStatus">
          Draft ready to save. Saving a draft does not require a slicing worker.
        </p>}
        {draftBlockReason && <p className="slicerActionStatus" role="status">
          <strong>Draft unavailable:</strong> {draftBlockReason}
          {!busy && canEdit && !!objects.length && !profilesReady &&
            <button type="button" onClick={onChangeProfiles}>Choose profiles</button>}
        </p>}
        {!draftBlockReason && sliceBlockReason && <p className="slicerActionStatus" role="status">
          <strong>Slicing unavailable:</strong> {sliceBlockReason}
          <button type="button" onClick={onChangeProfiles}>Check profiles and engine</button>
        </p>}
      </div>
      <div className="settingsActions">
        <button type="button" disabled={!plateReady || !profilesReady} onClick={onSaveDraft}>Save draft</button>
        <button type="button" className="primary" disabled={!plateReady || !profilesReady || !workerConfigured}
          onClick={onSlice}>Slice and preview</button>
      </div>
    </div>
  </section>;
}
