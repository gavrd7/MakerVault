import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import { FileModelViewerModal, ModelThumbnail } from "./ModelViewer";
import PrinterStartGcodeModal from "./PrinterStartGcodeModal";
import GcodeViewerModal from "./GcodeViewerModal";
import SlicerPlateEditor from "./SlicerPlateEditor";
import SlicerPrepareWorkspace from "./SlicerPrepareWorkspace";
import SlicerEngineChoices from "./SlicerEngineChoices";
import { slicerSpoolHex, recolorUnmodifiedPlate } from "./slicerSpoolColour";
import SlicerSpoolPicker from "./SlicerSpoolPicker";
import { spoolMaterial, chooseSuggestedProfile, defaultOfficialSearch, suggestOfficialVendor } from "./slicerProfileSuggestions";
import { availableSlicerPrintConnections, preferredSlicerPrintConnection } from "./slicerPrintRouting";

function ProfileActionIcon({ name }) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none"
    stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true">
    {name === "search" && <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>}
    {name === "upload" && <><path d="M12 16V3m-5 5 5-5 5 5" /><path d="M4 16v4h16v-4" /></>}
    {name === "bookmark" && <path d="M6 3h12v18l-6-4-6 4V3Z" />}
    {name === "settings" && <><circle cx="12" cy="12" r="3" /><path d="M12 2v3m0 14v3M2 12h3m14 0h3M4.93 4.93l2.12 2.12m9.9 9.9 2.12 2.12m0-14.14-2.12 2.12m-9.9 9.9-2.12 2.12" /></>}
  </svg>;
}

const initialForm = {
  engine: "orcaslicer", engine_version: "", input_asset_id: "", printer_id: "",
  spool_id: "", printer_preset: "", filament_preset: "", process_preset: "",
  nozzle_mm: "0.40", plate: "default",
  printer_profile_id: "", filament_profile_id: "", process_profile_id: "",
};

/**
 * Safe preparation-only entry point. A verified slicing worker, real engine-native
 * profile IDs and isolated execution are required before enabling a Slice action.
 */
export default function SlicerWorkbench({ files = [], printers = [], spools = [], canPrepare = false, canPrint = false, onBack, onOpenGcode, onFilesUploaded, initialDraftId = null }) {
  const [form, setForm] = useState(initialForm);
  const [engines, setEngines] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [profileModal, setProfileModal] = useState("");
  const [managingSavedProfiles, setManagingSavedProfiles] = useState(false);
  const [showProfileDependencies, setShowProfileDependencies] = useState(false);
  const [editingProfile, setEditingProfile] = useState(null);
  const [editProfileName, setEditProfileName] = useState("");
  const [editProfileSchema, setEditProfileSchema] = useState({});
  const [editProfileValues, setEditProfileValues] = useState({});
  const [editProfileBusy, setEditProfileBusy] = useState(false);
  const [editProfileError, setEditProfileError] = useState("");
  const [showDrafts, setShowDrafts] = useState(false);
  const [previewJobId, setPreviewJobId] = useState(null);
  const awaitingSlicePreviewRef = useRef(null);
  const [customBed, setCustomBed] = useState({ enabled: false, x: "220", y: "220" });
  const [profileLineages, setProfileLineages] = useState({});
  const [workerConfigured, setWorkerConfigured] = useState(false);
  const [canVerifyProfiles, setCanVerifyProfiles] = useState(false);
  const [verifyingProfiles, setVerifyingProfiles] = useState(false);
  const [mayCancel, setMayCancel] = useState(false);
  const [mayDeleteDraft, setMayDeleteDraft] = useState(false);
  const [printSelection, setPrintSelection] = useState(null);
  const [previewFile, setPreviewFile] = useState(null);
  const [plateObjects, setPlateObjects] = useState([]);
  // Keep temporary STL filenames and preview URLs when switching between
  // the setup plate and the interactive editor.
  const [plateLocalAssets, setPlateLocalAssets] = useState([]);
  const localAssetsRef = useRef([]);
  localAssetsRef.current = plateLocalAssets;
  useEffect(() => () => {
    localAssetsRef.current.forEach(asset => {
      if (asset.url?.startsWith("blob:")) URL.revokeObjectURL(asset.url);
    });
  }, []);
  const [editorOpen, setEditorOpen] = useState(false);
  const openedDraftRef = useRef(null);
  const manuallyColouredModels = useRef(new Set());
  const manuallyChosenProfiles = useRef(new Set());
  const [profileSuggestions, setProfileSuggestions] = useState({});
  const [nativePlate, setNativePlate] = useState(null);
  const [importFile, setImportFile] = useState(null);
  const [importKind, setImportKind] = useState("printer");
  const [officialQuery, setOfficialQuery] = useState("");
  const [officialVendor, setOfficialVendor] = useState("");
  const [officialVendors, setOfficialVendors] = useState([]);
  const [officialSourceInfo, setOfficialSourceInfo] = useState(null);
  const [officialResults, setOfficialResults] = useState(null);
  const [materialProfileMatches, setMaterialProfileMatches] = useState(null);
  const [officialBusy, setOfficialBusy] = useState(false);
  const [officialError, setOfficialError] = useState("");
  const [officialImportNotice, setOfficialImportNotice] = useState("");
  const [officialModels, setOfficialModels] = useState([]);
  const [officialModel, setOfficialModel] = useState("");
  const [officialManualModel, setOfficialManualModel] = useState("");
  const [officialModelsBusy, setOfficialModelsBusy] = useState(false);
  const [importName, setImportName] = useState("");
  const [importSource, setImportSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const stlFiles = useMemo(() => {
    const visible = files.filter(file => file.category === "mesh" && /\.stl$/i.test(file.filename || file.name || ""));
    const hidden = jobs.flatMap(job => job.temporary_inputs || []);
    return [...visible, ...hidden.filter(file => !visible.some(item => String(item.id) === String(file.id)))
      .filter((file, index, all) => all.findIndex(item => String(item.id) === String(file.id)) === index)];
  }, [files, jobs]);

  const update = (name, value) => setForm(current => {
    if (name === "engine" || name === "engine_version") return {
      ...current, [name]: value,
      printer_profile_id: "", filament_profile_id: "", process_profile_id: "",
    };
    if (name.endsWith("_preset")) return {
      ...current, [name]: value,
      [name.replace("_preset", "_profile_id")]: "",
    };
    return { ...current, [name]: value };
  });
  const forKind = kind => profiles.filter(profile =>
    profile.engine === form.engine && profile.engine_version === form.engine_version &&
    profile.kind === kind && !profile.is_dependency
  );
  const selectNativeProfile = (kind, id) => {
    manuallyChosenProfiles.current.add(kind);
    const profile = profiles.find(item => item.id === id);
    setForm(current => ({
      ...current,
      [kind + "_profile_id"]: id,
      ...(profile ? { [kind + "_preset"]: profile.name } : {}),
    }));
  };
  const changeSessionPrinter = printerId => {
    const printer = printers.find(item => String(item.id) === String(printerId));
    // A changed physical printer must never silently reuse the previous
    // machine's verified native presets or nozzle geometry.
    manuallyChosenProfiles.current.clear();
    setProfileSuggestions({});
    setForm(current => ({
      ...current,
      printer_id: String(printerId),
      nozzle_mm: String(printer?.nozzle_mm || "0.40"),
      printer_profile_id: "", filament_profile_id: "", process_profile_id: "",
      printer_preset: "", filament_preset: "", process_preset: "",
    }));
    setError("");
    setNotice("Printer selection changed. Choose compatible native profiles for the new printer before saving or slicing.");
  };
  const selectedPrinter = printers.find(item => String(item.id) === form.printer_id);
  const selectedSpool = spools.find(item => String(item.id) === String(form.spool_id));
  const selectedSpoolHex = slicerSpoolHex(selectedSpool);
  const materialHint = spoolMaterial(selectedSpool);

  // Reconcile only selections the user has not explicitly changed. Defaults
  // are scoped to the exact worker engine/version; printer suggestions must
  // match the selected machine and filament must match the physical material.
  useEffect(() => {
    if (loading || !profiles.length || !form.engine_version) return;
    const next = {};
    const reasons = {};
    for (const kind of ["printer", "filament", "process"]) {
      if (manuallyChosenProfiles.current.has(kind)) continue;
      const suggestion = chooseSuggestedProfile(profiles.filter(profile => !profile.is_dependency), jobs, {
        engine: form.engine, version: form.engine_version, kind,
        printer: selectedPrinter, nozzle: form.nozzle_mm,
        material: kind === "filament" ? materialHint : "",
      });
      if (suggestion) {
        next[kind] = suggestion.profile;
        reasons[kind] = suggestion.reason;
      }
    }
    setProfileSuggestions(reasons);
    if (!Object.keys(next).length) return;
    setForm(current => {
      let changed = false;
      const updated = { ...current };
      for (const [kind, profile] of Object.entries(next)) {
        if (current[kind + "_profile_id"] !== profile.id ||
            current[kind + "_preset"] !== profile.name) {
          updated[kind + "_profile_id"] = profile.id;
          updated[kind + "_preset"] = profile.name;
          changed = true;
        }
      }
      return changed ? updated : current;
    });
  }, [loading, profiles, jobs, form.engine, form.engine_version, form.printer_id,
      form.nozzle_mm, form.spool_id, materialHint, selectedPrinter?.id]);


  useEffect(() => {
    if (!materialHint || !["orcaslicer", "crealityprint"].includes(form.engine)) {
      setMaterialProfileMatches(null);
      return undefined;
    }
    let active = true;
    setMaterialProfileMatches({ material: materialHint, loading: true });
    const params = new URLSearchParams({
      engine: form.engine, kind: "filament", vendor: "Creality", q: materialHint,
    });
    apiFetch("/api/printing/slicer/official-profiles/?" + params)
      .then(result => {
        if (active) setMaterialProfileMatches({ material: materialHint, results: result });
      })
      .catch(() => {
        if (active) setMaterialProfileMatches({ material: materialHint, unavailable: true });
      });
    return () => { active = false; };
  }, [form.engine, materialHint]);

  function chooseSpool(id) {
    const spool = spools.find(item => String(item.id) === String(id));
    const hex = slicerSpoolHex(spool);
    const materialChanged = spoolMaterial(selectedSpool) !== spoolMaterial(spool);
    if (materialChanged) manuallyChosenProfiles.current.delete("filament");
    setForm(current => ({
      ...current, spool_id: id,
      ...(materialChanged ? { filament_profile_id: "", filament_preset: "" } : {}),
    }));
    // Never overwrite per-object colours explicitly edited by the user.
    if (hex) setPlateObjects(current => recolorUnmodifiedPlate(current, hex, manuallyColouredModels.current));
  }

  useEffect(() => {
    const id = ["orcaslicer", "crealityprint"].includes(form.engine) ? form.printer_profile_id : "";
    if (!id) {
      setNativePlate(null);
      return undefined;
    }
    let active = true;
    setNativePlate({ id, loading: true });
    apiFetch("/api/printing/slicer/profiles/" + id + "/plate/")
      .then(result => {
        if (active) setNativePlate({ id, plate: result.plate });
      })
      .catch(() => {
        if (active) setNativePlate({ id, error: "Native build volume could not be inspected." });
      });
    return () => { active = false; };
  }, [form.engine, form.printer_profile_id]);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [catalogue, existing, native] = await Promise.all([
        apiFetch("/api/printing/slicer/engines/"),
        apiFetch("/api/printing/slicer/jobs/"),
        apiFetch("/api/printing/slicer/profiles/"),
      ]);
      setEngines(catalogue.engines || []);
      setCanVerifyProfiles(catalogue.can_verify_profiles === true);
      setJobs(existing.jobs || []);
      setWorkerConfigured(existing.worker_configured === true);
      setMayCancel(existing.can_cancel === true);
      setMayDeleteDraft(existing.can_delete === true);
      setProfiles(native.profiles || []);
      setForm(current => {
        if (current.printer_id || !printers.length) return current;
        const last = (existing.jobs || []).find(job => printers.some(p => String(p.id) === String(job.printer?.id)));
        const found = printers.find(p => String(p.id) === String(last?.printer?.id))
          || (printers.filter(p => p.is_active !== false).length === 1 ? printers.find(p => p.is_active !== false) : null);
        if (!found) return current;
        return { ...current, printer_id: String(found.id), nozzle_mm: String(found.nozzle_mm || "0.4") };
      });
      setForm(current => {
        if (current.engine_version) return current;
        const engine = (catalogue.engines || []).find(item => item.key === current.engine);
        const installedVersion = engine?.installed_version;
        const availableProfile = (native.profiles || []).find(item => item.engine === current.engine && item.is_default)
          || (native.profiles || []).find(item => item.engine === current.engine);
        const version = installedVersion || availableProfile?.engine_version;
        return version ? { ...current, engine_version: version } : current;
      });
    } catch (err) {
      setError(err.message || "Could not load slicing drafts.");
    } finally {
      setLoading(false);
    }
  }

  function loadSavedDraft(job) {
    if (!job) return;
    setShowDrafts(false);
    if (job.status !== "draft") {
      setShowDrafts(true);
      setNotice("This slicing job is " + job.status + ". Select a saved draft to edit, or review its output.");
      return;
    }
    const savedObjects = job.settings?.plate_objects || [];
    manuallyColouredModels.current = new Set(savedObjects.map(item => item.instance_id));
    manuallyChosenProfiles.current = new Set(["printer", "filament", "process"]);
    setPlateObjects(savedObjects);
    setEditorOpen(true);
    setForm(current => ({
      ...current,
      engine: job.engine, engine_version: job.engine_version,
      input_asset_id: job.input_asset?.id || "",
      printer_id: job.printer?.id || "",
      spool_id: job.spool?.id || "",
      printer_preset: job.printer_preset,
      filament_preset: job.filament_preset,
      process_preset: job.process_preset,
      printer_profile_id: job.printer_profile_id || "",
      filament_profile_id: job.filament_profile_id || "",
      process_profile_id: job.process_profile_id || "",
      nozzle_mm: job.nozzle_mm,
    }));
    setNotice("Saved slicing draft loaded. Saving edits creates a new draft, preserving the original.");
    window.requestAnimationFrame(() =>
      document.getElementById("slicer-plate-heading")?.scrollIntoView({ behavior: "smooth" })
    );
  }

  useEffect(() => {
    if (loading || !initialDraftId || openedDraftRef.current === initialDraftId) return;
    const job = jobs.find(item => item.id === initialDraftId);
    openedDraftRef.current = initialDraftId;
    if (job) loadSavedDraft(job);
    else setError("That saved slicing draft is not available to this account.");
  }, [loading, initialDraftId, jobs]);

  useEffect(() => { refresh(); }, []);

  const previewJob = jobs.find(job => job.id === previewJobId && job.status === "completed" && job.output_asset?.id);
  const running = jobs.some(job => job.status === "queued" || job.status === "running");
  useEffect(() => {
    const pendingId = awaitingSlicePreviewRef.current;
    if (!pendingId || !showDrafts) return;
    const result = jobs.find(job => job.id === pendingId);
    if (result?.status === "completed" && result.output_asset?.id) {
      awaitingSlicePreviewRef.current = null;
      setPreviewJobId(result.id);
      setNotice("Slicing completed. Review the generated G-code before printing.");
    } else if (result && ["failed", "cancelled", "stale"].includes(result.status)) {
      awaitingSlicePreviewRef.current = null;
    }
  }, [jobs, showDrafts]);
  useEffect(() => {
    if (!running) return undefined;
    const id = window.setInterval(async () => {
      try {
        const result = await apiFetch("/api/printing/slicer/jobs/");
        setJobs(result.jobs || []);
        setWorkerConfigured(result.worker_configured === true);
        setMayCancel(result.can_cancel === true);
        setMayDeleteDraft(result.can_delete === true);
      } catch {
        // Existing draft listing remains visible; manual Refresh reports errors.
      }
    }, 5000);
    return () => window.clearInterval(id);
  }, [running]);

  async function deleteSavedDraft(job) {
    if (!["draft", "failed", "cancelled", "stale"].includes(job.status) || !mayDeleteDraft || busy) return;
    const label = job.status === "draft" ? "saved slicing draft" : "inactive slicing job";
    if (!window.confirm("Delete this " + label + " for " +
      (job.input_asset?.name || "this model") +
      "? This removes its job history and configuration, but preserves files saved separately to MakerVault.")) return;
    setError(""); setNotice(""); setBusy(true);
    try {
      await apiFetch("/api/printing/slicer/jobs/" + job.id + "/", { method: "DELETE" });
      setJobs(current => current.filter(item => item.id !== job.id));
      setNotice("Slicing entry deleted. Separately saved files were preserved.");
    } catch (err) {
      setError(err.message || "Could not delete this slicing entry.");
    } finally {
      setBusy(false);
    }
  }

  async function cancelPending(job) {
    if (!["draft", "queued"].includes(job.status)) return;
    setError(""); setNotice(""); setBusy(true);
    try {
      const result = await apiFetch("/api/printing/slicer/jobs/" + job.id + "/cancel/", {
        method: "POST", body: {},
      });
      setJobs(current => current.map(item => item.id === job.id ? result.job : item));
      setNotice("Slicing cancelled before execution. No printer or inventory changes were made.");
    } catch (err) {
      setError(err.message || "Could not cancel the pending slice.");
    } finally {
      setBusy(false);
    }
  }

  async function saveOutputToLibrary(job) {
    if (job.status !== "completed" || !job.output_asset_id || job.gcode_in_library) return;
    setBusy(true); setError("");
    try {
      const result = await apiFetch("/api/printing/slicer/jobs/" + job.id + "/save-gcode/", {
        method: "POST", body: {},
      });
      setJobs(current => current.map(item => item.id === job.id ? result.job : item));
      setNotice("Generated G-code added to your MakerVault G-code library.");
    } catch (err) {
      setError(err.message || "Could not add G-code to the library.");
    } finally {
      setBusy(false);
    }
  }

  async function startSlice(job) {
    setError(""); setNotice(""); setBusy(true);
    try {
      const result = await apiFetch("/api/printing/slicer/jobs/" + job.id + "/start/", {
        method: "POST", body: {},
      });
      setJobs(current => current.map(item => item.id === job.id ? result.job : item));
      awaitingSlicePreviewRef.current = job.id;
      setNotice("Slicing requested. This does not upload files to a printer or deduct filament inventory.");
    } catch (err) {
      setError(err.message || "Could not queue slicing.");
    } finally {
      setBusy(false);
    }
  }


  function requestPrint(job, action = "print") {
    if (job.status !== "completed" || !job.output_asset?.id) return;
    const printer = printers.find(item => String(item.id) === String(job.printer?.id));
    if (!printer) {
      setError("The printer used for this slice is no longer available.");
      return;
    }
    const connections = availableSlicerPrintConnections(printer);
    if (!connections.length) {
      setError("Set up an enabled printer connection before printing from the slicer.");
      return;
    }
    setError("");
    setPrintSelection({
      job,
      printer,
      connectionId: String(preferredSlicerPrintConnection(printer).id),
      choosing: connections.length > 1,
      action,
    });
  }

  function openPrinterReview() {
    setPrintSelection(current => current ? { ...current, choosing: false } : null);
  }

  async function saveDraft(mode = "draft") {
    if (busy || loading || !canPrepare) return;
    const sliceNow = mode !== "draft";
    const saveOutput = mode === "save-and-slice";
    const workflow = mode === "quick" ? "quick" : mode === "draft" && !editorOpen ? "setup" : "interactive";
    setError(""); setNotice("");
    if (!plateObjects.length) {
      setError("Add at least one STL to the visual build plate before saving or slicing.");
      return;
    }
    if (plateObjects.some(item => String(item.asset_id).startsWith("local:"))) {
      setError("A temporary STL has not finished uploading to the private slicing workspace. Import it again.");
      return;
    }
    if (!form.engine_version.trim() || !form.printer_id || !Number.isFinite(Number(form.nozzle_mm)) ||
        Number(form.nozzle_mm) < 0.1 || Number(form.nozzle_mm) > 2) {
      setError("Choose an engine version, printer and valid nozzle diameter before saving or slicing.");
      return;
    }
    if (["printer", "filament", "process"].some(kind => !form[kind + "_profile_id"])) {
      setError("Select a native printer, filament and process profile before saving or slicing.");
      return;
    }
    setBusy(true);
    let savedJob = null;
    try {
      const { job } = await apiFetch("/api/printing/slicer/jobs/", {
        method: "POST",
        body: {
          ...form,
          input_asset_id: plateObjects[0].asset_id,
          spool_id: form.spool_id || null,
          settings: { ...(plateObjects.length ? { plate_objects: plateObjects } : {}),
            save_gcode_to_library: saveOutput, workflow },
        },
      });
      savedJob = job;
      setJobs(current => [job, ...current]);
      if (!sliceNow) {
        setNotice("Slicing configuration saved as a private draft. No slicer or printer command was run.");
        setShowDrafts(true);
      } else {
        const queued = await apiFetch("/api/printing/slicer/jobs/" + job.id + "/start/", {
          method: "POST", body: {},
        });
        setJobs(current => current.map(item => item.id === job.id ? queued.job : item));
        awaitingSlicePreviewRef.current = job.id;
        setPreviewJobId(null);
        setNotice(saveOutput
          ? "Slicing queued. Generated G-code will be saved to your G-code library after completion."
          : "Slicing queued. Generated G-code will remain private unless you add it to the library.");
        setShowDrafts(true);
      }
    } catch (err) {
      setError((savedJob ? "Draft saved, but slicing could not start: " : "") +
        (err.message || "Could not prepare this slicing job."));
      if (savedJob) setShowDrafts(true);
    } finally {
      setBusy(false);
    }
  }

  async function inspectProfile(profile) {
    if (profile.engine !== "orcaslicer") return;
    setError("");
    setProfileLineages(current => ({ ...current, [profile.id]: { checking: true } }));
    try {
      const result = await apiFetch("/api/printing/slicer/profiles/" + profile.id + "/dependencies/");
      setProfileLineages(current => ({ ...current, [profile.id]: result.lineage }));
    } catch (err) {
      setProfileLineages(current => ({
        ...current,
        [profile.id]: { status: "invalid", error: err.message || "Profile inspection failed." },
      }));
    }
  }

  // Catalogue models come from the pinned upstream index, never a guessed
  // printer list. Changing manufacturer or engine invalidates old results.
  useEffect(() => {
    if (profileModal !== "search" || !officialVendor) return undefined;
    let active = true;
    setOfficialModelsBusy(true);
    setOfficialModels([]);
    setOfficialModel("");
    apiFetch("/api/printing/slicer/official-profiles/?" + new URLSearchParams({
      engine: form.engine, vendor: officialVendor, models: "1",
    }).toString()).then(result => {
      if (!active) return;
      const models = result.models || [];
      setOfficialModels(models);
      const model = String(selectedPrinter?.model || selectedPrinter?.name || "").trim().toLowerCase();
      const match = models.find(item => {
        const candidate = item.toLowerCase();
        return candidate === model || (model && candidate.endsWith(" " + model));
      });
      setOfficialModel(match || "");
    }).catch(err => {
      if (active) {
        setOfficialModels([]);
        setOfficialError("Could not load printer models from the official catalogue: " +
          (err.message || "Please try another manufacturer or reload the catalogue."));
      }
    }).finally(() => { if (active) setOfficialModelsBusy(false); });
    return () => { active = false; };
  }, [profileModal, officialVendor, form.engine, selectedPrinter?.id, selectedPrinter?.model, selectedPrinter?.name]);

  async function searchOfficialProfiles(event) {
    event.preventDefault();
    setOfficialError(""); setOfficialResults(null); setOfficialBusy(true);
    try {
      // A typed model search bypasses the catalogue model selection and
      // matches tokens anywhere in native preset names, in any order.
      const q = [officialManualModel.trim(), officialQuery.trim()].filter(Boolean).join(" ").trim();
      if (q.length < 2 || q.length > 80) throw new Error("Enter 2–80 characters across the manual model and preset searches.");
      const params = new URLSearchParams({ q, kind: importKind, vendor: officialVendor, engine: form.engine });
      if (!officialManualModel.trim() && officialModel) params.set("model", officialModel);
      const result = await apiFetch("/api/printing/slicer/official-profiles/?" + params.toString());
      setOfficialResults(result);
    } catch (err) {
      setOfficialError(err.message || "Official profile search is unavailable. You can still import a local file.");
    } finally {
      setOfficialBusy(false);
    }
  }

  async function importOfficialProfile(candidate, asDefault = false) {
    setOfficialError(""); setOfficialBusy(true);
    try {
      const result = await apiFetch("/api/printing/slicer/official-profiles/", {
        method: "POST",
        body: {
          kind: importKind, vendor: officialVendor, engine: form.engine,
          name: candidate.name, sub_path: candidate.sub_path,
        },
      });
      let imported = result.profile;
      if (asDefault) {
        try {
          const preference = await apiFetch("/api/printing/slicer/profiles/" + imported.id + "/default/", {
            method: "POST", body: { default: true },
          });
          imported = preference.profile;
        } catch (err) {
          setOfficialError("Profile imported, but setting its default failed: " + (err.message || "Please use Manage profiles."));
        }
      }
      manuallyChosenProfiles.current.add(imported.kind);
      // Official imports now include a complete dependency chain. Reload the
      // catalogue rather than hiding those newly imported parent presets.
      const loaded = await apiFetch("/api/printing/slicer/profiles/");
      setProfiles(loaded.profiles || []);
      setForm(current => ({
        ...current, engine: imported.engine, engine_version: result.engine_version,
        [imported.kind + "_profile_id"]: imported.id,
        [imported.kind + "_preset"]: imported.name,
      }));
      setOfficialImportNotice(imported.name + " imported as a " + imported.kind + " profile. You can select another profile type or return to your selected profiles.");
      setNotice("Official " + (imported.engine === "crealityprint" ? "Creality Print" : "OrcaSlicer") +
        " profile imported" + (imported.is_default ? " and saved as your default" : "") +
        ". " + Math.max(0, (result.parent_chain_length || 1) - 1) +
        " required parent preset(s) were included. The isolated worker will validate the profiles when slicing.");
    } catch (err) {
      setOfficialError(err.message || "Could not import the selected official native profile.");
    } finally {
      setOfficialBusy(false);
    }
  }

  async function openProfileEditor(profile) {
    setEditingProfile(profile);
    setEditProfileName(profile.name + " - Custom");
    setEditProfileSchema({});
    setEditProfileValues({});
    setEditProfileError("");
    setEditProfileBusy(true);
    setProfileModal("edit");
    try {
      const result = await apiFetch("/api/printing/slicer/profiles/" + profile.id + "/customise/");
      setEditProfileSchema(result.settings || {});
      setEditProfileValues(Object.fromEntries(Object.entries(result.settings || {}).map(
        ([key, spec]) => [key, spec.current == null ? "" : String(spec.current)]
      )));
    } catch (err) {
      setEditProfileError(err.message || "Cannot load the original preset for editing.");
    } finally {
      setEditProfileBusy(false);
    }
  }

  async function saveCustomProfile(event) {
    event.preventDefault();
    if (!editingProfile || editProfileBusy) return;
    const settings = Object.fromEntries(
      Object.entries(editProfileValues)
        .filter(([, raw]) => String(raw).trim() !== "")
        .map(([key, raw]) => [key, Number(raw)])
    );
    if (!Object.keys(settings).length) {
      setEditProfileError("Enter at least one supported native setting.");
      return;
    }
    setEditProfileError("");
    setEditProfileBusy(true);
    try {
      const result = await apiFetch("/api/printing/slicer/profiles/" + editingProfile.id + "/customise/", {
        method: "POST", body: { name: editProfileName.trim(), settings },
      });
      setProfiles(current => [result.profile, ...current]);
      setProfileModal("saved");
      setNotice("Custom " + editingProfile.kind + " preset saved as an unverified copy. The original was preserved.");
      setEditingProfile(null);
    } catch (err) {
      setEditProfileError(err.message || "Could not save the custom profile.");
    } finally {
      setEditProfileBusy(false);
    }
  }

  async function verifySelectedProfiles() {
    if (!canVerifyProfiles || !workerConfigured || verifyingProfiles) return;
    const ids = {
      printer: form.printer_profile_id,
      filament: form.filament_profile_id,
      process: form.process_profile_id,
    };
    if (Object.values(ids).some(value => !value)) {
      setError("Select a native printer, filament and process profile to run a verification slice.");
      return;
    }
    if (!window.confirm("Run a real isolated test slice with these three profiles? No printer is started and no filament is deducted. Verification can take up to 95 seconds.")) return;
    setError("");
    setNotice("");
    setVerifyingProfiles(true);
    try {
      const result = await apiFetch("/api/printing/slicer/profiles/approve/", {
        method: "POST",
        body: { engine: form.engine, engine_version: form.engine_version, profiles: ids },
      });
      setProfiles(current => current.map(profile =>
        Object.values(ids).includes(profile.id) ? { ...profile, status: "verified" } : profile
      ));
      setNotice("Real worker fixture passed for the selected profile trio. Receipt: " + result.receipt_sha256.slice(0, 12) + "… You may now prepare a draft for slicing.");
      await refresh();
    } catch (err) {
      setError("Fixture verification failed: " + (err.message || "The worker rejected the profile trio.") +
        " No profiles were approved.");
    } finally {
      setVerifyingProfiles(false);
    }
  }

  async function toggleProfileDefault(profile) {
    setError("");
    setBusy(true);
    try {
      const newDefault = !profile.is_default;
      await apiFetch("/api/printing/slicer/profiles/" + profile.id + "/default/", {
        method: "POST", body: { default: newDefault },
      });
      setProfiles(current => current.map(item => ({
        ...item,
        is_default: item.id === profile.id ? newDefault :
          newDefault && item.engine === profile.engine &&
          item.engine_version === profile.engine_version && item.kind === profile.kind
          ? false : item.is_default,
      })));
      setNotice((newDefault ? "Default saved: " : "Default cleared: ") + profile.name);
    } catch (err) {
      setError(err.message || "Could not update the default profile.");
    } finally {
      setBusy(false);
    }
  }

  async function loadOfficialVendors() {
    try {
      const params = new URLSearchParams({ engine: form.engine, catalogues: "1" });
      const response = await apiFetch("/api/printing/slicer/official-profiles/?" + params.toString());
      const vendors = response.vendors || [];
      setOfficialSourceInfo(response);
      setOfficialVendors(vendors);
      setOfficialVendor(suggestOfficialVendor(selectedPrinter, vendors));
    } catch (err) {
      setOfficialVendors([]);
      setOfficialSourceInfo(null);
      setOfficialError(err.message || "Could not load official catalogues. Manual import remains available.");
    }
  }

  function openOfficialSearch(kind = materialHint ? "filament" : form.printer_id ? "printer" : "process") {
    setImportKind(kind);
    setOfficialVendor("");
    setOfficialModel("");
    setOfficialManualModel("");
    setOfficialModels([]);
    setOfficialVendors([]);
    setOfficialSourceInfo(null);
    setOfficialError("");
    loadOfficialVendors();
    setOfficialQuery(defaultOfficialSearch(kind, { printer: selectedPrinter, spool: selectedSpool, nozzle: form.nozzle_mm }));
    setOfficialResults(null); // Never carry results into another engine/vendor catalogue.
    setOfficialImportNotice("");
    setOfficialError("");
    setProfileModal("search");
  }

  async function removeProfile(profile) {
    if (!window.confirm("Remove saved " + profile.kind + " profile \"" + profile.name + "\"? Existing source files remain in MakerVault Files. Profiles referenced by slicing jobs cannot be removed.")) return;
    setError(""); setBusy(true);
    try {
      await apiFetch("/api/printing/slicer/profiles/" + profile.id + "/", { method: "DELETE" });
      setProfiles(current => current.filter(item => item.id !== profile.id));
      setForm(current => current[profile.kind + "_profile_id"] === profile.id
        ? { ...current, [profile.kind + "_profile_id"]: "" } : current);
      setNotice("Profile registration removed. Its source file was preserved.");
    } catch (err) {
      setError(err.message || "Could not remove this profile.");
    } finally {
      setBusy(false);
    }
  }

  async function importProfile(event) {
    event.preventDefault();
    setError(""); setNotice(""); setBusy(true);
    let uploaded = false;
    try {
      if (!importFile) throw new Error("Choose an exported native profile file.");
      const expected = form.engine === "prusaslicer" ? ".ini" : ".json";
      if (!importFile.name.toLowerCase().endsWith(expected)) {
        throw new Error("This engine requires a native " + expected + " preset file.");
      }
      if (!form.engine_version.trim()) throw new Error("Enter the exact engine version before importing profiles.");
      const body = new FormData();
      body.append("file", importFile);
      body.append("category", "source");
      body.append("name", importName.trim() || importFile.name);
      const fileResult = await apiFetch("/api/files/", { method: "POST", body });
      uploaded = true;
      const { profile } = await apiFetch("/api/printing/slicer/profiles/", {
        method: "POST",
        body: {
          file_asset_id: fileResult.file.id,
          engine: form.engine,
          engine_version: form.engine_version,
          kind: importKind,
          name: importName.trim() || importFile.name.replace(/\\.[^.]+$/, ""),
          provenance: importSource.trim(),
        },
      });
      setProfiles(current => [profile, ...current]);
      setImportFile(null);
      setImportName("");
      setNotice("Native profile imported. MakerVault will check its integrity and dependencies when slicing.");
    } catch (err) {
      setError((err.message || "Profile import failed.") + (uploaded ? " The uploaded file remains in Files for review." : ""));
    } finally {
      setBusy(false);
    }
  }

  return <div className="printingStack">
    <section className="panel printingHero">
      <div>
        <span className="settingsEyebrow">3D Printing · MakerVault Slicer</span>
        <h2>Prepare a slice</h2>
        <p>Choose the model, physical printer and spool, then keep each slicing engine's printer, filament and process presets separate. Slicing execution is not enabled until a verified self-hosted worker is installed.</p>
      </div>
      <div className="printingHeroActions">
        {editorOpen && <button type="button" onClick={() => setEditorOpen(false)}>← Slicer setup</button>}
        <button type="button" onClick={onBack}>← Printing overview</button>
        <button type="button" onClick={() => setShowDrafts(true)}>Saved drafts ({jobs.length})</button>
      </div>
    </section>

    {editorOpen ? <SlicerPrepareWorkspace
      objects={plateObjects} onChange={setPlateObjects} files={stlFiles}
      localAssets={plateLocalAssets} onLocalAssetsChange={setPlateLocalAssets}
      onPrimaryChange={id => update("input_asset_id", String(id))}
      onFilesUploaded={onFilesUploaded} defaultColor={selectedSpoolHex}
      onManualColorChange={instanceId => manuallyColouredModels.current.add(instanceId)}
      plate={customBed.enabled ? { size_mm: [Number(customBed.x), Number(customBed.y)] }
        : (nativePlate?.plate && ["available", "partial"].includes(nativePlate.plate.status) ? nativePlate.plate
          : (Number(selectedPrinter?.build_volume?.x) > 0 && Number(selectedPrinter?.build_volume?.y) > 0
            ? { size_mm: [Number(selectedPrinter.build_volume.x), Number(selectedPrinter.build_volume.y)] } : null))}
      canEdit={canPrepare} busy={busy || loading} error={error} notice={notice}
      engine={form.engine + " " + form.engine_version} printer={selectedPrinter?.name}
      printerDetails={selectedPrinter} nozzleMm={form.nozzle_mm}
      printerId={form.printer_id}
      selectedProfiles={{ printer: form.printer_preset, process: form.process_preset, filament: form.filament_preset,
        printer_id: form.printer_profile_id, process_id: form.process_profile_id, filament_id: form.filament_profile_id }}
      onChangeProfiles={() => setProfileModal("change")}
      workerConfigured={workerConfigured && engines.some(engine => engine.key === form.engine && engine.available)}
      onBackToSetup={() => setEditorOpen(false)} onSaveDraft={() => saveDraft("draft")}
      onSlice={() => saveDraft("slice")}
    /> : <>
    <div className="slicerWorkbenchTop">
    <section className="panel printingSection" aria-labelledby="slicer-preparation-heading">
      <div className="slicerSetupHeading"><h3 id="slicer-preparation-heading">Slicer setup</h3></div>
      <p role="status">{workerConfigured
        ? "An isolated slicing worker is configured. Selected native profiles are checked for integrity before execution. Slicing never starts a print."
        : "Preparation mode — no isolated slicing worker is available. Saving a draft does not run a slicer, send a printer command or change spool inventory."}</p>
      {error && <p className="integrationError" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <form id="slicer-configuration-form" className="formGrid" onSubmit={event => { event.preventDefault(); saveDraft("draft"); }}>
        <div className="full slicerEngineSelection">
          <strong className="slicerEngineSelectionLabel">Slicing engine</strong>
          <SlicerEngineChoices engines={engines.length ? engines :
            [{ key: "orcaslicer", label: "OrcaSlicer", available: false },
             { key: "crealityprint", label: "Creality Print", available: false }]}
            selected={form.engine} disabled={!canPrepare || busy || loading}
            onSelect={key => {
              manuallyChosenProfiles.current.clear();
              const selectedEngine = engines.find(item => item.key === key);
              setForm(current => ({
                ...current, engine: key,
                engine_version: selectedEngine?.installed_version ||
                  profiles.find(profile => profile.engine === key)?.engine_version || "",
                printer_profile_id: "", filament_profile_id: "", process_profile_id: "",
              }));
            }} />
          <button type="button" className="slicerEngineManageLink"
            onClick={() => setProfileModal("engines")}>View engine installations</button>
        </div>
        <p className="full slicerEngineStatus" role="status">
          {engines.find(engine => engine.key === form.engine)?.available
            ? "The selected engine has passed worker identity checks. Compatible native profiles are still required for slicing."
            : "The selected engine is not installed or verified. You can prepare drafts, but slicing is disabled."}
        </p>
        <label>Engine version
          <input required maxLength="80" disabled={!canPrepare || busy} value={form.engine_version} onChange={e => update("engine_version", e.target.value)} placeholder="Exact installed/version-matched engine version" />
        </label>
        <label>Printer
          <select required disabled={!canPrepare || busy} value={form.printer_id}
            onChange={e => changeSessionPrinter(e.target.value)}>
            <option value="">Choose an owned printer</option>
            {printers.filter(item => item.is_active !== false).map(printer => <option key={printer.id} value={printer.id}>{printer.name}</option>)}
          </select>
        </label>
        <label>Nozzle diameter (mm)
          <input required type="number" step="0.01" min="0.1" max="2" disabled={!canPrepare || busy} value={form.nozzle_mm} onChange={e => update("nozzle_mm", e.target.value)} />
        </label>
        <div className="full slicerSpoolField">
          <span className="slicerSpoolFieldLabel">Physical filament spool (optional; does not replace the slicer's filament preset)</span>
          <SlicerSpoolPicker spools={spools} value={form.spool_id}
            onChange={chooseSpool} disabled={!canPrepare || busy} />
          {selectedSpoolHex && <span className="slicerSpoolColour">
            <span className="slicerSpoolSwatch" style={{ backgroundColor: selectedSpoolHex }} aria-hidden="true" />
            Preview colour: {selectedSpoolHex} · Individual models can override this colour
          </span>}
        </div>
        <label>Build plate
          <select disabled={!canPrepare || busy} value={form.plate} onChange={e => update("plate", e.target.value)}>
            <option value="default">Stock / default plate</option>
          </select>
        </label>
      {["orcaslicer", "crealityprint"].includes(form.engine) && nativePlate?.id === form.printer_profile_id &&
        <div className="slicerNativeVolume" aria-label="Native slicer build volume">
          <strong>Build volume</strong>
          <span>{nativePlate.loading ? "Loading…" :
            ["available", "partial"].includes(nativePlate.plate?.status) && Array.isArray(nativePlate.plate?.size_mm)
              ? nativePlate.plate.size_mm.join(" × ") + " mm"
              : "Not available from this profile"}</span>
        </div>}
      </form>
    </section>
    <aside className="panel printingSection slicerProfileSidebar" aria-label="Profile management">
      <h3>Profile management</h3>
      <p>Choose engine-native profiles. Manage imported profiles through Saved profiles.</p>
      <div className="slicerProfileActions">
        <button type="button" onClick={() => openOfficialSearch()}><ProfileActionIcon name="search" />Search official profiles</button>
        <button type="button" onClick={() => setProfileModal("import")}><ProfileActionIcon name="upload" />Import profile</button>
        <button type="button" onClick={() => { setManagingSavedProfiles(false); setProfileModal("saved"); }}><ProfileActionIcon name="bookmark" />Saved profiles ({profiles.filter(item => item.engine === form.engine && !item.is_dependency).length})</button>
      </div>
      {materialHint && <div className="slicerMaterialMatch">
        <strong>Filament match: {materialHint}</strong>
        <p>The selected spool is {materialHint}. Matching native filament presets are preferred; other materials won't be auto-selected.</p>
        {materialProfileMatches?.results && <p>
          {materialProfileMatches.results.total_matches} official {materialHint} candidates found for {form.engine === "crealityprint" ? "Creality Print" : "OrcaSlicer"}.
        </p>}
        <button type="button" disabled={materialProfileMatches?.loading}
          onClick={() => openOfficialSearch("filament")}>
          {materialProfileMatches?.loading ? "Finding matching profiles…" : "Review matching filament profiles"}
        </button>
      </div>}
      <h4>Selected profiles</h4>
      <div className="slicerSelectedProfiles">
        {["printer", "filament", "process"].map(kind => <label key={kind}>
          {kind.charAt(0).toUpperCase() + kind.slice(1)} profile
          <select disabled={!canPrepare || busy} value={form[kind + "_profile_id"]}
            onChange={event => selectNativeProfile(kind, event.target.value)}>
            <option value="">Select {kind} profile</option>
            {forKind(kind).map(profile => <option key={profile.id} value={profile.id}>
              {profile.name}{profile.is_default ? " · default" : ""}
            </option>)}
          </select>
        </label>)}
      </div>
      {Object.keys(profileSuggestions).length > 0 && <p className="slicerProfileHint">
        Suggested from {Object.values(profileSuggestions).join(", ")}.
      </p>}
      <h4>Build plate</h4>
      <label className="checkRow"><input type="checkbox" checked={customBed.enabled} onChange={e => setCustomBed(current => ({ ...current, enabled: e.target.checked }))} /><span>Custom preview bed size</span></label>
      {customBed.enabled && <div className="formGrid">
        <label>Width (mm)<input type="number" min="1" max="1000" step="1" value={customBed.x} onChange={e => setCustomBed(current => ({ ...current, x: e.target.value }))} /></label>
        <label>Depth (mm)<input type="number" min="1" max="1000" step="1" value={customBed.y} onChange={e => setCustomBed(current => ({ ...current, y: e.target.value }))} /></label>
        <p className="full">Preview-only override; does not modify or certify the engine's native printer profile.</p>
      </div>}
      <div className="slicerProfileRecommendationActions">
        <button type="button" onClick={() => {
          manuallyChosenProfiles.current.clear();
          setForm(current => ({
            ...current, printer_profile_id: "", filament_profile_id: "",
            process_profile_id: "", printer_preset: "", filament_preset: "", process_preset: "",
          }));
        }}>Restore suggested profiles</button>
      </div>
    </aside>
    </div>


    <SlicerPlateEditor
      files={stlFiles}
      localAssets={plateLocalAssets} onLocalAssetsChange={setPlateLocalAssets}
      objects={plateObjects}
      onChange={setPlateObjects}
      defaultColor={selectedSpoolHex}
      onManualColorChange={instanceId => manuallyColouredModels.current.add(instanceId)}
      onPrimaryChange={id => update("input_asset_id", String(id))}
      plate={customBed.enabled ? { size_mm: [Number(customBed.x), Number(customBed.y)] }
        : (nativePlate?.plate && ["available", "partial"].includes(nativePlate.plate.status) ? nativePlate.plate
        : (Number(selectedPrinter?.build_volume?.x) > 0 && Number(selectedPrinter?.build_volume?.y) > 0
          ? { size_mm: [Number(selectedPrinter.build_volume.x), Number(selectedPrinter.build_volume.y)] } : null))}
      canEdit={canPrepare}
      onFilesUploaded={onFilesUploaded}
      footer={<>
        <div className="slicerPlateActionFeedback" aria-live="polite">
          {error && <p className="integrationError" role="alert">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          {!error && !notice && !plateObjects.length &&
            <p className="slicerPlateActionHint">Add an STL to the plate before saving or slicing.</p>}
        </div>
        <div className="slicerDraftActions settingsActions">
          <button type="button" onClick={() => saveDraft("draft")}
            disabled={!canPrepare || busy || loading || !plateObjects.length || !printers.length}>
            {busy ? "Saving…" : "Save draft"}
          </button>
          <button type="button" onClick={() => saveDraft("quick")}
            disabled={!canPrepare || busy || loading || !workerConfigured ||
              !engines.some(engine => engine.key === form.engine && engine.available) ||
              !plateObjects.length || !printers.length}>
            {busy ? "Preparing…" : "Quick slice"}
          </button>
          <button type="button" className="primary" onClick={() => { setError(""); setNotice(""); setEditorOpen(true); }}
            disabled={!canPrepare || busy || loading}>
            Slice → Interactive slicer
          </button>
        </div>
      </>}
    />

    </>}
    {profileModal === "edit" && editingProfile && <Modal title={"Customise " + editingProfile.kind + " profile"} subtitle={editingProfile.engine + " · " + editingProfile.engine_version} onClose={() => setProfileModal("")} wide>
      <p>The original native preset remains unchanged. This creates a new, unverified copy with supported settings; inherited profiles still need their parent presets before slicing.</p>
      {editProfileError && <p role="alert" className="integrationError">{editProfileError}</p>}
      <form className="formGrid" onSubmit={saveCustomProfile}>
        <label className="full">Custom profile name
          <input required maxLength="200" value={editProfileName} disabled={editProfileBusy} onChange={e => setEditProfileName(e.target.value)} />
        </label>
        {Object.entries(editProfileSchema).map(([key, spec]) => <label key={key}>
          {({
  nozzle_diameter: "Nozzle diameter (mm)",
  retract_length: "Retraction length (mm)",
  retraction_distances_when_cut: "Long retraction when cutting filament (mm)",
  nozzle_temperature: "Nozzle temperature (°C)",
  hot_plate_temp: "Smooth plate temperature (°C)",
  cool_plate_temp: "Cool plate temperature (°C)",
  textured_plate_temp: "Textured plate temperature (°C)",
  filament_flow_ratio: "Filament flow ratio",
  layer_height: "Layer height (mm)",
  initial_layer_print_height: "Initial layer height (mm)",
  sparse_infill_density: "Infill (%)",
  wall_loops: "Wall loops",
  outer_wall_speed: "Outer wall speed (mm/s)",
})[key] || key.replaceAll("_", " ")}
          <input type="number" min={spec.min} max={spec.max} step="any" value={editProfileValues[key] ?? ""}
            disabled={editProfileBusy} onChange={e => setEditProfileValues(current => ({ ...current, [key]: e.target.value }))} />
        </label>)}
        <div className="full settingsActions">
          <button type="button" disabled={editProfileBusy} onClick={() => setProfileModal("saved")}>Cancel</button>
          <button type="submit" className="primary" disabled={editProfileBusy || !Object.keys(editProfileSchema).length}>
            {editProfileBusy ? "Saving…" : "Save custom profile"}
          </button>
        </div>
      </form>
    </Modal>}
    {profileModal === "change" && <Modal title="Change slicing profiles"
      subtitle={"Engine: " + form.engine + " " + form.engine_version + " · Printer: " + (selectedPrinter?.name || "Not selected")}
      onClose={() => setProfileModal("")} wide>
      <p>Choose from installed native printer, filament and process profiles. These changes
        apply to this slicing session and will be recorded with the next saved draft or slice.</p>
      <div className="slicerChangeProfileGrid">
        <label>Printer
          <select value={form.printer_id} disabled={!canPrepare || busy}
            onChange={e => changeSessionPrinter(e.target.value)}>
            <option value="">Choose an owned printer</option>
            {printers.filter(item => item.is_active !== false).map(printer =>
              <option key={printer.id} value={printer.id}>{printer.name}</option>)}
          </select>
        </label>
        <label>Nozzle diameter (mm)
          <input type="number" step="0.01" min="0.1" max="2"
            value={form.nozzle_mm} disabled={!canPrepare || busy}
            onChange={e => update("nozzle_mm", e.target.value)} />
        </label>
        <p className="full slicerChangePrinterHint">Changing the printer resets the session's native printer, process and filament profiles to prevent incompatible selections. Select matching presets below before saving or slicing.</p>
        {["printer", "filament", "process"].map(kind => <label key={kind}>
          {kind.charAt(0).toUpperCase() + kind.slice(1)} profile
          <select value={form[kind + "_profile_id"]} disabled={!canPrepare || busy}
            onChange={e => selectNativeProfile(kind, e.target.value)}>
            <option value="">Choose {kind} profile</option>
            {forKind(kind).map(profile => <option key={profile.id} value={profile.id}>
              {profile.name}
            </option>)}
          </select>
        </label>)}
      </div>
      <p className="projectUploadHint">Material slot assignments are separate from native filament presets.
        Changing these profiles does not modify printer hardware or loaded CFS/AMS slots.</p>
      <div className="settingsActions slicerChangeProfileActions">
        <button type="button" onClick={() => setProfileModal("")}>Done</button>
      </div>
    </Modal>}
    {profileModal === "engines" && <Modal title="Slicer engine installations"
      subtitle="Optional self-hosted engines" onClose={() => setProfileModal("")} wide>
      <p>OrcaSlicer and Creality Print run independently in the optional isolated worker.
        Engine installation from MakerVault is not available yet. A configured worker must pass
        verification before an engine can execute slicing jobs.</p>
      <SlicerEngineChoices engines={engines.length ? engines :
        [{ key: "orcaslicer", label: "OrcaSlicer", available: false },
         { key: "crealityprint", label: "Creality Print", available: false }]}
        mode="install" />
      <div className="printingActionGroup">
        <h4>Adding the slicer service to an existing MakerVault installation</h4>
        <p>The optional service must be deployed once by the host administrator.
          It does not require privileged mode or Docker socket access in MakerVault.
          Your existing database, models, printers and G-code library are preserved.</p>
        <a href="https://github.com/gavrd7/MakerVault/blob/feature/self-hosted-slicer-foundation/docs/guide/3d-printing/slicer.md#adding-the-slicer-container-to-an-existing-installation"
          target="_blank" rel="noopener noreferrer">
          Installation guidance for existing MakerVault installations ↗
        </a>
        <small>The experimental OrcaSlicer staging installer is documented separately from the future production installation.</small>
      </div>
      <p>You can continue preparing slicing drafts without installing either engine.</p>
    </Modal>}
    {profileModal === "search" && <Modal title="Search official profiles" onClose={() => setProfileModal("")} wide>
      <div className="slicerProfileNavigation">
        <button type="button" onClick={() => setProfileModal("")} disabled={officialBusy}>
          ← Back to selected profiles
        </button>
        <button type="button" onClick={() => { setManagingSavedProfiles(false); setProfileModal("saved"); }} disabled={officialBusy}>
          View saved profiles
        </button>
      </div>
      <div className="printingActionGroup" aria-labelledby="slicer-official-profiles-heading">
        <h4 id="slicer-official-profiles-heading">Search official slicer profiles</h4>
        <p>Search the selected engine's pinned official manufacturer catalogues for printer, filament and process presets. An engine may not provide a profile for every printer. Imports remain unverified candidates; profiles cannot be shared between engines.</p>
        {officialSourceInfo && !officialSourceInfo.official_search_available && <p role="status">This engine does not yet have a verified upstream catalogue browser in MakerVault. You can still import native {officialSourceInfo.native_profile_format} profiles as unverified candidates; slicing requires a separately validated engine and profile combination.</p>}
        <form className="formGrid" onSubmit={searchOfficialProfiles}>
          <label>Official source
            <select value={form.engine} disabled>
              <option value={form.engine}>{engines.find(engine => engine.key === form.engine)?.label || form.engine}</option>
            </select>
          </label>
          <label>Manufacturer / upstream catalogue
            <select value={officialVendor} disabled={officialBusy || !officialVendors.length} onChange={e => {
              setOfficialVendor(e.target.value); setOfficialResults(null);
            }}>
              {officialVendors.map(vendor => <option key={vendor.id} value={vendor.id}>{vendor.label}</option>)}
              {!officialVendors.length && <option value="">No catalogue loaded</option>}
            </select>
          </label>
          <label>Printer model
            <select value={officialModel} disabled={officialModelsBusy || !officialVendor}
              onChange={e => { setOfficialModel(e.target.value); setOfficialResults(null); }}>
              <option value="">All models / generic profiles</option>
              {officialModels.map(model => <option key={model} value={model}>{model}</option>)}
            </select>
          </label>
          <label>Profile type
            <select value={importKind} disabled={officialBusy} onChange={e => { setImportKind(e.target.value); setOfficialQuery(defaultOfficialSearch(e.target.value, { printer: selectedPrinter, spool: selectedSpool, nozzle: form.nozzle_mm })); setOfficialResults(null); setOfficialImportNotice(""); }}>
              <option value="printer">Printer / machine</option>
              <option value="filament">Filament</option>
              <option value="process">Process</option>
            </select>
          </label>
          <label className="full">Manual printer/model search (optional)
            <input value={officialManualModel} maxLength="80"
              onChange={e => { setOfficialManualModel(e.target.value); setOfficialResults(null); }}
              placeholder="Type a model, e.g. K1, instead of selecting it above" />
            <small>Typing here overrides the printer-model dropdown. Search terms match anywhere in the official profile name.</small>
          </label>
          <label className="full">Search official presets (optional)
            <input value={officialQuery} maxLength="80" onChange={e => setOfficialQuery(e.target.value)} placeholder="e.g. PLA or 0.20mm Standard" />
          </label>
          <div className="full settingsActions">
            <button type="submit" disabled={officialBusy || !officialVendor || !officialVendors.length || [officialManualModel.trim(), officialQuery.trim()].filter(Boolean).join(" ").length < 2}>
              {officialBusy ? "Searching…" : "Search official profiles"}
            </button>
          </div>
        </form>
        <div className="full settingsActions slicerOfficialImportAlternative"><button type="button" onClick={() => { setProfileModal("import"); setOfficialError(""); }}>Import native profile file instead</button></div>
        {officialError && <p className="integrationError" role="alert">{officialError}</p>}
        {officialImportNotice && <p role="status" className="slicerProfileImportNotice">{officialImportNotice}</p>}
        {officialResults && <div className="printingStack" role="region" aria-label="Official profile search results">
          <p>{officialResults.total_matches} matching official presets in {officialResults.vendor} · showing up to {officialResults.profiles.length} · original upstream release {officialResults.ref}{officialResults.printer_model_filter ? " · filtered for " + officialResults.printer_model_filter + " (name-based, not verified compatibility)" : ""}</p>
          {officialResults.profiles.map(candidate => <div className="cameraSourceRow" key={candidate.sub_path}>
            <div className="cameraSourceIdentity">
              <strong>{candidate.name}</strong>
              <small>{candidate.sub_path} · not verified</small>
            </div>
            <div className="cameraSourceActions">
              <button type="button" onClick={() => importOfficialProfile(candidate)} disabled={!canPrepare || officialBusy}>
                Import candidate
              </button>
              <button type="button" onClick={() => importOfficialProfile(candidate, true)} disabled={!canPrepare || officialBusy}>
                Import &amp; set default
              </button>
            </div>
          </div>)}
          {!officialResults.profiles.length && <p>No matching presets. Try fewer manual search terms or select All models to browse the complete manufacturer catalogue.</p>}
        </div>}
      </div>

    </Modal>}
    {profileModal === "import" && <Modal title="Import native profile" onClose={() => setProfileModal("")} wide>
      <div className="slicerProfileNavigation">
        <button type="button" onClick={() => setProfileModal("search")} disabled={busy}>
          ← Back to official profiles
        </button>
        <button type="button" onClick={() => setProfileModal("")} disabled={busy}>
          Back to selected profiles
        </button>
      </div>
      <p>Import an engine-native profile as an unverified candidate. Existing originals are preserved.</p>
      <h4>Import a local native profile file</h4>
      <form className="formGrid" onSubmit={importProfile}>
        <label>Profile type
          <select value={importKind} disabled={busy || !canPrepare} onChange={e => setImportKind(e.target.value)}>
            <option value="printer">Printer / machine</option>
            <option value="filament">Filament</option>
            <option value="process">Process</option>
          </select>
        </label>
        <label>Exported preset file
          <input required type="file" accept={form.engine === "prusaslicer" ? ".ini" : ".json"} disabled={busy || !canPrepare} onChange={e => setImportFile(e.target.files?.[0] || null)} />
        </label>
        <label>Preset name
          <input required maxLength="200" value={importName} disabled={busy || !canPrepare} onChange={e => setImportName(e.target.value)} placeholder="Native preset name" />
        </label>
        <label>Source / provenance
          <input maxLength="200" value={importSource} disabled={busy || !canPrepare} onChange={e => setImportSource(e.target.value)} placeholder="Exported from engine, vendor or original author" />
        </label>
        <div className="full settingsActions">
          <button type="submit" disabled={!canPrepare || busy || !form.engine_version.trim() || !importFile}>{busy ? "Importing…" : "Import profile for review"}</button>
        </div>
      </form>

    </Modal>}
    {profileModal === "saved" && <Modal title="Saved slicer profiles" onClose={() => setProfileModal("")} wide>
      <p>Profiles for the selected engine. Native parent presets are hidden from everyday selection and retained automatically for inherited profiles.</p>
      <div className="settingsActions slicerSavedProfileToolbar">
        <button type="button" onClick={() => setManagingSavedProfiles(current => !current)}>
          <ProfileActionIcon name="settings" /><span>{managingSavedProfiles ? "Done managing" : "Manage"}</span>
        </button>
        {managingSavedProfiles && <button type="button" onClick={() => setProfileModal("import")}>
          <ProfileActionIcon name="upload" /><span>Import profile</span>
        </button>}
        {managingSavedProfiles && <label className="checkRow slicerDependencyToggle">
          <input type="checkbox" checked={showProfileDependencies}
            onChange={e => setShowProfileDependencies(e.target.checked)} />
          <span>Show protected native parent presets</span>
        </label>}
      </div>
      <div className="printingStack">
        {profiles.filter(item => item.engine === form.engine &&
          (!item.is_dependency || (managingSavedProfiles && showProfileDependencies))).map(profile =>
          <div className="cameraSourceRow" key={profile.id}>
            <div className="cameraSourceIdentity">
              <strong>{profile.name} · {profile.kind}{profile.is_default ? " · Default" : ""}</strong>
              <small>{profile.engine} {profile.engine_version} · {profile.status} · {profile.provenance || "No source supplied"}</small>
              {profile.is_dependency && <small role="note">Protected inherited parent — managed automatically, not selectable for slicing</small>}
              {profileLineages[profile.id] && <small role="status">
                {profileLineages[profile.id].checking ? "Checking native parent presets…" :
                  profileLineages[profile.id].status === "complete" ? "Parent chain present — still unverified for slicing" :
                  profileLineages[profile.id].status === "missing" ? "Missing native parent: " + profileLineages[profile.id].missing :
                  profileLineages[profile.id].status === "cycle" ? "Circular native parent reference detected" :
                  profileLineages[profile.id].status === "too_deep" ? "Parent chain exceeds allowed depth" :
                  profileLineages[profile.id].error || "Native preset dependency inspection failed"}
              </small>}
              {profileLineages[profile.id]?.chain?.length > 1 && <small>
                Parent chain: {profileLineages[profile.id].chain.map(entry => entry.name).join(" → ")}
              </small>}
            </div>
            {managingSavedProfiles && <div className="cameraSourceActions">
              {profile.engine === "orcaslicer" && <button type="button" disabled={profileLineages[profile.id]?.checking} onClick={() => inspectProfile(profile)}>Check parent presets</button>}
              {!profile.is_dependency && ["orcaslicer", "crealityprint"].includes(profile.engine) && <button type="button" disabled={busy} onClick={() => openProfileEditor(profile)}>Edit as custom</button>}
              {!profile.is_dependency && <button type="button" disabled={busy} onClick={() => toggleProfileDefault(profile)}>
                {profile.is_default ? "Clear default" : "Set as default"}
              </button>}
              {!profile.is_dependency && <button type="button" disabled={busy} onClick={() => removeProfile(profile)}>Remove profile</button>}
            </div>}
          </div>
        )}
      </div>

    </Modal>}
    {showDrafts && <Modal title={previewJob ? "Sliced G-code preview" : "Saved slicing drafts"}
      onClose={() => { setShowDrafts(false); setPreviewJobId(null); }} wide>
      {previewJob ? <>
        <div className="formActions" style={{ justifyContent: "flex-start" }}>
          <button type="button" onClick={() => setPreviewJobId(null)}>← Back to slicing jobs</button>
          {previewJob.settings?.workflow !== "quick" && !previewJob.gcode_in_library && <button type="button" disabled={busy}
            onClick={() => saveOutputToLibrary(previewJob)}>Add G-code to library</button>}
          {previewJob.settings?.workflow !== "quick" && previewJob.gcode_in_library && <button type="button" onClick={onOpenGcode}>Open G-code library</button>}
          {canPrint && previewJob.settings?.workflow !== "quick" && <>
            <button type="button"
              onClick={() => requestPrint(previewJob, "upload")}>Upload to printer</button>
            <button type="button" className="primary"
              onClick={() => requestPrint(previewJob, "print")}>Upload and start print</button>
          </>}
        </div>
        {error && <p className="integrationError" role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        <GcodeViewerModal key={previewJob.output_asset.id} embedded
          file={previewJob.output_asset} canEdit={false} onClose={() => setPreviewJobId(null)} />
      </> : <>
      {error && <p className="integrationError" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button type="button" disabled={loading} onClick={refresh}>Refresh drafts</button>
      <h3>Saved slicing drafts</h3>
      {jobs.length ? <div className="printingStack">{jobs.map(job =>
        <div key={job.id} className="cameraSourceRow">
          <div className="cameraSourceIdentity">
            <strong>{job.input_asset?.name || "Model"} · {job.printer?.name || "Printer"}</strong>
            <small>{job.engine} {job.engine_version} · {job.status} · {job.process_preset}</small>
            {job.settings?.plate_objects?.length > 0 && <small>
              Saved visual plate: {job.settings.plate_objects.length} model instance{job.settings.plate_objects.length === 1 ? "" : "s"} · preparation-only
            </small>}
            <small>{job.spool?.name ? "Spool " + job.spool.name + " · " : ""}
              {job.status === "completed" ? "G-code saved privately; inspect before printing" :
                job.status === "draft" ? "Configuration saved; not sliced" :
                job.message || "Waiting for job update"}</small>
            {(job.status === "queued" || job.status === "running") && <progress value={job.progress || 0} max="100" aria-label="Slicing progress" />}
          </div>
          <div className="cameraSourceActions">
            {job.status === "draft" && <button type="button" disabled={busy}
              onClick={() => loadSavedDraft(job)}>Edit draft</button>}
            {mayDeleteDraft && ["draft", "failed", "cancelled", "stale"].includes(job.status) &&
              <button type="button" disabled={busy} onClick={() => deleteSavedDraft(job)}>
                {job.status === "draft" ? "Delete draft" : "Delete"}
              </button>}
            {job.can_slice && canPrepare && <button type="button" disabled={busy} onClick={() => startSlice(job)}>Slice now</button>}
            {mayCancel && (job.status === "draft" || job.status === "queued") && <button type="button" disabled={busy} onClick={() => cancelPending(job)}>Cancel {job.status === "queued" ? "queued slice" : "draft"}</button>}
            {job.status === "completed" && job.output_asset?.id &&
              <button type="button" onClick={() => setPreviewJobId(job.id)}>Preview G-code</button>}
            {job.settings?.workflow !== "quick" && job.status === "completed" && job.output_asset?.id && job.gcode_in_library && canPrint && <button type="button" className="primary" disabled={busy} onClick={() => requestPrint(job)}>Print from slicer</button>}
            {job.settings?.workflow !== "quick" && job.status === "completed" && job.output_asset_id && !job.gcode_in_library &&
              <button type="button" disabled={busy} onClick={() => saveOutputToLibrary(job)}>Add G-code to library</button>}
            {job.settings?.workflow !== "quick" && job.status === "completed" && job.output_asset_id && job.gcode_in_library &&
              <button type="button" onClick={onOpenGcode}>Open G-code library</button>}
          </div>
        </div>
      )}</div> : <p>No slicing drafts saved yet.</p>}
      </>}
    </Modal>}
    {previewFile && <FileModelViewerModal file={previewFile} onClose={() => setPreviewFile(null)} />}
    {printSelection?.choosing && <Modal title="Choose printer connection" subtitle={(printSelection.action === "upload" ? "Send " : "Print ") + (printSelection.job.output_asset?.filename || "sliced G-code") + " on " + printSelection.printer.name} onClose={() => setPrintSelection(null)}>
      <p>This uses MakerVault's existing printer-submission checks and requires a separate confirmation before printing.</p>
      <div className="formGrid">
        <label className="full">Printer connection
          <select value={printSelection.connectionId} onChange={event => setPrintSelection(current => current ? { ...current, connectionId: event.target.value } : null)}>
            {availableSlicerPrintConnections(printSelection.printer).map(connection => <option key={connection.id} value={String(connection.id)}>{connection.adapter_label || connection.adapter || "Printer connection"}{connection.status ? " · " + connection.status : ""}</option>)}
          </select>
        </label>
        <div className="full settingsActions">
          <button type="button" onClick={() => setPrintSelection(null)}>Cancel</button>
          <button type="button" className="primary" onClick={openPrinterReview}>{printSelection.action === "upload" ? "Review upload" : "Review print"}</button>
        </div>
      </div>
    </Modal>}
    {printSelection && !printSelection.choosing && (() => {
      const connection = availableSlicerPrintConnections(printSelection.printer)
        .find(item => String(item.id) === printSelection.connectionId);
      return connection ? <PrinterStartGcodeModal
        key={printSelection.job.id + ":" + connection.id}
        printer={printSelection.printer}
        connection={connection}
        canEdit={canPrint}
        initialAsset={printSelection.job.output_asset}
        initialAction={printSelection.action === "upload" ? "upload" : "print"}
        onChanged={refresh}
        onClose={() => setPrintSelection(null)}
      /> : null;
    })()}
  </div>;
}
