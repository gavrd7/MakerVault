import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import SlicerPlateEditor from "./SlicerPlateEditor";
import {addVariableLayerBand} from "./slicerVariableLayers.js";
import SlicerUiIcon from "./SlicerUiIcon";
import {NATIVE_TOOL_FEATURES, FEATURE_NAMES, usedNativeFeatures} from "./slicerEngineCompatibility";
import SlicerFlushVolumes from "./SlicerFlushVolumes";
import { apiFetch } from "../api";
import { matchLoadedSlotProfiles, slotProfileSearchTerm, resolveSlotLibrarySpool } from "./slicerSlotProfileMatching.js";

/**
 * Interactive Prepare shell. All slicing still goes through the existing
 * engine-specific, isolated queue. Disabled tools are intentionally visible:
 * none are represented as supported until their model transformation and
 * native format round-trip have been implemented and tested.
 */
const TOOLS = [
  { name: "Add model", target: "import", icon: "add", group: "create" },
  { name: "Add plate", target: "add_plate", icon: "add-plate", group: "create" },
  { name: "Duplicate", target: "duplicate", icon: "duplicate", group: "create" },
  { name: "Remove", target: "remove", icon: "remove", group: "create" },
  { name: "Move", target: "x_mm", icon: "move", group: "transform" },
  { name: "Rotate", target: "rotation_deg", icon: "rotate", group: "transform" },
  { name: "Scale", target: "scale_percent", icon: "scale", group: "transform" },
  { name: "Centre selected", target: "center", icon: "center", group: "arrange" },
  { name: "Auto-arrange", target: "arrange", icon: "arrange", group: "arrange" },
  { name: "Auto-orient", target: "auto_orient", icon: "orient", group: "arrange" },
  { name: "Lay on face", target: "lay_face", icon: "face", group: "arrange" },
  { name: "Fit selected", target: "focus", icon: "focus", group: "arrange" },
  { name: "Split", target: "split", icon: "split", group: "geometry" },
  { name: "Cut", target: "cut", icon: "cut", group: "geometry" },
  { name: "Drill", target: "drill", icon: "drill", group: "geometry" },
  { name: "Hollow", target: "hollow", icon: "hollow", group: "geometry" },
  { name: "Mesh boolean", target: "boolean", icon: "boolean", group: "geometry" },
  { name: "Measure", target: "measure", icon: "measure", expandable: true, group: "inspect" },
  { name: "Support painting", target: "paint_support", icon: "paint-support", group: "paint" },
  { name: "Seam painting", target: "paint_seam", icon: "paint-seam", group: "paint" },
  { name: "Variable layer height", target: "variable_layers", icon: "layers", group: "paint" },
  { name: "Colour painting", target: "paint_colour", icon: "paint-colour", group: "paint" },
  { name: "Fuzzy skin painting", target: "paint_fuzzy", icon: "paint-fuzzy", group: "paint" },
];
const TOOL_SHORT_LABELS = {
  "Add model":"Add model","Add plate":"Add plate","Duplicate":"Duplicate",
  "Remove":"Delete","Centre selected":"Centre","Auto-arrange":"Arrange",
  "Auto-orient":"Auto-orient","Lay on face":"Lay on face","Fit selected":"Fit model",
  "Mesh boolean":"Boolean","Support painting":"Support painting","Seam painting":"Seam painting",
  "Variable layer height":"Variable layer", "Fuzzy skin painting":"Fuzzy skin",
  "Colour painting":"Colour paint",
};
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
  plates = [], activePlateId = "plate-1", onChoosePlate, onAddPlate, onRemovePlate, onMoveModelsToPlate,
  onPlateLabelChange, onPrimaryChange, onFilesUploaded,
  defaultColor, onManualColorChange, canEdit, busy, error, notice,
  onChangeProfiles, onOpenDevice, onSaveDraft, onSaveProject, onExportNativeMaterials, onSliceMultimaterialTest, onImportProject, onSlice, onSliceAll, engine, printer,
  selectedProfiles, workerConfigured, engineCapabilities = {}, printerId,
  processOverrides = {}, onProcessOverridesChange, onSaveCustomProcessProfile,
  flushSettings = null, onFlushSettingsChange,
  slotFilamentProfiles = [], onSlotFilamentProfilesChange, filamentProfiles = [], onFilamentProfilesReload, spools = [],
  processProfiles = [], onSelectProcessProfile, onResetProcessSettings,
  printerDetails, nozzleMm, selectedPlateType = "Native / profile default",
  localAssets = [], onLocalAssetsChange, onPlateIssuesChange, plateIssues = null,
}) {
  const editorRef = useRef(null);
  const [sceneHeight, setSceneHeight] = useState(0);
  const latest = useRef(objects);
  const undoRef = useRef([]);
  const redoRef = useRef([]);
  const [, setHistoryVersion] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [selectedIds, setSelectedIds] = useState([]);
  const [expandedAssemblies, setExpandedAssemblies] = useState([]);
  const [movePlateTarget,setMovePlateTarget]=useState("");
  const [sliceMenuOpen,setSliceMenuOpen]=useState(false);
  const [showAllPlates,setShowAllPlates]=useState(false);
  const selectSingle = id => { setSelectedId(id); setSelectedIds(id ? [id] : []); };
  const selectMultiple = (id, additive = false, partOnly = false) => {
    const item = objects.find(row => row.instance_id === id);
    if (!item) return;
    if (!additive) {
      const ids = item.assembly_id && !partOnly
        ? objects.filter(row => row.assembly_id === item.assembly_id).map(row => row.instance_id)
        : [id];
      setSelectedIds(ids);
      setSelectedId(id);
      return;
    }
    // The assembly header selects a group; its expanded tree children can
    // be selected independently for per-part positioning and settings.
    const memberIds = item.assembly_id && !partOnly
      ? objects.filter(row => row.assembly_id === item.assembly_id).map(row => row.instance_id)
      : [id];
    setSelectedIds(current => {
      const allSelected = memberIds.every(value => current.includes(value));
      const next = allSelected
        ? current.filter(value => !memberIds.includes(value))
        : [...new Set([...current, ...memberIds])];
      setSelectedId(next.at(-1) || "");
      return next;
    });
  };
  const [scope, setScope] = useState("global");
  const [group, setGroup] = useState("Quality");
  const [toolMode, setToolMode] = useState("select");
  const [paintMode, setPaintMode] = useState("brush");
  const [paintSlot, setPaintSlot] = useState(0);
  const [supportSlot, setSupportSlot] = useState(0);
  const [seamSlot, setSeamSlot] = useState(0);
  const [supportOverhangsOnly, setSupportOverhangsOnly] = useState(false);
  const [supportOverhangAngle, setSupportOverhangAngle] = useState(45);
  const [paintBrushMm, setPaintBrushMm] = useState(3);
  const [paintAngle, setPaintAngle] = useState(30);
  const [paintHeight, setPaintHeight] = useState([0, 10]);
  const [paintHeightFollow, setPaintHeightFollow] = useState(true);
  const [paintHeightRange, setPaintHeightRange] = useState(10);
  const [paintErase, setPaintErase] = useState(false);
  const [paintError, setPaintError] = useState("");
  const [paintMobileMinimised, setPaintMobileMinimised] = useState(false);
  const [variableBandDraft,setVariableBandDraft] = useState({from_mm:0,to_mm:10,layer_mm:0.12});
  const [variableBandFollow,setVariableBandFollow] = useState(false);
  const [variableBandTarget,setVariableBandTarget] = useState("from");
  const [splitRequest, setSplitRequest] = useState(0);
  const [solidRequest, setSolidRequest] = useState(null);
  const [autoOrientMenuOpen, setAutoOrientMenuOpen] = useState(false);
  const [addModelMenuOpen, setAddModelMenuOpen] = useState(false);
  const [toolDescriptor, setToolDescriptor] = useState("");
  const [toolPopupStyle, setToolPopupStyle] = useState(null);
  const [autoOrientGoal, setAutoOrientGoal] = useState("balanced");
  const [autoOrientRequest, setAutoOrientRequest] = useState(0);
  const [measurementVisible, setMeasurementVisible] = useState(false);
  const [measureMode, setMeasureMode] = useState("distance");
  const [measureUnit, setMeasureUnit] = useState("mm");
  const [measureSnapMode, setMeasureSnapMode] = useState("auto");
  const [measureClearVersion, setMeasureClearVersion] = useState(0);
  const [nativeProcessFields, setNativeProcessFields] = useState({});
  const [settingsSearch, setSettingsSearch] = useState("");
  const [settingsLevel, setSettingsLevel] = useState("advanced");
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
    if (!spec || (spec.kind !== "toggle" && !spec.options?.some(option => String(option.value) === String(value)))) return;
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
  const [slotOfficialResults, setSlotOfficialResults] = useState({});
  const [slotOfficialSelections, setSlotOfficialSelections] = useState({});
  const [slotOfficialSearched, setSlotOfficialSearched] = useState({});
  const [slotOfficialBusy, setSlotOfficialBusy] = useState("");
  const [slotOfficialError, setSlotOfficialError] = useState("");
  const [editingSlotProfile,setEditingSlotProfile] = useState(null);
  const [detailsSlotId,setDetailsSlotId] = useState(null);
  const [filamentPickerId, setFilamentPickerId] = useState("");
  const [filamentNotice, setFilamentNotice] = useState("");
  // WCAG relative luminance: choose the more legible foreground for each
  // filament swatch rather than assuming all material colours are light.
  const materialTextColor = hex => {
    if (!/^#[0-9a-f]{6}$/i.test(hex || "")) return "#ffffff";
    const channel = offset => {
      const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    };
    const luminance = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
    return (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05)
      ? "#101722" : "#ffffff";
  };
  const validSlotColor = slot => /^#[0-9a-f]{6}$/i.test(slot?.color_hex || "")
    ? slot.color_hex.toUpperCase() : null;
  const slotName = slot => (slot.product_name || slot.material || "Unknown filament") +
    " · " + (slot.system_label || "Printer") + " slot " + ((slot.slot_index ?? 0) + 1);
  // A physical slot selection is an advisory project mapping, independent of
  // the preview colour and of the native slicer's filament preset. Never use it
  // to imply that a multi-material tool change has been configured.
  const changeModelPreviewFilament = (instanceId, slot) => {
    if (!printerId || slot?.id == null) return;
    const hex = validSlotColor(slot);
    const materialSlot = {
      printer_id: String(printerId),
      slot_id: String(slot.id),
      slot_index: Number(slot.slot_index ?? 0),
    };
    updatePlate(latest.current.map(item => item.instance_id === instanceId
      ? { ...item, ...(hex ? {color:hex} : {}), material_slot:materialSlot } : item));
    if (hex) onManualColorChange?.(instanceId);
    setFilamentPickerId("");
    setFilamentNotice("Assigned " + slotName(slot) +
      " to the project model. Single-slot slicing uses that slot's native filament preset when assigned; multi-slot printing requires verified tool routing.");
  };
  const clearModelFilament = instanceId => {
    updatePlate(latest.current.map(item => {
      if (item.instance_id !== instanceId) return item;
      const {material_slot:unused, ...withoutSlot} = item;
      return withoutSlot;
    }));
    setFilamentPickerId("");
    setFilamentNotice("Model's intended printer slot cleared. The native filament preset is unchanged.");
  };
  const [suppressedSlotMatches, setSuppressedSlotMatches] = useState([]);
  const [slotImportBusy, setSlotImportBusy] = useState(false);
  const currentPrinterIdRef = useRef(String(printerId || ""));
  currentPrinterIdRef.current = String(printerId || "");
  const lookupEngine = String(engine).split(" ")[0];
  const lookupVersion = String(engine).split(" ").slice(1).join(" ");
  const slotMatch = slot => matchLoadedSlotProfiles(resolveSlotLibrarySpool(slot,spools).slot, filamentProfiles, {
    engine: lookupEngine, version: lookupVersion, printer: printerDetails,
  });
  const findOfficialSlotProfiles = async slot => {
    const id = String(slot.id);
    const targetPrinterId = String(printerId || "");
    setSlotOfficialBusy(id);
    setSlotOfficialError("");
    setSlotOfficialResults(current => ({...current, [id]: []}));
    setSlotOfficialSelections(current => ({...current, [id]: ""}));
    setSlotOfficialSearched(current => ({...current, [id]: false}));
    try {
      if (lookupEngine !== "orcaslicer") {
        throw new Error("Direct slot profile search currently supports the pinned OrcaSlicer catalogue only.");
      }
      const linked = resolveSlotLibrarySpool(slot,spools);
      const matchingSlot = linked.slot;
      const query = slotProfileSearchTerm(matchingSlot);
      if (!query || query.length < 2) throw new Error("This slot has no recognisable filament material.");
      const printerBrand = String([matchingSlot.manufacturer, matchingSlot.brand, printerDetails?.manufacturer,
        printerDetails?.brand].filter(Boolean).join(" "));
      const manufacturerCatalogue = /creality/i.test(printerBrand) ? "Creality"
        : /bambu/i.test(printerBrand) ? "BBL"
        : /elegoo/i.test(printerBrand) ? "Elegoo" : "";
      const vendors = ["OrcaFilamentLibrary", ...(manufacturerCatalogue ? [manufacturerCatalogue] : [])];
      const searches = await Promise.allSettled(vendors.map(async vendor => {
        const params = new URLSearchParams({
          engine: lookupEngine, version: lookupVersion, vendor,
          kind: "filament", q: query, printer_id: String(printerId),
          slot_discovery: "1", material: matchingSlot.material || "",
          manufacturer: matchingSlot.manufacturer || matchingSlot.brand || "",
        });
        const result = await apiFetch("/api/printing/slicer/official-profiles/?" + params.toString());
        return (result.profiles || []).map(profile => ({...profile, vendor}));
      }));
      const candidates = searches.filter(row => row.status === "fulfilled")
        .flatMap(row => row.value);
      if (!searches.some(row => row.status === "fulfilled")) {
        throw new Error("The official filament catalogues could not be searched.");
      }
      // Candidate names can occur in multiple vendor catalogues.
      const distinct = new Map(candidates.map(profile =>
        [profile.vendor + ":" + profile.sub_path, profile]));
      if (currentPrinterIdRef.current !== targetPrinterId) return;
      const shortlisted = [...distinct.values()].sort((a,b) => {
        // The selected printer's native/vendor preset appears before generic
        // @System candidates; internal @base candidates were already excluded.
        const priority = entry => {
          const title = String(entry.name || "").toLowerCase();
          const model = String(printerDetails?.model || "").toLowerCase();
          const variant = model.match(/\\bk[12]\\b/)?.[0] || "";
          const onPrinter = variant && title.includes("@" ) && title.includes(variant);
          return (onPrinter ? 0 : 3) + (entry.vendor === manufacturerCatalogue ? 0 : 1);
        };
        return priority(a) - priority(b) || a.name.localeCompare(b.name);
      }).slice(0, 80);
      setSlotOfficialResults(current => ({...current, [id]: shortlisted}));
      setSlotOfficialSearched(current => ({...current, [id]: true}));
    } catch (err) {
      setSlotOfficialError(err.message || "Cannot search the official profile catalogue.");
    } finally {
      setSlotOfficialBusy("");
    }
  };
  const importOfficialSlotProfile = async (slot, candidate) => {
    if (!canEdit || slotImportBusy) return;
    if (!window.confirm("Import " + candidate.name + " for " + slotName(slot) + "?")) return;
    const targetPrinterId = String(printerId || "");
    setSlotImportBusy(true);
    setSlotOfficialError("");
    try {
      const result = await apiFetch("/api/printing/slicer/official-profiles/", {
        method: "POST",
        body: {kind:"filament",vendor:candidate.vendor,engine:lookupEngine,
          engine_version:lookupVersion,name:candidate.name,sub_path:candidate.sub_path},
      });
      const imported = result?.profile;
      if (!imported?.id || imported.kind !== "filament" ||
          imported.engine !== lookupEngine || imported.engine_version !== lookupVersion) {
        throw new Error("Imported preset did not match the active engine and version.");
      }
      // Return this exact profile to the parent's list immediately. The list
      // endpoint can be capped; reloading it alone must never hide a newly
      // imported preset just because it sorts after other installed parents.
      await onFilamentProfilesReload?.(imported);
      if (currentPrinterIdRef.current !== targetPrinterId) return;
      onSlotFilamentProfilesChange?.(current => [
        ...(current || []).filter(row => String(row.slot_id) !== String(slot.id)),
        {slot_id: String(slot.id), profile_id: String(imported.id)},
      ]);
      setSuppressedSlotMatches(current => current.filter(id => id !== String(slot.id)));
      setSlotOfficialResults(current => ({...current, [String(slot.id)]: []}));
      setSlotOfficialSelections(current => ({...current, [String(slot.id)]: ""}));
      setMaterialMessage(imported.name + " assigned to slot " +
        ((slot.slot_index ?? 0) + 1) + " (" +
        Math.max(0, (result.parent_chain_length || 1) - 1) + " parent preset(s)).");
    } catch (err) {
      setSlotOfficialError(err.message || "Profile import failed.");
      setMaterialMessage("CRITICAL: The selected slot profile was not assigned. " +
        (err.message || "Check native preset import."));
    } finally {
      setSlotImportBusy(false);
    }
  };
  const [materialRefreshing, setMaterialRefreshing] = useState(false);
  const [materialMessage, setMaterialMessage] = useState("Select Refresh to read current printer filament slots.");
  useEffect(() => { setSuppressedSlotMatches([]); setSlotOfficialResults({}); setSlotOfficialSelections({}); setSlotOfficialSearched({}); }, [printerId]);
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
        ? "Assigned slots use their selected native filament preset for a single-filament slice. Multiple slots still require verified tool routing."
        : "No loaded slots reported for this printer.");
    } catch (err) {
      if (requestId !== requestRef.current) return;
      setLiveMaterials([]);
      setMaterialMessage(err?.message || "Live printer filament information is unavailable.");
    } finally {
      if (requestId === requestRef.current) setMaterialRefreshing(false);
    }
  }, [printerId]);
  // Reconcile after slot inventory or imported presets change, never overwrite
  // existing selections. Stable objects and unchanged state do not trigger
  // a second profile assignment or a second printer refresh.
  useEffect(() => {
    if (!canEdit || !liveMaterials.length || !filamentProfiles.length) return;
    const existing = new Set(slotFilamentProfiles.map(row => String(row.slot_id)));
    const inferred = liveMaterials.filter(slot => !existing.has(String(slot.id)) && !suppressedSlotMatches.includes(String(slot.id)))
      .map(slot => ({slot, match: matchLoadedSlotProfiles(resolveSlotLibrarySpool(slot,spools).slot, filamentProfiles, {
        engine: String(engine).split(" ")[0],
        version: String(engine).split(" ").slice(1).join(" "),
        printer: printerDetails,
      })}))
      .filter(({match}) => match.level === "exact")
      .map(({slot, match}) => ({slot_id: String(slot.id), profile_id: String(match.profile.id)}));
    if (inferred.length) onSlotFilamentProfilesChange?.([...slotFilamentProfiles, ...inferred]);
  }, [canEdit, liveMaterials, filamentProfiles, slotFilamentProfiles, engine, printerDetails, onSlotFilamentProfilesChange, suppressedSlotMatches, spools]);
  useEffect(() => {
    refreshPrinterMaterials();
    return () => { requestRef.current += 1; };
  }, [refreshPrinterMaterials]);
  useEffect(()=>{
    undoRef.current=[];redoRef.current=[];
    setSelectedId("");setSelectedIds([]);setSolidRequest(null);setMovePlateTarget("");
    setToolMode("select");setPaintError("");setMeasurementVisible(false);
    setSplitRequest(0);setHistoryVersion(version=>version+1);
  },[activePlateId]);
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
  // Assemblies display as contiguous logical groups regardless of the
  // underlying object order. Individual parts retain their instance IDs
  // and remain independently editable inside the expanded group.
  const modelTreeRows=(()=>{
    const visited=new Set(),result=[];
    for(const row of objects) {
      if(!row.assembly_id){result.push(row);continue;}
      if(visited.has(row.assembly_id))continue;
      visited.add(row.assembly_id);
      result.push(...objects.filter(item=>item.assembly_id===row.assembly_id));
    }
    return result;
  })();
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
    setExpandedAssemblies(current => current.filter(value => value !== id));
  }
  function disassembleSelected() {
    if (!canEdit || busy || !activeAssembly) return;
    updatePlate(objects.map(row => row.assembly_id === activeAssembly
      ? { ...row, assembly_id: null } : row));
    setExpandedAssemblies(current=>current.filter(id=>id!==activeAssembly));
  }
  const removableAssemblyMembers=selectedModels.filter(row=>row.assembly_id);
  function removeSelectedFromAssembly(){
    if(!canEdit||busy||!removableAssemblyMembers.length)return;
    const ids=new Set(removableAssemblyMembers.map(row=>row.instance_id));
    const remaining=objects.map(row=>ids.has(row.instance_id)
      ?{...row,assembly_id:null}:row);
    const counts=new Map();
    remaining.forEach(row=>{if(row.assembly_id)
      counts.set(row.assembly_id,(counts.get(row.assembly_id)||0)+1);});
    updatePlate(remaining.map(row=>row.assembly_id&&counts.get(row.assembly_id)<2
      ?{...row,assembly_id:null}:row));
    setExpandedAssemblies(current=>current.filter(id=>counts.get(id)>=2));
    setSelectedIds([]);setSelectedId("");
  }
  const active = selectedId ? objects.find(row => row.instance_id === selectedId) : null;
  const itemName = object => {
    const file = [...localAssets, ...files].find(row => String(row.id) === String(object.asset_id));
    return file?.name || file?.filename || "STL model";
  };
  const toolbarAnchor = event => {
    const button=event?.currentTarget?.closest(".slicerToolTooltip")?.querySelector("button");
    const rect=(button||event?.currentTarget)?.getBoundingClientRect?.();
    return rect ? {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom} : null;
  };
  function selectTool(tool, event) {
    const feature = NATIVE_TOOL_FEATURES[tool.target];
    if (feature && !["draft_only","test_only","verified"].includes(engineCapabilities[feature]?.status)) return;
    // Keep each menu inside the bordered toolbar, even when icons wrap.
    if (["import","auto_orient"].includes(tool.target)) {
      const anchor=event?.currentTarget?.closest(".slicerToolTooltip");
      const toolbar=anchor?.closest(".slicerPrepareTools");
      if (anchor && toolbar) {
        const frame=toolbar.getBoundingClientRect();
        const button=anchor.getBoundingClientRect();
        if (window.innerWidth <= 850) {
          const width=Math.min(260,window.innerWidth-24);
          setToolPopupStyle({
            position:"fixed",left:Math.max(12,Math.min(button.left,window.innerWidth-width-12))+"px",
            top:Math.min(button.bottom+8,window.innerHeight-175)+"px",
            right:"auto",transform:"none",width:width+"px",
            maxHeight:"min(65dvh, 360px)",overflowY:"auto",
          });
        } else {
          const width=Math.min(260,Math.max(160,frame.width-16));
          const desired=button.left+button.width/2-frame.left-width/2;
          const left=Math.max(8,Math.min(desired,frame.width-width-8));
          setToolPopupStyle({
            left:(left-(button.left-frame.left))+"px",
            right:"auto",transform:"none",width:width+"px",
          });
        }
      }
    }
    if (tool.target === "import") {
      setAutoOrientMenuOpen(false);
      setAddModelMenuOpen(open => !open);
      return;
    }
    setAddModelMenuOpen(false);
    if (["paint_colour","paint_support","paint_seam","paint_fuzzy"].includes(tool.target)) {
      if (!selectedId && objects[0]?.instance_id) selectSingle(objects[0].instance_id);
      setMeasurementVisible(false);setAutoOrientMenuOpen(false);
      setPaintError("");
      setToolMode(current => current === tool.target ? "select" : tool.target);
      setMobilePane("plate");
      return;
    }
    if (tool.target === "variable_layers") {
      if (!selectedId && objects[0]?.instance_id) selectSingle(objects[0].instance_id);
      setMeasurementVisible(false);setAutoOrientMenuOpen(false);
      setToolMode("variable_layers");setMobilePane("plate");return;
    }
    if (tool.target === "measure") {
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setToolMode("select");
      setMeasurementVisible(true);
      setMobilePane("plate");
      return;
    }
    setMeasurementVisible(false);
    if (tool.target === "add_plate") {
      setShowAllPlates(false);onAddPlate?.();setToolMode("select");setMobilePane("plate");return;
    }
    if (tool.target === "auto_orient") {
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setAutoOrientMenuOpen(current => !current);
      setMobilePane("plate");
      return;
    }
    setAutoOrientMenuOpen(false);
    if (["hollow", "drill", "cut", "boolean"].includes(tool.target)) {
      if (!selectedId && objects[0]?.instance_id) setSelectedId(objects[0].instance_id);
      setToolMode("select");
      setMobilePane("plate");
      setSolidRequest({ kind: tool.target, id: Date.now() + Math.random(), anchorRect:toolbarAnchor(event) });
      return;
    }
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
    if (["x_mm", "rotation_deg", "scale_percent"].includes(tool.target)) {
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
  const projectHasModels=plates.length?plates.some(item=>item.objects.length>0):objects.length>0;
  const plateReady = canEdit && projectHasModels && !busy;
  const activePlateReady = canEdit && !!objects.length && !busy;
  const conflictsBlockSlice = !plateIssues || plateIssues.signature !== JSON.stringify(objects) ||
    plateIssues.issues.length > 0;
  const missingNativeProfiles = ["printer", "process", "filament"].filter(
    kind => !selectedProfiles?.[kind + "_id"]);
  const profilesReady = missingNativeProfiles.length === 0;
  const draftBlockReason = !canEdit
    ? "Your account cannot prepare slicing drafts."
    : busy ? "The slicer is still loading or processing a request."
    : !projectHasModels ? "Add a model to at least one build plate first."
    : !profilesReady ? "Missing native " + missingNativeProfiles.join(", ") + (missingNativeProfiles.length === 1 ? " profile" : " profiles") + ". Choose the matching profiles in Slicer setup."
    : "";
  // Matches the bounded keys proven by the pinned Orca 2.5.0 real-binary
  // two-object G-code fixture. Object edits outside this set remain draft-only.
  const verifiedObjectSettings = new Set(["wall_loops", "sparse_infill_density"]);
  const objectSettingsPending = objects.some(item =>
    Object.keys(item.process_overrides || {}).some(key => !verifiedObjectSettings.has(key))
  );
  // Physical feeder slots are not Orca tool numbers. A single selected
  // feeder may annotate a normal one-filament slice; multiple feeders need
  // separate native palette + printer-changeover verification.
  const assignedSlots = objects.map(item => item.material_slot).filter(Boolean);
  const hasSingleSlot = assignedSlots.length > 0
    && assignedSlots.length === objects.length
    && assignedSlots.every(slot => String(slot.printer_id) === String(printerId)
      && slot.slot_id === assignedSlots[0].slot_id
      && slot.slot_index === assignedSlots[0].slot_index);
  const multiMaterialReadyForExport = assignedSlots.length === objects.length
    && new Set(assignedSlots.map(slot => slot.slot_id)).size >= 2
    && slotFilamentProfiles.length >= 2;
  // The server inherits the explicitly assigned native filament for a
  // single-slot slice; it need not match the main profile shown in Setup.
  // An unrelated or missing native slot profile is still unsafe.
  // Other loaded slots may have saved native presets without participating
  // in this particular slice. Only the assigned slot selects the one native
  // logical filament. Multiple model-assigned slots remain blocked.
  const activeSlotProfiles = slotFilamentProfiles.filter(row =>
    row.slot_id === assignedSlots[0]?.slot_id);
  // A physical slot assignment must have an explicitly selected native
  // filament preset. Never silently use the main PLA/other material preset.
  const singleSlotProfileMatches = activeSlotProfiles.length === 1
    && filamentProfiles.some(profile =>
      String(profile.id) === String(activeSlotProfiles[0].profile_id)
      && profile.kind === "filament"
      && profile.engine === String(engine).split(" ")[0]
      && profile.engine_version === String(engine).split(" ").slice(1).join(" "));
  const materialRoutingPending = assignedSlots.length > 0
    ? !(hasSingleSlot && singleSlotProfileMatches)
    : false;
  const projectRoutingPending = plates.some(plate =>
    (plate.objects || []).some(item => item.material_slot != null)
  ) || slotFilamentProfiles.length > 0;
  const incompatibleEdits = usedNativeFeatures([{objects}]).filter(
    key => !["verified","test_only"].includes(engineCapabilities[key]?.status));
  const nativeEditReason = incompatibleEdits.length
    ? "Native export not yet verified for " + incompatibleEdits.map(key=>FEATURE_NAMES[key]).join(", ") +
      ". The project is preserved; choose an engine with verified native support before slicing."
    : "";
  const sliceBlockReason = draftBlockReason ||
    nativeEditReason ||
    (!activePlateReady ? "Select a plate containing models to slice." : "") ||
    (conflictsBlockSlice ? "Resolve build-plate conflicts or wait for models to finish loading before slicing." : "") ||
    (flushSettings != null ? "This draft contains flushing/prime-tower overrides, but the physical multi-material path is not yet enabled. Save the draft or reset flushing settings to slice a single-filament job." : "") ||
    (materialRoutingPending ? "An assigned CFS/AMS slot requires an imported native filament preset for that slot. Select its Profile before slicing. Multiple assigned slots still need verified multi-material routing."
      : objectSettingsPending
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
                {profile.name}
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
                  : "No matching settings in this native process profile at the selected detail level. Try Expert or another process profile."}
              </p>}
            {Object.keys(editingOverrides).length > 0 && <div className="slicerNativeSettingsActions">
              <span>{Object.keys(editingOverrides).length} {editingObject ? "object" : "global"} draft override(s) · Original profile unchanged</span>
              <div className="slicerNativeSettingsButtons">
                {!editingObject && <button type="button" disabled={!canEdit || busy || savingCustomProfile || !onSaveCustomProcessProfile}
                  onClick={event => {
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
  const paintPalette = (() => {
    const saved = objects.find(item => item.instance_id === selectedId)?.colour_paint?.palette;
    if (Array.isArray(saved) && saved.length) return saved;
    const loaded = [...liveMaterials].sort((a, b) => Number(a.slot_index ?? 0) - Number(b.slot_index ?? 0)).slice(0, 64);
    return loaded.length ? loaded.map(slot => ({
      color: validSlotColor(slot) || "#8c80d9",
      label: slotName(slot),
      printer_id: String(printerId),
      slot_id: String(slot.id),
      slot_index: Number(slot.slot_index ?? 0),
    })) : ["#58b5e4","#f59e0b","#a78bfa","#10b981","#ef4444","#f472b6"].map((color, index) => ({
      color, label: "Preview colour " + (index + 1),
    }));
  })();
  // Shared brush and region selectors for colour and support painting.
  const paintTools = [
    ["brush","paint-brush","Brush · paint the visible surface with an adjustable pen"],
    ["sphere","paint-sphere","Sphere · paint a 3D region around the pointer"],
    ["smart_fill","paint-fill","Fill · paint the clicked surface until a sharp edge"],
    ["height","paint-height","Height range · paint between two model heights"],
  ];
  const paintSelected = objects.find(row => row.instance_id === selectedId);
  const isSupportPainting=toolMode==="paint_support";
  const isSeamPainting=toolMode==="paint_seam";
  const isFuzzyPainting=toolMode==="paint_fuzzy";
  const isSemanticPainting=isSeamPainting||isFuzzyPainting;
  const activeSemanticField=isSeamPainting?"seam_paint":"fuzzy_skin_paint";
  const activePaintState=isSupportPainting?paintSelected?.support_paint:
    isSemanticPainting?paintSelected?.[activeSemanticField]:paintSelected?.colour_paint;
  const paintPanel = ["paint_colour","paint_support","paint_seam","paint_fuzzy"].includes(toolMode) && (
    <section className={"slicerColourPaintPanel"+(paintMobileMinimised?" slicerPaintMinimised":"")} aria-label={isSupportPainting?"Support painting controls":isSeamPainting?"Seam painting controls":isFuzzyPainting?"Fuzzy skin painting controls":"Colour painting controls"}
      style={{position:"absolute",top:"var(--slicer-paint-top, 56px)",left:12,zIndex:20,width:"min(310px, calc(100% - 74px))",
        maxHeight:"min(490px, calc(100% - 24px))",overflowY:"auto",padding:10,
        border:"1px solid #476079",borderRadius:10,background:"rgba(17,27,42,.96)",
        boxShadow:"0 8px 26px rgba(0,0,0,.4)",display:"grid",gap:8}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:8}}>
        <strong>{isSupportPainting?"Support painting":isSeamPainting?"Seam painting":isFuzzyPainting?"Fuzzy skin painting":"Colour painting"}</strong>
        <div style={{display:"flex",alignItems:"center",gap:5}}>
          <button type="button" className="slicerPaintMobileMinimise"
            aria-expanded={!paintMobileMinimised}
            onClick={()=>setPaintMobileMinimised(v=>!v)}>
            {paintMobileMinimised?"Tools":"Minimise"}
          </button>
        <button type="button" onClick={()=>{setToolMode("select");setPaintError("");}}
          aria-label="Close painting">Done</button>
        </div>
      </div>
      <div role="group" aria-label="Painting tools" style={{display:"flex",flexWrap:"wrap",gap:5}}>
        {paintTools.map(([mode,icon,description])=><button type="button" key={mode}
          title={description} aria-label={description} aria-pressed={paintMode===mode}
          onClick={()=>setPaintMode(mode)} className={paintMode===mode?"isActive":""}
          style={{border:paintMode===mode?"2px solid #38bdf8":"1px solid #53647a",
            borderRadius:7,width:33,height:33,display:"grid",placeItems:"center",padding:5}}>
          <SlicerUiIcon name={icon} size={19}/></button>)}
      </div>
      {!isSupportPainting&&!isSemanticPainting&&<div role="group" aria-label="Paint filament palette" style={{display:"flex",gap:6,flexWrap:"wrap"}}>
        {paintPalette.map((slot,index)=><button key={index} type="button"
          title={slot.label} aria-label={"Paint with "+slot.label}
          aria-pressed={!paintErase&&paintSlot===index}
          onClick={()=>{setPaintSlot(index);setPaintErase(false);}}
          style={{display:"grid",justifyItems:"center",alignContent:"center",gap:1,
            padding:"3px",border:!paintErase&&paintSlot===index?"2px solid #38bdf8":"1px solid #53647a",
            borderRadius:8,minWidth:53,background:"transparent",maxWidth:85}}>
          <span style={{fontSize:10,maxWidth:74,overflow:"hidden",textOverflow:"ellipsis",
            whiteSpace:"nowrap"}}>{(slot.label||"Filament").split(" · ")[0]}</span>
          <span style={{width:25,height:25,borderRadius:"50%",backgroundColor:slot.color,
            border:"1px solid #9aa9bc",display:"grid",placeItems:"center",
            color:materialTextColor(slot.color),fontWeight:700,fontSize:11}}>{index+1}</span>
        </button>)}
      </div>}
      {isSupportPainting&&<>
        <div role="group" aria-label="Support painting action" style={{display:"flex",gap:5}}>
          {[[0,"Enforce supports"],[1,"Block supports"]].map(([slot,label])=><button type="button" key={slot}
            aria-pressed={!paintErase&&supportSlot===slot} className={!paintErase&&supportSlot===slot?"isActive":""}
            onClick={()=>{setSupportSlot(slot);setPaintErase(false);}}>{label}</button>)}
        </div>
        <label className="checkRow" style={{display:"flex",alignItems:"center",gap:7,fontSize:12}}>
          <input type="checkbox" checked={supportOverhangsOnly}
            onChange={event=>setSupportOverhangsOnly(event.target.checked)} />
          <span>Overhangs only</span>
        </label>
        {supportOverhangsOnly&&<label style={{display:"grid",gap:3,fontSize:12}}>
          Overhang angle · {supportOverhangAngle}° from vertical
          <input type="range" min="10" max="80" step="5" aria-label="Support overhang angle"
            value={supportOverhangAngle} onChange={event=>setSupportOverhangAngle(Number(event.target.value))} />
          <small style={{opacity:.8}}>Restricts new support-enforcer strokes to downward-facing overhangs. Blockers and erasing remain unrestricted.</small>
        </label>}
      </>}
      {isSeamPainting&&<div role="group" aria-label="Seam painting action" style={{display:"flex",gap:5}}>
        {[[0,"Enforce seam"],[1,"Block seam"]].map(([slot,label])=><button type="button" key={slot}
          aria-pressed={!paintErase&&seamSlot===slot} className={!paintErase&&seamSlot===slot?"isActive":""}
          onClick={()=>{setSeamSlot(slot);setPaintErase(false);}}>{label}</button>)}
      </div>}
      {isFuzzyPainting&&<small>Enable native fuzzy skin in Print Settings before slicing. Painted masks are currently draft-only.</small>}
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:5}}>
        <small>{isSupportPainting ? `${paintSelected?.support_paint?.regions?.reduce((n,r)=>n+r.patches.length,0)||0} support patches` : isSemanticPainting ? `${activePaintState?.regions?.reduce((n,r)=>n+r.patches.length,0)||0} ${isSeamPainting?"seam":"fuzzy skin"} patches` : paintSelected?.colour_paint?.version === 2 ? `${paintSelected.colour_paint.regions?.reduce((n,region)=>n+region.patches.length,0)||0} clipped patches` : `${paintSelected?.colour_paint ? Object.keys(paintSelected.colour_paint.faces||{}).length : 0} facets (legacy)`}</small>
        <div className="slicerPaintEditActions">
          <button type="button" title="Erase painted faces" aria-label="Erase painted faces"
            aria-pressed={paintErase} onClick={()=>setPaintErase(true)}
            className={paintErase?"isActive":""}>Erase</button>
        <button type="button" disabled={!activePaintState}
          onClick={()=>{updatePlate(latest.current.map(item=>{
            if(item.instance_id!==selectedId)return item;
            if(isSupportPainting){const {support_paint:unused,...rest}=item;return rest;}
            if(isSeamPainting){const {seam_paint:unused,...rest}=item;return rest;}
            if(isFuzzyPainting){const {fuzzy_skin_paint:unused,...rest}=item;return rest;}
            const {colour_paint:unused,...rest}=item;return rest;
          }));setPaintError("");}}>Clear all</button>
        </div>
      </div>
      {["brush","sphere"].includes(paintMode)&&<label style={{display:"grid",gap:2,fontSize:12}}>
        {paintMode==="brush"?"Brush":"Region"} radius · {paintBrushMm} mm
        <input aria-label="Paint radius" type="range" min="0.5" max="30" step="0.5"
          value={paintBrushMm} onChange={e=>setPaintBrushMm(Number(e.target.value))}/>
      </label>}
      {paintMode==="smart_fill"&&<label style={{display:"grid",gap:2,fontSize:12}}>
        Surface angle · {paintAngle}°
        <input type="range" min="0" max="90" aria-label="Smart fill angle"
          value={paintAngle} onChange={e=>setPaintAngle(Number(e.target.value))}/>
      </label>}
      {paintMode==="height"&&<div style={{display:"grid",gap:5}}>
        <label className="slicerPaintHeightFollowRow">
          <input type="checkbox" checked={paintHeightFollow}
            onChange={e=>setPaintHeightFollow(e.target.checked)}/>
          <span>Follow pointer to position band</span>
        </label>
        <label style={{display:"grid",gap:2,fontSize:12}}>
          Range thickness · {paintHeightRange} mm
          <input type="range" min="0.5" max="100" step="0.5" value={paintHeightRange}
            aria-label="Height painting range thickness"
            onChange={e=>{
              const mm=Number(e.target.value);setPaintHeightRange(mm);
              setPaintHeight(([from])=>[from,Math.round((from+mm)*2)/2]);
            }}/>
        </label>
        <small>{paintHeightFollow?"Move over the model to position the height band; click to paint.":
          "Fixed range: edit both heights below, then click the model to paint."}</small>
        <div style={{display:"flex",gap:7}}>
          <label style={{flex:1,minWidth:0,fontSize:11}}>From (mm)
            <input type="number" min="0" step=".5" aria-label="Paint from height" style={{width:"100%"}}
              value={paintHeight[0]} onChange={e=>{
                const from=Number(e.target.value);setPaintHeight(v=>{
                  setPaintHeightRange(Math.max(.5,Math.abs(v[1]-from)));return [from,v[1]];
                });setPaintHeightFollow(false);
              }}/>
          </label>
          <label style={{flex:1,minWidth:0,fontSize:11}}>To (mm)
            <input type="number" min="0" step=".5" aria-label="Paint to height" style={{width:"100%"}}
              value={paintHeight[1]} onChange={e=>{
                const to=Number(e.target.value);setPaintHeight(v=>{
                  setPaintHeightRange(Math.max(.5,Math.abs(to-v[0])));return [v[0],to];
                });setPaintHeightFollow(false);
              }}/>
          </label>
        </div>
      </div>}
      <small style={{fontSize:11,opacity:.8}}>Left drag: paint · Right drag: rotate view · Wheel: zoom · Ctrl+Z / Ctrl+Y: undo / redo. Paint annotations are preview-only until native export is verified.</small>
      {paintError&&<small role="alert" style={{color:"#fca5a5"}}>{paintError}</small>}
    </section>
  );
  const variableLayersSelected=objects.find(row=>row.instance_id===selectedId);
  const variableLayerBands=variableLayersSelected?.variable_layer_profile?.bands || [];
  const variableLayerPanel=toolMode==="variable_layers" && (
    <section className="slicerColourPaintPanel slicerVariableLayerPanel"
      aria-label="Variable layer height controls"
      style={{position:"absolute",top:"var(--slicer-paint-top, 56px)",left:12,zIndex:20,
        width:"min(310px, calc(100% - 74px))",maxHeight:"min(490px, calc(100% - 24px))",
        overflowY:"auto",padding:10,border:"1px solid #476079",borderRadius:10,
        background:"rgba(17,27,42,.96)",boxShadow:"0 8px 26px rgba(0,0,0,.4)",
        display:"grid",gap:8}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:8}}>
        <strong>Variable layer height</strong>
        <button type="button" onClick={()=>{setToolMode("select");setPaintError("");}}>Done</button>
      </div>
      <label className="slicerVariableLayerRange">
        <span>Band thickness <strong>{(Math.max(.5,Number(variableBandDraft.to_mm)-Number(variableBandDraft.from_mm))).toFixed(1)} mm</strong></span>
        <input type="range" min="0.5" max="50" step="0.5"
          aria-label="Variable layer height Z band thickness"
          value={Math.max(.5,Math.min(50,Number(variableBandDraft.to_mm)-Number(variableBandDraft.from_mm)))}
          onChange={e=>setVariableBandDraft(current=>({
            ...current,to_mm:Math.min(1000,Math.round((current.from_mm+Number(e.target.value))*2)/2)
          }))}/>
      </label>
       <div className="slicerVariableLayerPointerControls">
        <label className="checkRow" style={{display:"flex",gap:7,alignItems:"center"}}>
          <input type="checkbox" checked={variableBandFollow}
            onChange={event=>setVariableBandFollow(event.target.checked)} />
          Pick Z on model
        </label>
        <label>Pointer adjusts
          <select aria-label="Variable layer height pointer target"
            value={variableBandTarget}
            onChange={event=>setVariableBandTarget(event.target.value)}>
            <option value="from">Position entire band</option>
            <option value="to">Adjust end of band</option>
          </select>
        </label>
        <small>Hover to preview Z; click or tap to set it.</small>
      </div>
      <div className="slicerVariableLayerBandGrid">
        {[
          ["from_mm","From Z (mm)",0.5],
          ["to_mm","To Z (mm)",0.5],
          ["layer_mm","Layer height (mm)",0.01],
        ].map(([key,label,step])=><label key={key}>{label}
          <input type="number" min={key==="layer_mm" ? 0.05 : 0}
            max={key==="layer_mm" ? 0.5 : 1000} step={step}
            value={variableBandDraft[key]}
            onChange={event=>setVariableBandDraft(current=>({...current,
              [key]:Number(event.target.value)}))} />
        </label>)}
      </div>
      <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
      <button type="button" disabled={!variableLayersSelected} onClick={()=>{
        try{
          const bands=addVariableLayerBand(variableLayerBands,
            variableBandDraft.from_mm,variableBandDraft.to_mm,variableBandDraft.layer_mm);
          updatePlate(latest.current.map(row=>row.instance_id===selectedId
            ?{...row,variable_layer_profile:{version:1,bands}}:row));
          setPaintError("");
        }catch(error){setPaintError(error.message||"Invalid variable layer range.");}
      }}>Add layer range</button>
      <button type="button" disabled={!variableLayerBands.length} onClick={()=>{
        updatePlate(latest.current.map(row=>row.instance_id===selectedId
          ?(({variable_layer_profile:unused,...rest})=>rest)(row):row));
        setPaintError("");
      }}>Clear all</button>
      </div>
      {variableLayerBands.map((band,i)=><div key={i} className="slicerVariableLayerBandRow">
        <span>{band.from_mm}–{band.to_mm} mm · {band.layer_mm} mm layers</span>
        <button type="button" aria-label={"Remove layer range "+(i+1)}
          onClick={()=>{
            const bands=variableLayerBands.filter((_,j)=>i!==j);
            updatePlate(latest.current.map(row=>row.instance_id===selectedId
              ?(bands.length?{...row,variable_layer_profile:{version:1,bands}}:
                (({variable_layer_profile:unused,...rest})=>rest)(row)):row));
            setPaintError("");
          }}>Remove</button>
      </div>)}
      <small>Draft only · Native layer-profile export pending</small>
      {paintError&&<small role="alert" style={{color:"#fca5a5"}}>{paintError}</small>}
    </section>
  );
  // Mobile toolbar scroll viewports clip all descendants, even position:fixed.
  // Portal the menu on phones; keep the desktop popover in its original place.
  const addModelMenu = (
    <div
          className="slicerToolOptions slicerAddModelMenu" style={toolPopupStyle} id="slicer-add-model-toolbar-options"
          role="group" aria-label="Add model options">
          <div className="slicerToolOptionsHeader"><strong>Add model</strong>
            <button type="button" aria-label="Close Add model menu"
              onClick={() => setAddModelMenuOpen(false)}>Close</button>
          </div>
          <button type="button" className="slicerAddModelChoice" onClick={event => {
            setAddModelMenuOpen(false);
            editorRef.current?.querySelector('input[type="file"][accept=".stl,.3mf"]')?.click();
          }}><SlicerUiIcon name="add" /> Upload from device</button>
          <button type="button" className="slicerAddModelChoice" onClick={event => {
            setAddModelMenuOpen(false);
            setMobilePane("plate");
            editorRef.current?.querySelector('[data-slicer-add-models]')?.scrollIntoView({
              behavior: "smooth", block: "start"
            });
          }}><SlicerUiIcon name="models" /> Add from MakerVault</button>
          <button type="button" className="slicerAddModelChoice" onClick={event => {
            setAddModelMenuOpen(false);setMobilePane("plate");
            setSolidRequest({kind:"primitive",id:Date.now(),anchorRect:toolbarAnchor(event)});
          }}><SlicerUiIcon name="models" /> Add primitive shape</button>
          <button type="button" className="slicerAddModelChoice" onClick={event => {
            setAddModelMenuOpen(false);setMobilePane("plate");
            setSolidRequest({kind:"text",id:Date.now(),anchorRect:toolbarAnchor(event)});
          }}><SlicerUiIcon name="shape-text" /> Add text</button>
          <button type="button" className="slicerAddModelChoice" onClick={event => {
            setAddModelMenuOpen(false);setMobilePane("plate");
            setSolidRequest({kind:"svg",id:Date.now(),anchorRect:toolbarAnchor(event)});
          }}><SlicerUiIcon name="shape-svg" /> Add SVG</button>
          <button type="button" className="slicerAddModelChoice" disabled={!objects.length} onClick={event => {
            setAddModelMenuOpen(false);setMobilePane("plate");
            setSolidRequest({kind:"negative",id:Date.now(),anchorRect:toolbarAnchor(event)});
          }}><SlicerUiIcon name="cut" /> Add negative volume</button>
        </div>
  );
  const modelToolbar = (
<div className="slicerPrepareTools" role="toolbar" aria-label="Model editing tools">
      <span className="slicerToolTooltip" onMouseEnter={() => setToolDescriptor("Undo · Ctrl+Z")}
        onMouseLeave={() => setToolDescriptor("")}
        onFocus={() => setToolDescriptor("Undo · Ctrl+Z")}
        onBlur={() => setToolDescriptor("")}>
        <button type="button" disabled={!undoRef.current.length || busy} onClick={undo}
          aria-label="Undo"><SlicerUiIcon name="undo" /><span className="slicerToolButtonLabel">Undo</span></button>
      </span>
      <span className="slicerToolTooltip" onMouseEnter={() => setToolDescriptor("Redo · Ctrl+Y")}
        onMouseLeave={() => setToolDescriptor("")}
        onFocus={() => setToolDescriptor("Redo · Ctrl+Y")}
        onBlur={() => setToolDescriptor("")}>
        <button type="button" disabled={!redoRef.current.length || busy} onClick={redo}
          aria-label="Redo"><SlicerUiIcon name="redo" /><span className="slicerToolButtonLabel">Redo</span></button>
      </span>
      {TOOLS.map((tool,index) => <div className={"slicerToolTooltip" + (index>0&&TOOLS[index-1].group!==tool.group?" slicerToolGroupStart":"") + (((tool.target === "auto_orient" && autoOrientMenuOpen) || (tool.target === "import" && addModelMenuOpen)) ? " slicerToolOptionsOpen" : "")} key={tool.name}
        onMouseEnter={() => setToolDescriptor(NATIVE_TOOL_FEATURES[tool.target] ?
          tool.name + " · " + (engineCapabilities[NATIVE_TOOL_FEATURES[tool.target]]?.reason || "Native export has not been verified.") :
          tool.pending ? tool.name + " · Not yet available: " + tool.pending : tool.name)}
        onMouseLeave={() => setToolDescriptor("")}
        onFocus={() => setToolDescriptor(tool.pending ? tool.name + " · Not yet available: " + tool.pending : tool.name)}
        onBlur={() => setToolDescriptor("")}
        data-tooltip={NATIVE_TOOL_FEATURES[tool.target] ?
          tool.name + " · " + (engineCapabilities[NATIVE_TOOL_FEATURES[tool.target]]?.reason || "Not verified for this engine/version. Try OrcaSlicer for draft editing.") :
          tool.pending ? tool.name + " · Not yet available: " + tool.pending
          : tool.expandable ? tool.name + " · Options in the Measure panel" : tool.name}>
        <button type="button"
          className={((tool.target === "x_mm" && toolMode === "move") ||
            (tool.target === "rotation_deg" && toolMode === "rotate") ||
            (tool.target === "scale_percent" && toolMode === "scale") ||
            (tool.target === "measure" && measurementVisible) ||
            (tool.target === "paint_support" && toolMode === "paint_support") ||
            (tool.target === "paint_seam" && toolMode === "paint_seam") ||
            (tool.target === "paint_fuzzy" && toolMode === "paint_fuzzy") ||
            (tool.target === "variable_layers" && toolMode === "variable_layers") ||
            (tool.target === "paint_colour" && toolMode === "paint_colour") ||
            (tool.target === "lay_face" && toolMode === "lay_face") ||
            (tool.target === "auto_orient" && autoOrientMenuOpen) ||
            (tool.target === "import" && addModelMenuOpen)) ? "isActive" : ""}
          aria-pressed={["paint_colour","paint_support","paint_seam","paint_fuzzy"].includes(tool.target) ? toolMode === tool.target : tool.target === "measure" ? measurementVisible :
            tool.target === "lay_face" ? toolMode === "lay_face" :
            tool.target === "auto_orient" ? autoOrientMenuOpen :
            ["x_mm", "rotation_deg", "scale_percent"].includes(tool.target)
            ? (tool.target === "x_mm" ? toolMode === "move"
              : tool.target === "rotation_deg" ? toolMode === "rotate" : toolMode === "scale") : undefined}
          aria-label={tool.name}
          aria-expanded={tool.target === "import" ? addModelMenuOpen : tool.target === "auto_orient" ? autoOrientMenuOpen : undefined}
          aria-controls={tool.target === "import" ? "slicer-add-model-toolbar-options" : tool.target === "auto_orient" ? "slicer-auto-orient-toolbar-options" : undefined}
          disabled={!!tool.pending || !canEdit || busy ||
            (NATIVE_TOOL_FEATURES[tool.target] && !["draft_only","test_only","verified"].includes(
              engineCapabilities[NATIVE_TOOL_FEATURES[tool.target]]?.status)) ||
            (tool.target==="add_plate" && plates.length>=8) ||
            (!["import","add_plate"].includes(tool.target) && !objects.length)}
          onClick={event => selectTool(tool,event)}><SlicerUiIcon name={tool.icon || "others"} size={22}/><span className="slicerToolButtonLabel">{TOOL_SHORT_LABELS[tool.name] || tool.name}</span></button>
        {tool.target === "import" && addModelMenuOpen && (
          toolPopupStyle?.position === "fixed"
            ? createPortal(
                <div className="slicerAddModelOverlay" role="presentation"
                  onMouseDown={event => { if (event.target === event.currentTarget) setAddModelMenuOpen(false); }}>
                  {addModelMenu}
                </div>,
                document.body
              )
            : addModelMenu
        )}
        {tool.target === "auto_orient" && autoOrientMenuOpen && <div className="slicerToolOptions slicerAutoOrientMenu" style={toolPopupStyle} id="slicer-auto-orient-toolbar-options" role="group" aria-label="Auto-orient choices">
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
        </div>}
      </div>)}
      <div className="slicerToolbarDescriptor" role="status" aria-live="off">{toolDescriptor || "\u00a0"}</div>
    </div>
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
          <div>
            <button type="button" disabled={!canEdit || busy || selectedModels.length < 2}
              onClick={assembleSelected}>Assemble selection</button>
            <button type="button" disabled={!canEdit || busy || !activeAssembly}
              onClick={disassembleSelected}>Disassemble</button>
            <button type="button" disabled={!canEdit||busy||!removableAssemblyMembers.length}
              onClick={removeSelectedFromAssembly}>Remove selected from assembly</button>
          </div>
        </div>}
        {selectedModels.length>0 && plates.length>1 && <div className="slicerMoveToPlate">
          <label>Move {selectedModels.length} selected to plate
            <select value={movePlateTarget}
              onChange={event=>setMovePlateTarget(event.target.value)}>
              <option value="">Choose destination</option>
              {plates.filter(p=>p.id!==activePlateId).map(p=>
                <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <button type="button" disabled={!canEdit||busy||!movePlateTarget}
            onClick={()=>{
              onMoveModelsToPlate?.(selectedModels.map(item=>item.instance_id),movePlateTarget);
              setSelectedIds([]);setSelectedId("");setMovePlateTarget("");
            }}>Move models</button>
        </div>}
        {modelTreeRows.map((object, index) => {
          const assembly = object.assembly_id;
          const members = assembly ? objects.filter(row=>row.assembly_id===assembly) : [];
          const firstMember = assembly && members[0]?.instance_id===object.instance_id;
          const expanded = assembly && expandedAssemblies.includes(assembly);
          return <React.Fragment key={object.instance_id}>
          {firstMember && <div className="slicerAssemblyTreeHeader">
            <button type="button" className={members.every(row=>validSelection.includes(row.instance_id))?"selected":""}
              aria-label={"Select assembly of "+members.length+" parts"}
              onClick={event=>selectMultiple(object.instance_id,event.ctrlKey||event.metaKey||event.shiftKey)}>
              <SlicerUiIcon name="models"/> Assembly · {members.length} parts
            </button>
            <button type="button" aria-expanded={!!expanded} aria-label={expanded?"Collapse assembly":"Expand assembly"}
              onClick={()=>setExpandedAssemblies(current=>expanded?
                current.filter(id=>id!==assembly):[...current,assembly])}>
              {expanded?"−":"+"}
            </button>
          </div>}
          {(!assembly || expanded) && <div className={"slicerPrepareModelEntry"+(assembly?" slicerAssemblyTreePart"+(members.at(-1)?.instance_id===object.instance_id?" slicerAssemblyTreeLast":""):"")}>
          <button type="button"
            className={validSelection.includes(object.instance_id) ? "selected" : ""}
            onClick={event => selectMultiple(object.instance_id, event.ctrlKey || event.metaKey || event.shiftKey, !!assembly)}
            aria-pressed={validSelection.includes(object.instance_id)}>
            {(() => {
              const mapping = object.material_slot;
              const samePrinter = mapping && String(mapping.printer_id) === String(printerId);
              const liveSlot = samePrinter ? liveMaterials.find(slot =>
                String(slot.id) === String(mapping.slot_id)) : null;
              const rawMaterial = liveSlot?.material || "";
              const material = /^([A-Z]{2,6})(?:[- /]|$)/i.exec(rawMaterial.trim())?.[1]?.toUpperCase()
                || rawMaterial.trim().slice(0, 5).toUpperCase() || "";
              const slotNumber = mapping && Number.isInteger(Number(mapping.slot_index))
                ? Number(mapping.slot_index) + 1 : null;
              const status = !mapping ? "No printer slot assigned"
                : !samePrinter ? "Assigned to a different printer — reassign before printing"
                : !liveSlot ? "Assigned slot is no longer loaded — recheck before printing"
                : "Intended slot: " + slotName(liveSlot) + " (draft mapping only)";
              return <>
                <span className="slicerPrepareModelSwatch slicerPrepareMaterialSwatch"
                  style={{ background: object.color, color: materialTextColor(object.color) }}
                  title={liveSlot ? (rawMaterial || "Unknown material") : "Model preview colour"}
                  aria-hidden="true">{material}</span>
                <span className="slicerPrepareModelName">{index + 1}. {itemName(object)}</span>
                {mapping && <span className={"slicerPrepareSlotBadge"+(samePrinter && liveSlot ? "" : " stale")}
                  title={status} aria-hidden="true">{slotNumber ?? "?"}</span>}
                <span className="sr-only">{status}</span>
              </>;
            })()}
          </button>
          {object.text_model && <button type="button" className="slicerModelEditText"
            disabled={!canEdit || busy} onClick={()=>{
              selectSingle(object.instance_id);
              setMobilePane("plate");
              setSolidRequest({kind:"text",editTargetId:object.instance_id,
                id:Date.now()+Math.random()});
            }}>Edit text</button>}
          <button type="button" className="slicerModelChangeFilament"
            disabled={!canEdit || busy || (!liveMaterials.length && !object.material_slot)}
            aria-expanded={filamentPickerId === object.instance_id}
            onClick={() => {
              setSelectedId(object.instance_id);
              setFilamentPickerId(current => current === object.instance_id ? "" : object.instance_id);
              setFilamentNotice("");
            }}>Change filament</button>
          {filamentPickerId === object.instance_id && <div className="slicerModelFilamentChoices">
            <strong>Loaded printer slots · intended mapping only</strong>
            {!liveMaterials.length && <small>No loaded slots reported. An existing assignment can still be cleared.</small>}
            {liveMaterials.map(slot => <button type="button" key={slot.id}
              disabled={!canEdit || busy}
              onClick={() => changeModelPreviewFilament(object.instance_id, slot)}>
              <span className="slicerLiveMaterialSwatch"
                style={{ backgroundColor: validSlotColor(slot) || "#697b91" }} aria-hidden="true" />
              <span>{slotName(slot)}</span>
            </button>)}
            {object.material_slot && <button type="button" disabled={!canEdit||busy}
              onClick={() => clearModelFilament(object.instance_id)}>Clear intended slot</button>}
          </div>}
        </div>}
        </React.Fragment>})}
        {filamentNotice && <p className="slicerModelFilamentNotice" role="status">{filamentNotice}</p>}
        </aside>
        <section className="slicerLiveMaterialSlots" aria-label="Loaded printer filament slots">
          <div className="slicerLiveMaterialHeader"><strong>Loaded printer filaments</strong>
            <button type="button" disabled={materialRefreshing || !printerId} onClick={refreshPrinterMaterials}>
              {materialRefreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          {liveMaterials.map(slot => {
            const chosen=slotFilamentProfiles.find(row=>row.slot_id===String(slot.id));
            const profile=filamentProfiles.find(row=>row.id===chosen?.profile_id);
            const suggestion=slotMatch(slot);
            return <div className="slicerLiveMaterialSlot slicerLiveMaterialSlotCompact" key={slot.id}>
              <span className="slicerLiveMaterialSwatch slicerLiveMaterialSwatchRound"
                style={{backgroundColor:validSlotColor(slot)||"#697b91"}} aria-hidden="true"/>
              <div className="slicerLiveMaterialSummary">
                <strong title={slot.product_name || slot.material || "Unknown filament"}>
                  {slot.product_name || slot.material || "Unknown filament"}</strong>
                <small>Slot {(slot.slot_index??0)+1} · {slot.material||"Unknown"}</small>
                {resolveSlotLibrarySpool(slot,spools).spool && <small>Matched MakerVault spool · {resolveSlotLibrarySpool(slot,spools).spool.spool_id}</small>}
                <small>{profile ? "Profile: " + profile.name
                  : suggestion.level === "exact" ? "Matching installed profile found"
                  : suggestion.level === "ambiguous" ? "Multiple matching profiles — choose one"
                  : suggestion.level === "fallback" ? "Similar installed profiles available for review"
                  : "No matching native profile installed"}</small>
              </div>
              <div className="slicerLiveMaterialActions">
                <button type="button" onClick={()=>setDetailsSlotId(String(slot.id))}
                  aria-label={"Details for "+slotName(slot)}>Details</button>
                <button type="button" disabled={!canEdit||busy}
                  onClick={()=>setEditingSlotProfile(String(slot.id))}
                  aria-label={"Choose filament profile for "+slotName(slot)}>Profile</button>
              </div>
              {!profile && suggestion.suggestions.length > 0 && <div className="slicerSlotProfileSuggestions">
                <label>Suggested native profile
                  <select value="" disabled={!canEdit || busy} onChange={event => {
                    const id=event.target.value;
                    if (!id) return;
                    setSuppressedSlotMatches(current => current.filter(row => row !== String(slot.id)));
                    onSlotFilamentProfilesChange?.([
                      ...slotFilamentProfiles.filter(row=>String(row.slot_id)!==String(slot.id)),
                      {slot_id:String(slot.id),profile_id:id},
                    ]);
                  }}>
                    <option value="">Review profile match…</option>
                    {suggestion.suggestions.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}
                  </select>
                </label>
              </div>}
              {!profile && lookupEngine === "orcaslicer" && <div className="slicerSlotProfileSuggestions">
                {slotOfficialError && <small role="alert" className="formError">{slotOfficialError}</small>}
                <button type="button" disabled={slotOfficialBusy === String(slot.id) || slotImportBusy || !canEdit}
                  onClick={() => findOfficialSlotProfiles(slot)}>
                  {slotOfficialBusy === String(slot.id) ? "Searching…" : "Find official profiles"}
                </button>
                {slotOfficialSearched[String(slot.id)] && <div>
                  {!(slotOfficialResults[String(slot.id)] || []).length && <small>No matching profiles found.</small>}
                  {(slotOfficialResults[String(slot.id)] || []).length > 0 && <>
                    <label>Available profiles
                      <select value={slotOfficialSelections[String(slot.id)] || ""}
                        onChange={event => setSlotOfficialSelections(current =>
                          ({...current,[String(slot.id)]:event.target.value}))}>
                        <option value="">Choose profile…</option>
                        {(slotOfficialResults[String(slot.id)] || []).map(row =>
                          <option key={row.vendor+":"+row.sub_path} value={row.vendor+":"+row.sub_path}>
                            {row.name} ({row.vendor})
                          </option>)}
                      </select>
                    </label>
                    <button type="button" disabled={slotImportBusy || !slotOfficialSelections[String(slot.id)]}
                      onClick={() => {
                        const selected=(slotOfficialResults[String(slot.id)] || []).find(row =>
                          row.vendor+":"+row.sub_path === slotOfficialSelections[String(slot.id)]);
                        if (selected) importOfficialSlotProfile(slot,selected);
                      }}>Import & assign</button>
                  </>}
                </div>}
              </div>}
            </div>;
          })}
          {detailsSlotId && createPortal(<div className="slicerFlushModalBackdrop"
            onMouseDown={e=>{if(e.target===e.currentTarget)setDetailsSlotId(null);}}>
            <section className="slicerFlushModal slicerSlotProfileModal" role="dialog"
              aria-modal="true" aria-label="Loaded filament details">
              <header className="slicerFlushModalHeader">
                <h3>Loaded filament details</h3>
                <button type="button" onClick={()=>setDetailsSlotId(null)} aria-label="Close filament details">✕</button>
              </header>
              <div className="slicerFlushModalBody">
                {liveMaterials.filter(slot=>String(slot.id)===detailsSlotId).map(slot=>{
                  const chosen=slotFilamentProfiles.find(row=>row.slot_id===String(slot.id));
                  const profile=filamentProfiles.find(row=>row.id===chosen?.profile_id);
                  return <div key={slot.id} className="slicerSlotDetails">
                    <div className="slicerFlushSlotLabel"><span className="slicerLiveMaterialSwatch slicerLiveMaterialSwatchRound"
                      style={{backgroundColor:validSlotColor(slot)||"#697b91"}}/>
                      <strong>{slot.product_name||slot.material||"Unknown filament"}</strong></div>
                    <p>{slot.system_label||"Printer material"} · Slot {(slot.slot_index??0)+1}</p>
                    <p>{slot.spool_code||"Unlinked spool"}</p>
                    <p>Material: {slot.material||"Unknown"}</p>
                    <p>Remaining: {slot.remaining_percent==null?"Not reported":Math.round(slot.remaining_percent)+"%"}</p>
                    <p>Filament profile: {profile?.name||"Not assigned"}</p>
                    <button type="button" onClick={()=>{setDetailsSlotId(null);setEditingSlotProfile(String(slot.id));}}>
                      Change filament profile</button>
                  </div>;
                })}
              </div>
              <footer className="slicerFlushModalFooter">
                <button type="button" onClick={()=>setDetailsSlotId(null)}>Done</button>
              </footer>
            </section>
          </div>,document.body)}
          {editingSlotProfile && createPortal(<div className="slicerFlushModalBackdrop"
             onMouseDown={e=>{if(e.target===e.currentTarget)setEditingSlotProfile(null);}}>
            <section className="slicerFlushModal slicerSlotProfileModal" role="dialog"
              aria-modal="true" aria-label="Choose per-slot filament profile">
              <header className="slicerFlushModalHeader"><h3>Slot filament profile</h3>
                <button type="button" onClick={()=>setEditingSlotProfile(null)}>✕</button>
              </header>
              <div className="slicerFlushModalBody">
                <p className="projectUploadHint">Choose an imported native filament preset for this slot.
                  A single assigned slot's native preset is used automatically when slicing. Physical multi-slot tool routing still requires validation.</p>
                <label>Native filament preset
                  <select value={slotFilamentProfiles.find(row=>row.slot_id===editingSlotProfile)?.profile_id||""}
                    onChange={e=>{
                      const updated=slotFilamentProfiles.filter(row=>row.slot_id!==editingSlotProfile);
                      if(e.target.value) {
                        setSuppressedSlotMatches(current => current.filter(row => row !== editingSlotProfile));
                        updated.push({slot_id:editingSlotProfile,profile_id:e.target.value});
                      } else {
                        // Respect an explicit clear; never silently reuse the main preset.
                        setSuppressedSlotMatches(current => [...new Set([...current,editingSlotProfile])]);
                      }
                      onSlotFilamentProfilesChange?.(updated);
                    }}>
                    <option value="">No slot profile selected · slicing blocked when this slot is assigned</option>
                    {filamentProfiles.map(profile=><option key={profile.id} value={profile.id}>
                      {profile.name}
                    </option>)}
                  </select>
                </label>
                {!filamentProfiles.length&&<p className="projectUploadHint">No native filament presets are installed for this slicer engine and version. Find an official preset below.</p>}
                {lookupEngine === "orcaslicer" && liveMaterials.filter(slot => String(slot.id) === editingSlotProfile).map(slot =>
                  <div key={slot.id} className="slicerSlotProfileSuggestions">
                    <button type="button" disabled={!canEdit || busy || slotImportBusy || slotOfficialBusy === String(slot.id)}
                      onClick={() => findOfficialSlotProfiles(slot)}>
                      {slotOfficialBusy === String(slot.id) ? "Searching…" : "Find official profiles"}
                    </button>
                    {slotOfficialSearched[String(slot.id)] && <>
                      {!(slotOfficialResults[String(slot.id)] || []).length && <p className="projectUploadHint">No matching official filament presets were found.</p>}
                      {!!(slotOfficialResults[String(slot.id)] || []).length && <>
                        <label>Available official profiles
                          <select value={slotOfficialSelections[String(slot.id)] || ""}
                            disabled={slotImportBusy || !canEdit}
                            onChange={event => setSlotOfficialSelections(current => ({...current,[String(slot.id)]:event.target.value}))}>
                            <option value="">Choose official profile…</option>
                            {(slotOfficialResults[String(slot.id)] || []).map(row =>
                              <option key={row.vendor+":"+row.sub_path} value={row.vendor+":"+row.sub_path}>
                                {row.name} ({row.vendor})
                              </option>)}
                          </select>
                        </label>
                        <button type="button" disabled={!canEdit || slotImportBusy || !slotOfficialSelections[String(slot.id)]}
                          onClick={() => {
                            const candidate = (slotOfficialResults[String(slot.id)] || []).find(row =>
                              row.vendor+":"+row.sub_path === slotOfficialSelections[String(slot.id)]);
                            if (candidate) importOfficialSlotProfile(slot,candidate);
                          }}>
                          {slotImportBusy ? "Importing…" : "Import & assign"}
                        </button>
                      </>}
                    </>}
                    {slotOfficialError && <p className="formError" role="alert">{slotOfficialError}</p>}
                  </div>
                )}
              </div>
              <footer className="slicerFlushModalFooter">
                <button type="button" onClick={()=>setEditingSlotProfile(null)}>Done</button>
              </footer>
            </section>
          </div>,document.body)}
          <p role="status">{materialMessage}</p>
          {slotOfficialError && <p role="alert">{slotOfficialError}</p>}
          <SlicerFlushVolumes slots={liveMaterials} value={flushSettings}
            processProfileId={selectedProfiles?.process_id}
            onChange={onFlushSettingsChange} disabled={!canEdit || busy} />
        </section>

      </div>
      <div id="slicer-prepare-plate" className="slicerPrepareScene" ref={editorRef} aria-labelledby="slicer-mobile-tab-plate">
      <div className="slicerPlateProjectNav" role="group" aria-label="Project build plates">
        <div className="slicerPlateProjectTabs">
          {plates.length>1 && <button type="button"
            className={showAllPlates?"active":""} aria-pressed={showAllPlates}
            onClick={()=>setShowAllPlates(true)}><SlicerUiIcon name="plates-overview" size={16}/> All plates</button>}
          {plates.map((item,index)=><button key={item.id} type="button"
            className={!showAllPlates&&item.id===activePlateId?"active":""}
            aria-current={item.id===activePlateId?"true":undefined}
            onClick={()=>{setShowAllPlates(false);onChoosePlate?.(item.id);}}>
            {item.name || "Plate "+(index+1)}
            <span className="slicerPlateProjectCount">{item.objects.length}</span>
          </button>)}
        </div>
        <button type="button" onClick={()=>{setShowAllPlates(false);onAddPlate?.();}} disabled={!canEdit||busy||plates.length>=8}
          aria-label="Add build plate" title="Add a new empty build plate">+ Plate</button>
        <button type="button" onClick={()=>onRemovePlate?.(activePlateId)}
          disabled={!canEdit||busy||plates.length<=1}
          aria-label="Remove active build plate">Remove</button>
      </div>

        {toolMode === "lay_face" && <p className="projectUploadHint" role="status">
          <strong>Lay on face:</strong> Tap or click the model face you want touching the build plate.
          MakerVault will rotate the model and place it back on the bed. Select the tool again to cancel.
        </p>}
        {showAllPlates && plates.length>1 ? <section className="slicerAllPlates" aria-label="All build plates overview">
          <div className="slicerAllPlatesHeading">
            <strong>All build plates</strong>
            <span>{plates.length} plates · {plates.reduce((sum,item)=>sum+item.objects.length,0)} models</span>
          </div>
          <div className="slicerAllPlatesGrid">
            {plates.map((entry,index)=>{
              const width=Number(plate?.size_mm?.[0])||260;
              const depth=Number(plate?.size_mm?.[1])||260;
              return <button type="button" key={entry.id}
                className="slicerAllPlatesCard"
                onClick={()=>{setShowAllPlates(false);onChoosePlate?.(entry.id);}}
                aria-label={"Edit "+entry.name+", "+entry.objects.length+" models"}>
                <span className="slicerAllPlatesCardTitle">
                  <strong>{index+1}. {entry.name}</strong>
                  <small>{entry.objects.length} models</small>
                </span>
                <svg viewBox="0 0 260 260" role="img"
                  aria-label={"Top-down plate placements for "+entry.name}>
                  <rect x="5" y="5" width="250" height="250" rx="5" fill="#293744" stroke="#6eaac5" strokeWidth="2"/>
                  {Array.from({length:9},(_,line)=>
                    <React.Fragment key={line}>
                      <path d={`M${30+line*25} 5V255`} stroke="#506478" strokeWidth=".5"/>
                      <path d={`M5 ${30+line*25}H255`} stroke="#506478" strokeWidth=".5"/>
                    </React.Fragment>)}
                  {entry.objects.map((item,itemIndex)=>{
                    const x=130+Number(item.x_mm||0)*250/width;
                    const y=130-Number(item.y_mm||0)*250/depth;
                    const angle=-Number(item.rotation_deg||0);
                    return <g key={item.instance_id}
                      transform={`translate(${Math.max(8,Math.min(252,x))} ${Math.max(8,Math.min(252,y))}) rotate(${angle})`}>
                      <rect x="-9" y="-9" width="18" height="18" rx="2"
                        fill={/^#[0-9a-f]{6}$/i.test(item.color||"")?item.color:"#8c80d9"}
                        stroke="#e8f3ff" strokeWidth="1" opacity=".88"/>
                      {itemIndex<25&&<text x="0" y="3" textAnchor="middle" fontSize="8" fill="#111827">{itemIndex+1}</text>}
                    </g>;
                  })}
                </svg>
                <span className="slicerAllPlatesOpen">Open plate for editing</span>
              </button>;
            })}
          </div>
        </section> : <SlicerPlateEditor key={activePlateId} plateIndex={Math.max(0,plates.findIndex(item=>item.id===activePlateId))} plateCount={plates.length||1} toolbar={modelToolbar} paintControls={variableLayerPanel || paintPanel} files={files} localAssets={localAssets}
          onLocalAssetsChange={onLocalAssetsChange} onPlateIssuesChange={onPlateIssuesChange} objects={objects} onChange={updatePlate}
          colourPaintOptions={{mode:paintMode,slot:paintErase?null:(isSupportPainting?supportSlot:isSeamPainting?seamSlot:isFuzzyPainting?0:paintSlot),palette:paintPalette,
            radiusMm:paintBrushMm,angleDeg:paintAngle,minHeightMm:paintHeight[0],maxHeightMm:paintHeight[1],
            supportOverhangsOnly:supportOverhangsOnly,supportOverhangAngle:supportOverhangAngle}}
          onColourPaintHeightPick={z=>{
            if(!paintHeightFollow)return;
            setPaintHeight(([lower,upper])=>{
              const low=Math.max(0,Math.round(z*2)/2);
              const high=Math.round((low+paintHeightRange)*2)/2;
              return low===lower && high===upper?[lower,upper]:[low,high];
            });
          }}
          variableLayerPreview={toolMode==="variable_layers" ? variableBandDraft : null}
          onVariableLayerHeightPick={z=>{
            if(!variableBandFollow)return;
            const mm=Math.max(0,Math.round(z*2)/2);
            setVariableBandDraft(current=>{
              if(variableBandTarget==="from"){
                const span=Math.max(.5,current.to_mm-current.from_mm);
                const next={...current,from_mm:mm,to_mm:Math.min(1000,Math.round((mm+span)*2)/2)};
                return next.from_mm===current.from_mm&&next.to_mm===current.to_mm?current:next;
              }
              const next={...current,to_mm:Math.max(current.from_mm+.5,mm)};
              return next.to_mm===current.to_mm?current:next;
            });
          }}
          onVariableLayerHeightCommit={()=>setVariableBandFollow(false)}
          onColourPaintError={setPaintError}
          onPrimaryChange={onPrimaryChange} onFilesUploaded={onFilesUploaded}
          onManualColorChange={onManualColorChange} defaultColor={defaultColor}
          plate={plate} plateType={plateType} plateLabel={plateLabel}
          printerLabel={selectedProfiles?.printer || printerDetails?.model || printerDetails?.name || ""}
          onPlateLabelChange={onPlateLabelChange} canEdit={canEdit && !busy} toolMode={toolMode} selectedInstanceId={selectedId}
          autoOrientGoal={autoOrientGoal} autoOrientRequest={autoOrientRequest}
          splitRequest={splitRequest} solidRequest={solidRequest}
          selectedInstanceIds={validSelection} onSelectModel={selectMultiple}
          onSelectedInstanceChange={selectSingle} measurementVisible={measurementVisible}
          measureMode={measureMode} measureUnit={measureUnit} measureSnapMode={measureSnapMode}
          measureClearVersion={measureClearVersion}
          onMeasureModeChange={setMeasureMode} onMeasureSnapModeChange={setMeasureSnapMode}
          onMeasureUnitChange={setMeasureUnit}
          onMeasureClear={() => setMeasureClearVersion(value => value + 1)}
          onMeasureFinish={() => setMeasurementVisible(false)}
          onExitToolMode={() => setToolMode("select")} />}
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
        {objects.some(item => (item.support_paint?.regions || []).length > 0) &&
          engineCapabilities.support_paint?.status === "test_only" &&
          <p className="slicerActionStatus" role="status">
            Support painting is an offline OrcaSlicer 2.5.0 test. Use a single
            upright, unscaled model and check that support generation is enabled
            in the process profile. Inspect support toolpaths before printing;
            printer submission is disabled for experimental G-code.
          </p>}
        {objects.some(item => (item.variable_layer_profile?.bands || []).length > 0) &&
          engineCapabilities.variable_layer_profile?.status === "test_only" &&
          <p className="slicerActionStatus" role="status">
            Variable layer height is an offline OrcaSlicer test. Use one upright, unscaled
            model. Generated G-code cannot be uploaded or printed until its actual layer
            transitions have passed native verification.
          </p>}
        {incompatibleEdits.length > 0 && <p className="slicerActionStatus" role="status">
          Saved edits require verified native export: {incompatibleEdits.map(key => FEATURE_NAMES[key]).join(", ")}.
          None will be silently discarded from generated G-code.
        </p>}
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
          {conflictsBlockSlice
            ? <button type="button" onClick={() => {
              setMobilePane("plate");
              editorRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
            }}>Review build plate</button>
            : <button type="button" onClick={onChangeProfiles}>Check profiles and engine</button>}
        </p>}
      </div>
      <div className="settingsActions">
        {plates.length>1 && <p className="slicerPlateSliceScope" role="status">
          Save draft and project export preserve all {plates.length} plates. The main Slice button uses <strong>{plateLabel}</strong>.
        </p>}
        <button type="button" disabled={!plateReady || !profilesReady} onClick={onSaveDraft}>Save draft</button>
        <button type="button" disabled={!plateReady || !profilesReady} onClick={onSaveProject}>Save project (.3mf)</button>
        {multiMaterialReadyForExport && <button type="button"
          disabled={!activePlateReady || !profilesReady || busy}
          onClick={onExportNativeMaterials}
          title="Download an Orca-compatible 3MF; the backend detects the printer material system and derives tool order. Printing remains disabled until physical changeovers are verified.">
          Export multi-material 3MF (offline)
        </button>}
        {multiMaterialReadyForExport && <button type="button"
          disabled={!activePlateReady || !profilesReady || !workerConfigured || busy ||
                    conflictsBlockSlice || objectSettingsPending}
          onClick={onSliceMultimaterialTest}
          title="Generate an audited multi-colour Orca G-code test. Printer upload and print start are intentionally blocked.">
          Slice multi-colour (test)
        </button>}
        <label className="slicerProjectImportButton" aria-label="Open project from 3MF file">
          Open project (.3mf)
          <input type="file" accept=".3mf" disabled={!canEdit||busy}
            onChange={event=>{
              const file=event.target.files?.[0];
              event.target.value="";
              if(file)onImportProject?.(file);
            }}/>
        </label>
        <div className="slicerSliceSplit">
          <button type="button" className="primary"
            disabled={!activePlateReady || !profilesReady || !workerConfigured || conflictsBlockSlice || objectSettingsPending || materialRoutingPending}
            onClick={onSlice}>Slice</button>
          <button type="button" aria-label="More slicing options"
            aria-haspopup="menu" aria-expanded={sliceMenuOpen}
            disabled={!plateReady || !profilesReady || !workerConfigured}
            onClick={()=>setSliceMenuOpen(value=>!value)}>▾</button>
          {sliceMenuOpen && <div className="slicerSliceMenu" role="menu">
            <button type="button" role="menuitem"
              disabled={!activePlateReady || conflictsBlockSlice || objectSettingsPending || materialRoutingPending}
              onClick={()=>{setSliceMenuOpen(false);onSlice?.();}}>Slice active plate</button>
            <button type="button" role="menuitem"
              disabled={!projectHasModels || objectSettingsPending || projectRoutingPending}
              onClick={()=>{setSliceMenuOpen(false);onSliceAll?.();}}>
              Slice all plates ({plates.filter(plate=>plate.objects.length).length})
            </button>
          </div>}
        </div>
      </div>
    </div>
  </section>;
}
