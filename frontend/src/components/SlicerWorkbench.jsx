import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";
import PrinterStartGcodeModal from "./PrinterStartGcodeModal";
import { availableSlicerPrintConnections, preferredSlicerPrintConnection } from "./slicerPrintRouting";

const initialForm = {
  engine: "prusaslicer", engine_version: "", input_asset_id: "", printer_id: "",
  spool_id: "", printer_preset: "", filament_preset: "", process_preset: "",
  nozzle_mm: "0.40", plate: "default",
  printer_profile_id: "", filament_profile_id: "", process_profile_id: "",
};

/**
 * Safe preparation-only entry point. A verified slicing worker, real engine-native
 * profile IDs and isolated execution are required before enabling a Slice action.
 */
export default function SlicerWorkbench({ files = [], printers = [], spools = [], canPrepare = false, canPrint = false, onBack, onOpenGcode }) {
  const [form, setForm] = useState(initialForm);
  const [engines, setEngines] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [workerConfigured, setWorkerConfigured] = useState(false);
  const [printSelection, setPrintSelection] = useState(null);
  const [importFile, setImportFile] = useState(null);
  const [importKind, setImportKind] = useState("printer");
  const [importName, setImportName] = useState("");
  const [importSource, setImportSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const stlFiles = useMemo(() => files.filter(file =>
    file.category === "mesh" && /\.stl$/i.test(file.filename || "")
  ), [files]);

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
    profile.engine === form.engine && profile.engine_version === form.engine_version && profile.kind === kind
  );
  const selectNativeProfile = (kind, id) => {
    const profile = profiles.find(item => item.id === id);
    setForm(current => ({
      ...current,
      [kind + "_profile_id"]: id,
      ...(profile ? { [kind + "_preset"]: profile.name } : {}),
    }));
  };
  const selectedPrinter = printers.find(item => String(item.id) === form.printer_id);

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
      setJobs(existing.jobs || []);
      setWorkerConfigured(existing.worker_configured === true);
      setProfiles(native.profiles || []);
    } catch (err) {
      setError(err.message || "Could not load slicing drafts.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  const running = jobs.some(job => job.status === "queued" || job.status === "running");
  useEffect(() => {
    if (!running) return undefined;
    const id = window.setInterval(async () => {
      try {
        const result = await apiFetch("/api/printing/slicer/jobs/");
        setJobs(result.jobs || []);
        setWorkerConfigured(result.worker_configured === true);
      } catch {
        // Existing draft listing remains visible; manual Refresh reports errors.
      }
    }, 5000);
    return () => window.clearInterval(id);
  }, [running]);

  async function startSlice(job) {
    setError(""); setNotice(""); setBusy(true);
    try {
      const result = await apiFetch("/api/printing/slicer/jobs/" + job.id + "/start/", {
        method: "POST", body: {},
      });
      setJobs(current => current.map(item => item.id === job.id ? result.job : item));
      setNotice("Slicing requested. This does not upload files to a printer or deduct filament inventory.");
    } catch (err) {
      setError(err.message || "Could not queue slicing.");
    } finally {
      setBusy(false);
    }
  }


  function requestPrint(job) {
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
    });
  }

  function openPrinterReview() {
    setPrintSelection(current => current ? { ...current, choosing: false } : null);
  }

  async function saveDraft(event) {
    event.preventDefault();
    setError(""); setNotice(""); setBusy(true);
    try {
      const { job } = await apiFetch("/api/printing/slicer/jobs/", {
        method: "POST",
        body: {
          ...form,
          spool_id: form.spool_id || null,
          settings: {},
        },
      });
      setJobs(current => [job, ...current]);
      setNotice("Slicing configuration saved as a private draft. No slicer or printer command was run.");
    } catch (err) {
      setError(err.message || "Could not save the slicing draft.");
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
      setNotice("Native profile imported as an unverified candidate. Slicing remains disabled until an approved worker and profiles pass validation.");
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
        <button type="button" onClick={onBack}>← Printing overview</button>
        <button type="button" disabled={loading} onClick={refresh}>Refresh drafts</button>
      </div>
    </section>

    <section className="panel printingSection" aria-labelledby="slicer-preparation-heading">
      <h3 id="slicer-preparation-heading">Slicing configuration</h3>
      <p role="status">{workerConfigured
        ? "A verified isolated worker is configured. Only drafts with administrator-verified native profiles can be sliced. Slicing never starts a print."
        : "Preparation mode — no administrator-approved slicing worker is available. Saving a draft does not run a slicer, send a printer command or change spool inventory."}</p>
      {error && <p className="integrationError" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <form className="formGrid" onSubmit={saveDraft}>
        <label>Engine
          <select required disabled={!canPrepare || busy || loading} value={form.engine} onChange={e => update("engine", e.target.value)}>
            {engines.length ? engines.map(engine =>
              <option key={engine.key} value={engine.key}>{engine.label} · {engine.status} · not installed</option>
            ) : <option value="prusaslicer">PrusaSlicer · not installed</option>}
          </select>
        </label>
        <label>Requested engine version (not yet installed)
          <input required maxLength="80" disabled={!canPrepare || busy} value={form.engine_version} onChange={e => update("engine_version", e.target.value)} placeholder="Exact tested version when available" />
        </label>
        <label className="full">Model STL
          <select required disabled={!canPrepare || busy} value={form.input_asset_id} onChange={e => update("input_asset_id", e.target.value)}>
            <option value="">Choose an existing STL file</option>
            {stlFiles.map(file => <option key={file.id} value={file.id}>{file.name} · {file.filename}</option>)}
          </select>
        </label>
        <label>Printer
          <select required disabled={!canPrepare || busy} value={form.printer_id} onChange={e => {
            const printer = printers.find(item => String(item.id) === e.target.value);
            setForm(current => ({ ...current, printer_id: e.target.value, nozzle_mm: String(printer?.nozzle_mm || "0.40") }));
          }}>
            <option value="">Choose an owned printer</option>
            {printers.filter(item => item.is_active !== false).map(printer => <option key={printer.id} value={printer.id}>{printer.name}</option>)}
          </select>
        </label>
        <label>Nozzle diameter (mm)
          <input required type="number" step="0.01" min="0.1" max="2" disabled={!canPrepare || busy} value={form.nozzle_mm} onChange={e => update("nozzle_mm", e.target.value)} />
        </label>
        <label className="full">Physical filament spool (optional; does not replace the slicer's filament preset)
          <select disabled={!canPrepare || busy} value={form.spool_id} onChange={e => update("spool_id", e.target.value)}>
            <option value="">No physical spool selected</option>
            {spools.map(spool => <option key={spool.id} value={spool.id}>{spool.spool_id} · {spool.filament}</option>)}
          </select>
        </label>
        {forKind("printer").length > 0 && <label>Native printer profile (unverified)
          <select disabled={!canPrepare || busy} value={form.printer_profile_id} onChange={e => selectNativeProfile("printer", e.target.value)}>
            <option value="">Use a draft label instead</option>
            {forKind("printer").map(profile => <option key={profile.id} value={profile.id}>{profile.name} · {profile.status}</option>)}
          </select>
        </label>}
        <label>Engine printer preset (draft label)
          <input required maxLength="200" disabled={!canPrepare || busy} value={form.printer_preset} onChange={e => update("printer_preset", e.target.value)} placeholder={selectedPrinter?.name || "Native machine preset"} />
        </label>
        {forKind("filament").length > 0 && <label>Native filament profile (unverified)
          <select disabled={!canPrepare || busy} value={form.filament_profile_id} onChange={e => selectNativeProfile("filament", e.target.value)}>
            <option value="">Use a draft label instead</option>
            {forKind("filament").map(profile => <option key={profile.id} value={profile.id}>{profile.name} · {profile.status}</option>)}
          </select>
        </label>}
        <label>Engine filament preset (draft label)
          <input required maxLength="200" disabled={!canPrepare || busy} value={form.filament_preset} onChange={e => update("filament_preset", e.target.value)} placeholder="Native filament preset" />
        </label>
        {forKind("process").length > 0 && <label>Native process profile (unverified)
          <select disabled={!canPrepare || busy} value={form.process_profile_id} onChange={e => selectNativeProfile("process", e.target.value)}>
            <option value="">Use a draft label instead</option>
            {forKind("process").map(profile => <option key={profile.id} value={profile.id}>{profile.name} · {profile.status}</option>)}
          </select>
        </label>}
        <label>Engine process preset (draft label)
          <input required maxLength="200" disabled={!canPrepare || busy} value={form.process_preset} onChange={e => update("process_preset", e.target.value)} placeholder="Native quality/process preset" />
        </label>
        <label>Build plate
          <select disabled={!canPrepare || busy} value={form.plate} onChange={e => update("plate", e.target.value)}>
            <option value="default">Default plate</option>
          </select>
        </label>
        <div className="full settingsActions">
          <button type="submit" className="primary" disabled={!canPrepare || busy || loading || !stlFiles.length || !printers.length}>{busy ? "Saving…" : "Save slicing draft"}</button>
        </div>
      </form>
      {!stlFiles.length && <p>Add a plain-text STL model to Files or Model Library before preparing a slicing draft.</p>}
    </section>

    <section className="panel printingSection" aria-labelledby="slicer-profile-import">
      <h3 id="slicer-profile-import">Engine-native profiles</h3>
      <p>Import a preset exported by the selected slicer. PrusaSlicer INI and OrcaSlicer JSON remain separate. Imported profiles are preserved in private Files and are <strong>not verified for execution</strong>.</p>
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
      <div className="printingStack">
        {profiles.filter(item => item.engine === form.engine).map(profile =>
          <div className="cameraSourceRow" key={profile.id}>
            <div className="cameraSourceIdentity">
              <strong>{profile.name} · {profile.kind}</strong>
              <small>{profile.engine} {profile.engine_version} · {profile.status} · {profile.provenance || "No source supplied"}</small>
            </div>
          </div>
        )}
      </div>
    </section>

    <section className="panel printingSection" aria-label="Saved slicing drafts">
      <h3>Saved slicing drafts</h3>
      {jobs.length ? <div className="printingStack">{jobs.map(job =>
        <div key={job.id} className="cameraSourceRow">
          <div className="cameraSourceIdentity">
            <strong>{job.input_asset?.name || "Model"} · {job.printer?.name || "Printer"}</strong>
            <small>{job.engine} {job.engine_version} · {job.status} · {job.process_preset}</small>
            <small>{job.spool?.name ? "Spool " + job.spool.name + " · " : ""}
              {job.status === "completed" ? "G-code saved privately; inspect before printing" :
                job.status === "draft" ? "Configuration saved; not sliced" :
                job.message || "Waiting for job update"}</small>
            {(job.status === "queued" || job.status === "running") && <progress value={job.progress || 0} max="100" aria-label="Slicing progress" />}
          </div>
          <div className="cameraSourceActions">
            {job.can_slice && canPrepare && <button type="button" disabled={busy} onClick={() => startSlice(job)}>Slice now</button>}
            {job.status === "completed" && job.output_asset?.id && canPrint && <button type="button" className="primary" disabled={busy} onClick={() => requestPrint(job)}>Print from slicer</button>}
            {job.status === "completed" && job.output_asset_id && <button type="button" onClick={onOpenGcode}>Open G-code library</button>}
          </div>
        </div>
      )}</div> : <p>No slicing drafts saved yet.</p>}
    </section>

    {printSelection?.choosing && <Modal title="Choose printer connection" subtitle={"Print " + (printSelection.job.output_asset?.filename || "sliced G-code") + " on " + printSelection.printer.name} onClose={() => setPrintSelection(null)}>
      <p>This uses MakerVault's existing printer-submission checks and requires a separate confirmation before printing.</p>
      <div className="formGrid">
        <label className="full">Printer connection
          <select value={printSelection.connectionId} onChange={event => setPrintSelection(current => current ? { ...current, connectionId: event.target.value } : null)}>
            {availableSlicerPrintConnections(printSelection.printer).map(connection => <option key={connection.id} value={String(connection.id)}>{connection.adapter_label || connection.adapter || "Printer connection"}{connection.status ? " · " + connection.status : ""}</option>)}
          </select>
        </label>
        <div className="full settingsActions">
          <button type="button" onClick={() => setPrintSelection(null)}>Cancel</button>
          <button type="button" className="primary" onClick={openPrinterReview}>Review print</button>
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
        initialAction="print"
        onChanged={refresh}
        onClose={() => setPrintSelection(null)}
      /> : null;
    })()}
  </div>;
}
