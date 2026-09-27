import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock, Modal } from "./Common";

function grams(value) {
  if (value == null) return "—";
  return `${Number(value).toFixed(0)} g`;
}

function formatDate(value) {
  if (!value) return "Never";
  try { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
}

export default function PrintingPage({ config, projects }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [modal, setModal] = useState("");
  const [manageModel, setManageModel] = useState(null);

  async function load() {
    setError("");
    try {
      setData(await apiFetch("/api/printing/"));
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { load(); }, []);

  async function saved() {
    setModal("");
    await load();
  }

  if (!data && !error) return <LoadingBlock label="Loading 3D printing workspace…" />;

  const summary = data?.summary || {};
  const canAddPrinter = Boolean(config?.permissions?.add_printer);
  const canAddFilament = Boolean(config?.permissions?.add_filament);
  const canAddSpool = Boolean(config?.permissions?.add_spool);
  const canAddModel = Boolean(config?.permissions?.add_model3d);
  const canChangeModel = Boolean(config?.permissions?.change_model3d);

  return <div className="printingStack">
    <section className="panel printingHero">
      <div>
        <span className="settingsEyebrow">v0.6.0 foundation</span>
        <h2>3D Printing &amp; Model Library</h2>
        <p>Native MakerVault models, printers and spool inventory stay authoritative. External services and printer filament systems plug into this data rather than replacing it.</p>
      </div>
      <div className="printingHeroActions">
        {canAddPrinter && <button onClick={() => setModal("printer")}>＋ Printer</button>}
        {canAddFilament && <button onClick={() => setModal("filament")}>＋ Filament</button>}
        {canAddSpool && <button onClick={() => setModal("spool")}>＋ Spool</button>}
        {canAddModel && <button className="primary" onClick={() => setModal("model")}>＋ Model</button>}
        <button onClick={load}>Refresh</button>
      </div>
    </section>

    {error && <div className="error">{error}</div>}

    <div className="printingMetrics">
      <article><span>Models</span><strong>{summary.models || 0}</strong></article>
      <article><span>Printers</span><strong>{summary.printers || 0}</strong></article>
      <article><span>Spools</span><strong>{summary.spools || 0}</strong></article>
      <article><span>Loaded slots</span><strong>{summary.loaded_slots || 0}</strong></article>
      <article><span>External links</span><strong>{summary.externally_linked_spools || 0}</strong></article>
      <article><span>Print jobs</span><strong>{summary.print_jobs || 0}</strong></article>
    </div>

    <section className="panel printingSection">
      <div className="panelHead"><div><h3>Printers &amp; loaded filament</h3><p>Filament slots are provider-neutral so CFS, AMS and later systems can use the same model.</p></div></div>
      <div className="printingCards">
        {(data?.printers || []).map(printer => <article className="printingCard" key={printer.id}>
          <div className="printingCardHead"><div><strong>{printer.name}</strong><small>{[printer.manufacturer, printer.model].filter(Boolean).join(" · ")}</small></div><Badge>{printer.slots.length} slots</Badge></div>
          <div className="printingSlotGrid">
            {printer.slots.filter(slot => slot.is_loaded).map(slot => <div className="printingSlot" key={slot.id}>
              <span className="printingSwatch" style={slot.color_hex ? { background: slot.color_hex } : undefined} />
              <div><strong>{slot.material || "Unknown material"}</strong><small>{slot.system_label} · unit {slot.unit_index + 1}, slot {slot.slot_index + 1}</small><small>{slot.spool_code || "Unmatched spool"} · {grams(slot.remaining_weight_g)}</small></div>
            </div>)}
            {!printer.slots.some(slot => slot.is_loaded) && <div className="printingEmptyInline">No loaded filament slots have been discovered yet.</div>}
          </div>
        </article>)}
        {!data?.printers?.length && <div className="projectEmpty"><strong>No printers yet.</strong><span>Add your first printer to begin the 3D printing workspace.</span></div>}
      </div>
    </section>

    <section className="printingColumns">
      <div className="panel printingSection">
        <div className="panelHead"><div><h3>Spool inventory</h3><p>Native spool records with optional external mappings.</p></div></div>
        <div className="printingList">
          {(data?.spools || []).map(spool => <article className="printingListRow" key={spool.id}>
            <span className="printingSwatch" style={spool.color_hex ? { background: spool.color_hex } : undefined} />
            <div><strong>{spool.spool_id} · {spool.filament}</strong><small>{spool.material} · {grams(spool.remaining_weight_g)} remaining</small></div>
            <div className="printingBadges">{spool.loaded_slots.length > 0 && <Badge tone="accent">Loaded</Badge>}{spool.external_links.map(link => <Badge key={link.id}>{link.provider_label}</Badge>)}</div>
          </article>)}
          {!data?.spools?.length && <div className="printingEmptyInline">No spool records yet.</div>}
        </div>
      </div>

      <div className="panel printingSection">
        <div className="panelHead"><div><h3>Model library</h3><p>Revisions can reuse existing MakerVault files without duplicating storage.</p></div></div>
        <div className="printingList">
          {(data?.models || []).map(model => <article className="printingListRow printingModelRow" key={model.id}>
            <div><strong>{model.name}</strong><small>{model.project || "Standalone model"} · {model.revision_count} revision{model.revision_count === 1 ? "" : "s"}</small></div>
            <div className="printingBadges">{model.revisions.flatMap(r => r.assets).slice(0,3).map(asset => <Badge key={asset.id}>{asset.file.category_label}</Badge>)}</div>
            {canChangeModel && <button onClick={() => setManageModel(model)}>Manage</button>}
          </article>)}
          {!data?.models?.length && <div className="printingEmptyInline">No 3D models yet.</div>}
        </div>
      </div>
    </section>

    <section className="panel printingSection">
      <div className="panelHead"><div><h3>Integration foundation</h3><p>Optional adapters will synchronise around MakerVault rather than becoming required dependencies.</p></div></div>
      <div className="printingIntegrationGrid">
        <article><strong>Spoolman</strong><span>External spool mapping schema ready</span><Badge>Foundation</Badge></article>
        <article><strong>SimplyPrint</strong><span>Optional filament mapping planned</span><Badge>Planned</Badge></article>
        <article><strong>Creality CFS</strong><span>Provider-neutral loaded-slot schema ready</span><Badge>Foundation</Badge></article>
        <article><strong>AMS / other systems</strong><span>Generic adapter model reserved</span><Badge>Future adapters</Badge></article>
      </div>
    </section>

    {!!data?.recent_prints?.length && <section className="panel printingSection">
      <div className="panelHead"><div><h3>Recent prints</h3><p>Latest native MakerVault print history.</p></div></div>
      <div className="printingList">
        {data.recent_prints.map(job => <article className="printingListRow" key={job.id}>
          <div><strong>{job.model || "Unlinked print"}{job.revision ? ` · ${job.revision}` : ""}</strong><small>{job.printer} · {formatDate(job.created_at)}</small></div>
          <Badge tone={job.status === "success" ? "good" : job.status === "printing" ? "accent" : "neutral"}>{job.status_label}</Badge>
        </article>)}
      </div>
    </section>}

    {modal === "printer" && <PrinterModal manufacturers={data?.manufacturers || []} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "filament" && <FilamentModal manufacturers={data?.manufacturers || []} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "spool" && <SpoolModal filaments={data?.filaments || []} currency={config?.currency || "GBP"} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "model" && <ModelModal projects={projects || []} onClose={() => setModal("")} onSaved={saved} />}
    {manageModel && <ModelManageModal
      model={manageModel}
      files={data?.model_files || []}
      onClose={() => setManageModel(null)}
      onChanged={async () => { setManageModel(null); await load(); }}
    />}
  </div>;
}

function PrinterModal({ manufacturers, onClose, onSaved }) {
  const [form, setForm] = useState({ name: "", manufacturer_id: "", model: "", serial_number: "", location: "", build_volume_x_mm: "", build_volume_y_mm: "", build_volume_z_mm: "", nozzle_mm: "0.4", notes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { await apiFetch("/api/printing/printers/", { method: "POST", body: form }); await onSaved(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title="Add printer" subtitle="Create a native MakerVault printer record. Integrations can be attached later." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Name<input required value={form.name} onChange={e => set("name", e.target.value)} placeholder="Desk printer" /></label>
      <label>Manufacturer<select value={form.manufacturer_id} onChange={e => set("manufacturer_id", e.target.value)}><option value="">Unspecified</option>{manufacturers.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>Model<input required value={form.model} onChange={e => set("model", e.target.value)} placeholder="K2, K1, X1C…" /></label>
      <label>Serial number<input value={form.serial_number} onChange={e => set("serial_number", e.target.value)} /></label>
      <label>Location<input value={form.location} onChange={e => set("location", e.target.value)} /></label>
      <label>Nozzle (mm)<input type="number" min="0.1" step="0.05" value={form.nozzle_mm} onChange={e => set("nozzle_mm", e.target.value)} /></label>
      <label>Build X (mm)<input type="number" min="1" step="0.1" value={form.build_volume_x_mm} onChange={e => set("build_volume_x_mm", e.target.value)} /></label>
      <label>Build Y (mm)<input type="number" min="1" step="0.1" value={form.build_volume_y_mm} onChange={e => set("build_volume_y_mm", e.target.value)} /></label>
      <label>Build Z (mm)<input type="number" min="1" step="0.1" value={form.build_volume_z_mm} onChange={e => set("build_volume_z_mm", e.target.value)} /></label>
      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Add printer"}</button></div>
    </form>
  </Modal>;
}

function FilamentModal({ manufacturers, onClose, onSaved }) {
  const [form, setForm] = useState({ manufacturer_id: "", name: "", material: "PLA", color_name: "", color_hex: "", diameter_mm: "1.75", nominal_weight_g: "1000" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { await apiFetch("/api/printing/filaments/", { method: "POST", body: form }); await onSaved(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title="Add filament product" subtitle="Define the material/product once, then create one or more physical spools from it." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Manufacturer<select value={form.manufacturer_id} onChange={e => set("manufacturer_id", e.target.value)}><option value="">Unspecified</option>{manufacturers.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>Product name<input required value={form.name} onChange={e => set("name", e.target.value)} placeholder="PLA Basic" /></label>
      <label>Material<input required value={form.material} onChange={e => set("material", e.target.value)} placeholder="PLA, PETG, ASA…" /></label>
      <label>Colour name<input value={form.color_name} onChange={e => set("color_name", e.target.value)} /></label>
      <label>Colour<input type="color" value={form.color_hex || "#777777"} onChange={e => set("color_hex", e.target.value)} /></label>
      <label>Diameter (mm)<input type="number" step="0.01" min="0.1" value={form.diameter_mm} onChange={e => set("diameter_mm", e.target.value)} /></label>
      <label>Nominal weight (g)<input type="number" step="1" min="0" value={form.nominal_weight_g} onChange={e => set("nominal_weight_g", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Add filament"}</button></div>
    </form>
  </Modal>;
}

function SpoolModal({ filaments, currency, onClose, onSaved }) {
  const [form, setForm] = useState({ spool_id: "", filament_id: filaments[0]?.id || "", initial_weight_g: "", remaining_weight_g: "", purchase_cost: "", currency, location: "", status: "sealed", opened_on: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { await apiFetch("/api/printing/spools/", { method: "POST", body: form }); await onSaved(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title="Add physical spool" subtitle="This remains a native MakerVault spool even if you later link it to Spoolman or SimplyPrint." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Spool ID<input required value={form.spool_id} onChange={e => set("spool_id", e.target.value)} placeholder="SPL-0001" /></label>
      <label>Filament<select required value={form.filament_id} onChange={e => set("filament_id", e.target.value)}><option value="">Choose filament…</option>{filaments.map(x => <option key={x.id} value={x.id}>{x.display_name}</option>)}</select></label>
      {!filaments.length && <div className="formError full">Create a filament product before adding a spool.</div>}
      <label>Initial weight (g)<input type="number" min="0" step="0.1" value={form.initial_weight_g} onChange={e => set("initial_weight_g", e.target.value)} /></label>
      <label>Remaining weight (g)<input type="number" min="0" step="0.1" value={form.remaining_weight_g} onChange={e => set("remaining_weight_g", e.target.value)} /></label>
      <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}><option value="sealed">Sealed</option><option value="open">Open</option><option value="drying">Drying</option><option value="empty">Empty</option><option value="retired">Retired</option></select></label>
      <label>Location<input value={form.location} onChange={e => set("location", e.target.value)} /></label>
      <label>Purchase cost<input type="number" min="0" step="0.01" value={form.purchase_cost} onChange={e => set("purchase_cost", e.target.value)} /></label>
      <label>Opened on<input type="date" value={form.opened_on} onChange={e => set("opened_on", e.target.value)} /></label>
      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !filaments.length}>{busy ? "Saving…" : "Add spool"}</button></div>
    </form>
  </Modal>;
}

function ModelModal({ projects, onClose, onSaved }) {
  const [form, setForm] = useState({ name: "", project_id: "", description: "", source_url: "", license: "", tags: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { await apiFetch("/api/printing/models/", { method: "POST", body: form }); await onSaved(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title="Add 3D model" subtitle="Create the model record first; revisions and existing MakerVault files can then be attached without duplicating storage." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Name<input required value={form.name} onChange={e => set("name", e.target.value)} /></label>
      <label>Project<select value={form.project_id} onChange={e => set("project_id", e.target.value)}><option value="">Standalone model</option>{projects.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label className="full">Description<textarea rows="3" value={form.description} onChange={e => set("description", e.target.value)} /></label>
      <label>Source URL<input type="url" value={form.source_url} onChange={e => set("source_url", e.target.value)} /></label>
      <label>Licence<input value={form.license} onChange={e => set("license", e.target.value)} placeholder="CC BY 4.0, personal use…" /></label>
      <label className="full">Tags<input value={form.tags} onChange={e => set("tags", e.target.value)} placeholder="Comma-separated" /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Add model"}</button></div>
    </form>
  </Modal>;
}


function ModelManageModal({ model, files, onClose, onChanged }) {
  const [version, setVersion] = useState("");
  const [revisionNotes, setRevisionNotes] = useState("");
  const [revisionId, setRevisionId] = useState(model.revisions[0]?.id || "");
  const [fileId, setFileId] = useState("");
  const [role, setRole] = useState("model");
  const [primary, setPrimary] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const compatibleFiles = (files || []).filter(file => {
    if (!model.project_id || !file.project_id) return true;
    return model.project_id === file.project_id;
  });

  async function addRevision(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/models/" + model.id + "/revisions/", {
        method: "POST",
        body: { version, notes: revisionNotes },
      });
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function attachFile(event) {
    event.preventDefault();
    if (!revisionId || !fileId) return;
    setBusy(true); setError("");
    try {
      await apiFetch(
        "/api/printing/models/" + model.id + "/revisions/" + revisionId + "/assets/",
        {
          method: "POST",
          body: { file_asset_id: fileId, role, is_primary: primary },
        },
      );
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function detach(revision, asset) {
    if (!window.confirm('Detach "' + asset.file.name + '" from revision ' + revision.version + "? The file itself will remain in MakerVault.")) return;
    setBusy(true); setError("");
    try {
      await apiFetch(
        "/api/printing/models/" + model.id + "/revisions/" + revision.id + "/assets/" + asset.id + "/",
        { method: "DELETE" },
      );
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={"Manage model · " + model.name} subtitle="Revisions reuse existing MakerVault files; attaching or detaching does not duplicate or delete the stored asset." onClose={onClose} wide>
    <div className="printingModelManage">
      {error && <div className="formError">{error}</div>}

      <section>
        <h3>Revisions</h3>
        <div className="printingRevisionList">
          {model.revisions.map(revision => <article key={revision.id}>
            <div className="printingRevisionHead"><strong>Revision {revision.version}</strong><small>{revision.notes || "No notes"}</small></div>
            <div className="printingRevisionAssets">
              {revision.assets.map(asset => <div key={asset.id}>
                <div><strong>{asset.file.name}</strong><small>{asset.role_label}{asset.is_primary ? " · Primary" : ""} · {asset.file.filename}</small></div>
                <button type="button" disabled={busy} onClick={() => detach(revision, asset)}>Detach</button>
              </div>)}
              {!revision.assets.length && <span className="muted">No files attached.</span>}
            </div>
          </article>)}
          {!model.revisions.length && <div className="printingEmptyInline">No revisions yet.</div>}
        </div>
      </section>

      <form className="printingManageForm" onSubmit={addRevision}>
        <h3>Add revision</h3>
        <label>Version<input required value={version} onChange={e => setVersion(e.target.value)} placeholder="1.0, A, 2026-09…" /></label>
        <label>Notes<textarea rows="2" value={revisionNotes} onChange={e => setRevisionNotes(e.target.value)} /></label>
        <button className="primary" disabled={busy}>{busy ? "Saving…" : "Add revision"}</button>
      </form>

      <form className="printingManageForm" onSubmit={attachFile}>
        <h3>Attach existing MakerVault file</h3>
        <label>Revision<select required value={revisionId} onChange={e => setRevisionId(e.target.value)}><option value="">Choose revision…</option>{model.revisions.map(x => <option key={x.id} value={x.id}>{x.version}</option>)}</select></label>
        <label>File<select required value={fileId} onChange={e => setFileId(e.target.value)}><option value="">Choose STL / 3MF / CAD file…</option>{compatibleFiles.map(x => <option key={x.id} value={x.id}>{x.name} · {x.category_label}{x.project ? " · " + x.project : ""}</option>)}</select></label>
        <label>Role<select value={role} onChange={e => setRole(e.target.value)}><option value="model">Printable model</option><option value="slicer">Slicer project</option><option value="cad">CAD / source</option><option value="reference">Reference</option><option value="other">Other</option></select></label>
        <label className="checkRow"><input type="checkbox" checked={primary} onChange={e => setPrimary(e.target.checked)} /><span>Primary file for this role</span></label>
        {!compatibleFiles.length && <div className="printingEmptyInline">Upload an STL, 3MF or CAD file in Files first, then attach it here.</div>}
        <button className="primary" disabled={busy || !model.revisions.length || !compatibleFiles.length}>{busy ? "Saving…" : "Attach file"}</button>
      </form>
    </div>
  </Modal>;
}
