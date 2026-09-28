import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock, Modal } from "./Common";
import ModelViewerModal from "./ModelViewer";

function grams(value) {
  if (value == null) return "—";
  return `${Number(value).toFixed(0)} g`;
}

function formatDate(value) {
  if (!value) return "Never";
  try { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
}

function newestFirst(rows) {
  const activityTime = row => Math.max(
    new Date(row.updated_at || row.created_at || 0).getTime() || 0,
    ...((row.revisions || []).map(revision => new Date(revision.created_at || 0).getTime() || 0))
  );
  return [...(rows || [])].sort((a, b) => activityTime(b) - activityTime(a));
}

function hasViewableModelAsset(model) {
  return (model?.revisions || []).some(revision =>
    (revision.assets || []).some(asset => {
      const filename = (asset.file?.filename || asset.file?.name || "").toLowerCase();
      return Boolean(asset.file?.url) && (filename.endsWith(".stl") || filename.endsWith(".3mf"));
    })
  );
}

function newestGeometryAnalysis(model) {
  for (const revision of model?.revisions || []) {
    if (revision.geometry_analysis) return revision.geometry_analysis;
  }
  return null;
}

export default function PrintingPage({ config, projects }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [modal, setModal] = useState("");
  const [manageModel, setManageModel] = useState(null);
  const [managePrinter, setManagePrinter] = useState(null);
  const [claimSlot, setClaimSlot] = useState(null);
  const [workspaceView, setWorkspaceView] = useState("overview");

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
  const canChangePrinter = Boolean(config?.permissions?.change_printer);
  const canAddFilament = Boolean(config?.permissions?.add_filament);
  const canChangeFilament = Boolean(config?.permissions?.change_filament);
  const canAddSpool = Boolean(config?.permissions?.add_spool);
  const canChangeSpool = Boolean(config?.permissions?.change_spool);
  const canDeleteSpool = Boolean(config?.permissions?.delete_spool);
  const canAddModel = Boolean(config?.permissions?.add_model3d);
  const canChangeModel = Boolean(config?.permissions?.change_model3d);
  const canDeleteModel = Boolean(config?.permissions?.delete_model3d);
  const canAddPrintJob = Boolean(config?.permissions?.add_printjob);
  const canAddLocation = Boolean(config?.permissions?.add_printing_location);
  const recentSpools = newestFirst(data?.spools).slice(0, 5);
  const recentModels = newestFirst(data?.models).slice(0, 5);

  if (workspaceView === "filaments") {
    return <FilamentLibraryPage
      filaments={data?.filaments || []}
      manufacturers={data?.filament_manufacturers || []}
      materials={data?.common_filament_materials || []}
      canChangeFilament={canChangeFilament}
      onBack={() => setWorkspaceView("overview")}
      onChanged={load}
    />;
  }

  if (workspaceView === "spools") {
    return <SpoolInventoryPage
      spools={data?.spools || []}
      filaments={data?.filaments || []}
      locations={data?.locations || []}
      printers={data?.printers || []}
      currency={config?.currency || "GBP"}
      canAddSpool={canAddSpool}
      canChangeSpool={canChangeSpool}
      canDeleteSpool={canDeleteSpool}
      onBack={() => setWorkspaceView("overview")}
      onChanged={load}
    />;
  }

  if (workspaceView === "models") {
    return <ModelLibraryPage
      models={data?.models || []}
      files={data?.model_files || []}
      printers={data?.printers || []}
      projects={projects || []}
      canAddModel={canAddModel}
      canChangeModel={canChangeModel}
      canDeleteModel={canDeleteModel}
      canUpload={Boolean(config?.permissions?.add_file)}
      onBack={() => setWorkspaceView("overview")}
      onChanged={load}
    />;
  }

  return <div className="printingStack">
    <section className="panel printingHero">
      <div>
        <span className="settingsEyebrow">Model intelligence</span>
        <h2>3D Printing &amp; Model Library</h2>
        <p>Native MakerVault models, printers and spool inventory stay authoritative. External services and printer filament systems plug into this data rather than replacing it.</p>
      </div>
      <div className="printingHeroActions">
        {canAddPrinter && <button onClick={() => setModal("printer")}>＋ Printer</button>}
        {canAddLocation && <button onClick={() => setModal("location")}>＋ Location</button>}
        {canAddFilament && <button onClick={() => setModal("filament")}>＋ Filament</button>}
        <button onClick={() => setWorkspaceView("filaments")}>Filament library</button>
        {canAddFilament && <button onClick={() => setModal("filamentCatalogue")}>⌕ Filament catalogue</button>}
        {canAddSpool && <button onClick={() => setModal("spool")}>＋ Spool</button>}
        {canAddModel && <button className="primary" onClick={() => setModal("model")}>＋ Model</button>}
        {canAddPrintJob && <button onClick={() => setModal("print")}>＋ Print history</button>}
        <button onClick={load}>Refresh</button>
      </div>
    </section>

    {error && <div className="error">{error}</div>}

    <div className="printingMetrics">
      <article><span>Models</span><strong>{summary.models || 0}</strong></article>
      <article><span>Active printers</span><strong>{summary.active_printers || 0}</strong></article>
      <article><span>Filaments</span><strong>{summary.filaments || 0}</strong></article>
      <article><span>Spools</span><strong>{summary.spools || 0}</strong></article>
      <article><span>Loaded slots</span><strong>{summary.loaded_slots || 0}</strong></article>
      <article><span>Print jobs</span><strong>{summary.print_jobs || 0}</strong></article>
    </div>


    {!!data?.integrations?.length && <section className="printingIntegrationStatusBar" aria-label="Enabled integration status">
      {data.integrations.map(item => {
        const tone = item.status === "connected" ? "good" : item.status === "error" || item.status === "disconnected" ? "danger" : "neutral";
        return <div className={"printingIntegrationStatus printingIntegrationStatus-" + item.status} key={item.provider}>
          <span className="printingIntegrationDot" />
          <strong>{item.name}</strong>
          <Badge tone={tone}>{item.status_label}</Badge>
          <small>{item.last_sync_at ? "Last sync " + formatDate(item.last_sync_at) : "Not synced yet"}</small>
          {item.auto_sync && item.next_sync_at && <small>Next {formatDate(item.next_sync_at)}</small>}
        </div>;
      })}
    </section>}

    <section className="panel printingSection">
      <div className="panelHead"><div><h3>Printers &amp; loaded filament</h3><p>Filament slots are provider-neutral so CFS, AMS and later systems can use the same model.</p></div></div>
      <div className="printingCards">
        {(data?.printers || []).map(printer => <article className="printingCard printingPrinterCard" key={printer.id}>
          <div className="printingPrinterHeader">
            <div className="printingPrinterImage">
              {(printer.multi_material_installed && printer.catalogue?.image_multi_material) || printer.catalogue?.image
                ? <img
                    src={(printer.multi_material_installed && printer.catalogue?.image_multi_material) || printer.catalogue?.image}
                    alt={printer.catalogue.display_name || printer.model || printer.name}
                    loading="lazy"
                  />
                : <span aria-hidden="true">3D</span>}
            </div>
            <div className="printingPrinterHeaderMain">
              <div className="printingCardHead">
                <div><strong>{printer.name}</strong><small>{[printer.manufacturer, printer.model, printer.location].filter(Boolean).join(" · ")}</small></div>
                <div className="printingBadges">
                  {printer.is_active ? <Badge tone="good">Active</Badge> : <Badge>Inactive</Badge>}
                  {printer.simplyprint?.external_id && <Badge tone={printer.simplyprint?.online ? "good" : printer.simplyprint?.state === "offline" ? "danger" : "accent"}>SimplyPrint · {printer.simplyprint?.state || (printer.simplyprint?.online ? "online" : "linked")}</Badge>}
                  {printer.installed_multi_material_label && <Badge>{printer.installed_multi_material_label}</Badge>}
                  {printer.multi_material_installed && <Badge>{printer.slots.length} slots</Badge>}
                  {canChangePrinter && <button type="button" onClick={() => setManagePrinter(printer)}>Manage</button>}
                </div>
              </div>
              {((printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_source_provider) || printer.catalogue?.image_source_provider) && <small className="printingPrinterImageCredit">
                Image: {(printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_source_provider) || printer.catalogue?.image_source_provider}
                {((printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_license) || printer.catalogue?.image_license) ? " · " + ((printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_license) || printer.catalogue?.image_license) : ""}
              </small>}
            </div>
          </div>
          <div className="printingSlotGrid">
            {printer.slots.filter(slot => slot.is_loaded).map(slot => <div className="printingSlot" key={slot.id}>
              <span className="printingSwatch" style={slot.color_hex ? { background: slot.color_hex } : undefined} />
              <div>
                <strong>{slot.product_name || slot.material || "Unknown material"}</strong>
                <small>{[slot.vendor, slot.material].filter(Boolean).join(" · ")}{slot.vendor || slot.material ? " · " : ""}{slot.system_label} · unit {slot.unit_index + 1}, slot {slot.slot_index + 1}</small>
                <small>{slot.spool_code || "Unmatched MakerVault spool"} · {slot.remaining_percent != null ? Math.round(slot.remaining_percent) + "% remaining" : grams(slot.remaining_weight_g)}</small>
                {!slot.spool_id && canAddSpool && <button className="slotInventoryAction" type="button" onClick={() => setClaimSlot({ printer, slot })}>＋ Add to inventory</button>}
              </div>
            </div>)}
            {!printer.slots.some(slot => slot.is_loaded) && (
              !printer.multi_material_installed
                ? <div className="printingEmptyInline">No loaded filament slots discovered. No native multi-material add-on is marked as installed.</div>
                : <div className="printingEmptyInline">No loaded filament slots have been discovered yet.</div>
            )}
          </div>
        </article>)}
        {!data?.printers?.length && <div className="projectEmpty"><strong>No printers yet.</strong><span>Add your first printer to begin the 3D printing workspace.</span></div>}
      </div>
    </section>

    <section className="printingColumns">
      <div className="panel printingSection">
        <div className="panelHead"><div><h3>Spool inventory</h3><p>Showing the 5 most recently updated spools.</p></div><button onClick={() => setWorkspaceView("spools")}>View all {summary.spools || 0}</button></div>
        <div className="printingList">
          {recentSpools.map(spool => <article className="printingListRow" key={spool.id}>
            <span className={"printingSwatch filamentPreview-" + (spool.transparency || "opaque")} style={filamentSwatchStyle(spool)} />
            <div><strong>{spool.spool_id} · {spool.filament}</strong><small>{spool.material} · {grams(spool.remaining_weight_g)} remaining{spool.location ? " · " + spool.location : ""}</small></div>
            <div className="printingBadges">{spool.loaded_slots.length > 0 && <Badge tone="accent">Loaded</Badge>}{spool.external_links.map(link => <Badge key={link.id}>{link.provider_label}</Badge>)}</div>
          </article>)}
          {!recentSpools.length && <div className="printingEmptyInline">No spool records yet.</div>}
        </div>
      </div>

      <div className="panel printingSection">
        <div className="panelHead"><div><h3>Model library</h3><p>Showing the 5 most recently updated models.</p></div><button onClick={() => setWorkspaceView("models")}>View all {summary.models || 0}</button></div>
        <div className="printingList">
          {recentModels.map(model => <article className="printingListRow printingModelRow" key={model.id}>
            <div><strong>{model.name}</strong><small>{model.project || "Standalone model"} · {model.revision_count} revision{model.revision_count === 1 ? "" : "s"}</small></div>
            <div className="printingBadges">{model.revisions.flatMap(r => r.assets).slice(0,3).map(asset => <Badge key={asset.id}>{asset.file.category_label}</Badge>)}</div>
            {canChangeModel && <button onClick={() => setManageModel(model)}>Manage</button>}
          </article>)}
          {!recentModels.length && <div className="printingEmptyInline">No 3D models yet.</div>}
        </div>
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

    {modal === "printer" && <PrinterModal manufacturers={data?.printer_manufacturers || []} models={data?.printer_catalogue_models || []} locations={data?.locations || []} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "location" && <LocationModal onClose={() => setModal("")} onSaved={saved} />}
    {modal === "filament" && <FilamentModal manufacturers={data?.filament_manufacturers || []} materials={data?.common_filament_materials || []} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "filamentCatalogue" && <FilamentCatalogueModal onClose={() => setModal("")} onImported={saved} />}
    {modal === "spool" && <SpoolModal filaments={data?.filaments || []} locations={data?.locations || []} printers={data?.printers || []} currency={config?.currency || "GBP"} onClose={() => setModal("")} onSaved={saved} />}
    {claimSlot && <DiscoveredSpoolModal
      printer={claimSlot.printer}
      slot={claimSlot.slot}
      filaments={data?.filaments || []}
      spools={data?.spools || []}
      currency={config?.currency || "GBP"}
      canCreateFilament={canAddFilament}
      canLinkExisting={canChangeSpool}
      onClose={() => setClaimSlot(null)}
      onSaved={async () => { setClaimSlot(null); await load(); }}
    />}
    {modal === "model" && <ModelModal projects={projects || []} canUpload={Boolean(config?.permissions?.add_file)} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "print" && <PrintJobModal
      printers={data?.printers || []}
      spools={data?.spools || []}
      models={data?.models || []}
      projects={projects || []}
      currency={config?.currency || "GBP"}
      onClose={() => setModal("")}
      onSaved={saved}
    />}
    {managePrinter && <PrinterManageModal
      printer={managePrinter}
      manufacturers={data?.printer_manufacturers || []}
      models={data?.printer_catalogue_models || []}
      locations={data?.locations || []}
      onClose={() => setManagePrinter(null)}
      onSaved={async () => { setManagePrinter(null); await load(); }}
    />}
    {manageModel && <ModelManageModal
      model={manageModel}
      files={data?.model_files || []}
      onClose={() => setManageModel(null)}
      onChanged={async () => { setManageModel(null); await load(); }}
    />}
  </div>;
}

function SpoolInventoryPage({ spools, filaments, locations, printers, currency, canAddSpool, canChangeSpool, canDeleteSpool, onBack, onChanged }) {
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [manageSpool, setManageSpool] = useState(null);
  const [deleteSpool, setDeleteSpool] = useState(null);
  const term = query.trim().toLowerCase();
  const rows = newestFirst(spools).filter(spool => !term || [
    spool.spool_id, spool.rfid_uid, spool.filament, spool.manufacturer, spool.material, spool.color_name, spool.location,
    ...(spool.external_links || []).map(link => link.provider_label),
  ].filter(Boolean).join(" ").toLowerCase().includes(term));

  return <div className="printingStack">
    <section className="panel printingLibraryHero">
      <div>
        <span className="settingsEyebrow">3D Printing</span>
        <h2>Spool Inventory</h2>
        <p>MakerVault-native spool records. External integrations add context and links without replacing your local inventory decisions.</p>
      </div>
      <div className="printingHeroActions">
        <button onClick={onBack}>← Printing overview</button>
        {canAddSpool && <button className="primary" onClick={() => setAddOpen(true)}>＋ Spool</button>}
      </div>
    </section>

    <section className="panel printingSection">
      <div className="printingLibraryToolbar">
        <div><strong>{spools.length} spool{spools.length === 1 ? "" : "s"}</strong><small>{rows.length !== spools.length ? rows.length + " matching" : "Newest updated first"}</small></div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search ID, filament, material, location or integration…" />
      </div>
      <div className="printingList">
        {rows.map(spool => <article className="printingListRow printingLibraryRow" key={spool.id}>
          <span className={"printingSwatch filamentPreview-" + (spool.transparency || "opaque")} style={filamentSwatchStyle(spool)} />
          <div>
            <strong>{spool.spool_id} · {spool.filament}</strong>
            <small>{[spool.manufacturer, spool.material, spool.color_name].filter(Boolean).join(" · ")} · {grams(spool.remaining_weight_g)} remaining{spool.location ? " · " + spool.location : ""}</small>
            <small>{spool.rfid_uid ? "RFID " + spool.rfid_uid + " · " : ""}Updated {formatDate(spool.updated_at)}</small>
          </div>
          <div className="printingBadges">
            {spool.loaded_slots?.length > 0 && <Badge tone="accent">Loaded</Badge>}
            <Badge>{spool.status_label || spool.status}</Badge>
            {(spool.external_links || []).map(link => <Badge key={link.id}>{link.provider_label}</Badge>)}
            {canChangeSpool && <button type="button" onClick={() => setManageSpool(spool)}>RFID / identity</button>}
            {canDeleteSpool && <button className="dangerButton" type="button" onClick={() => setDeleteSpool(spool)}>Delete</button>}
          </div>
        </article>)}
        {!rows.length && <div className="printingEmptyInline">{term ? "No spools match this search." : "No spool records yet."}</div>}
      </div>
    </section>

    {addOpen && <SpoolModal filaments={filaments} locations={locations} printers={printers} currency={currency} onClose={() => setAddOpen(false)} onSaved={async () => { setAddOpen(false); await onChanged(); }} />}
    {manageSpool && <SpoolIdentityModal spool={manageSpool} onClose={() => setManageSpool(null)} onSaved={async () => { setManageSpool(null); await onChanged(); }} />}
    {deleteSpool && <DeletePrintingRecordModal
      title={"Delete spool · " + deleteSpool.spool_id}
      description={"Delete " + deleteSpool.spool_id + " from MakerVault spool inventory?"}
      warning="This removes the physical spool record and its external integration links. Any currently loaded printer slot will become unmatched. The filament product itself is not deleted."
      endpoint={"/api/printing/spools/" + deleteSpool.id + "/"}
      onClose={() => setDeleteSpool(null)}
      onDeleted={async () => { setDeleteSpool(null); await onChanged(); }}
    />}
  </div>;
}


function SpoolIdentityModal({ spool, onClose, onSaved }) {
  const [rfidUid, setRfidUid] = useState(spool.rfid_uid || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/spools/" + spool.id + "/", {
        method: "PATCH",
        body: { rfid_uid: rfidUid.trim().toUpperCase() },
      });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal
    title={"Physical identity · " + spool.spool_id}
    subtitle="RFID identifies this exact physical reel. Brand, material and colour describe the filament product and are not sufficient to identify a particular spool."
    onClose={onClose}
  >
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <div className="settingsCallout full">
        <strong>{spool.filament}</strong>
        <p>{[spool.manufacturer, spool.material, spool.color_name].filter(Boolean).join(" · ") || "Filament"}</p>
      </div>
      <label className="full">RFID tag ID<input autoFocus value={rfidUid} onChange={e => setRfidUid(e.target.value.toUpperCase())} placeholder="Optional physical tag ID" /><small>Each non-empty tag ID can belong to only one MakerVault spool.</small></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save RFID identity"}</button></div>
    </form>
  </Modal>;
}


function ModelLibraryPage({ models, files, printers, projects, canAddModel, canChangeModel, canDeleteModel, canUpload, onBack, onChanged }) {
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [manageModel, setManageModel] = useState(null);
  const [viewerModel, setViewerModel] = useState(null);
  const [deleteModel, setDeleteModel] = useState(null);
  const term = query.trim().toLowerCase();
  const rows = newestFirst(models).filter(model => !term || [
    model.name, model.project, model.description, ...(model.tags || []),
  ].filter(Boolean).join(" ").toLowerCase().includes(term));

  return <div className="printingStack">
    <section className="panel printingLibraryHero">
      <div>
        <span className="settingsEyebrow">3D Printing</span>
        <h2>Model Library</h2>
        <p>All printable models, revisions and attached STL/3MF/CAD assets in one dedicated library.</p>
      </div>
      <div className="printingHeroActions">
        <button onClick={onBack}>← Printing overview</button>
        {canAddModel && <button className="primary" onClick={() => setAddOpen(true)}>＋ Model</button>}
      </div>
    </section>

    <section className="panel printingSection">
      <div className="printingLibraryToolbar">
        <div><strong>{models.length} model{models.length === 1 ? "" : "s"}</strong><small>{rows.length !== models.length ? rows.length + " matching" : "Newest updated first"}</small></div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search model, project, description or tag…" />
      </div>
      <div className="printingList">
        {rows.map(model => {
          const analysis = newestGeometryAnalysis(model);
          const dims = analysis?.dimensions_mm;
          return <article className="printingListRow printingModelRow printingLibraryRow" key={model.id}>
            <div>
              <strong>{model.name}</strong>
              <small>{model.project || "Standalone model"} · {model.revision_count} revision{model.revision_count === 1 ? "" : "s"} · updated {formatDate(model.updated_at)}</small>
              {analysis && <small className="modelAnalysisInline">
                {dims ? [dims.x, dims.y, dims.z].map(value => Number(value).toFixed(1)).join(" × ") + " mm" : "Geometry analysed"}
                {analysis.triangle_count != null ? " · " + Number(analysis.triangle_count).toLocaleString() + " triangles" : ""}
              </small>}
            </div>
            <div className="printingBadges">
              {model.revisions.flatMap(r => r.assets).slice(0, 4).map(asset => <Badge key={asset.id}>{asset.file.category_label}</Badge>)}
              {analysis && <Badge tone="good">Analysed</Badge>}
            </div>
            <div className="printingLibraryActions">
              {hasViewableModelAsset(model) && <button className="primary" type="button" onClick={() => setViewerModel(model)}>View 3D</button>}
              {canChangeModel && <button onClick={() => setManageModel(model)}>Manage</button>}
              {canDeleteModel && <button className="dangerButton" type="button" onClick={() => setDeleteModel(model)}>Delete</button>}
            </div>
          </article>;
        })}
        {!rows.length && <div className="printingEmptyInline">{term ? "No models match this search." : "No 3D models yet."}</div>}
      </div>
    </section>

    {addOpen && <ModelModal projects={projects} canUpload={canUpload} onClose={() => setAddOpen(false)} onSaved={async () => { setAddOpen(false); await onChanged(); }} />}
    {manageModel && <ModelManageModal model={manageModel} files={files} onClose={() => setManageModel(null)} onChanged={async () => { setManageModel(null); await onChanged(); }} />}
    {viewerModel && <ModelViewerModal
      model={viewerModel}
      printers={printers}
      canAnalyse={canChangeModel}
      onClose={() => setViewerModel(null)}
      onChanged={onChanged}
    />}
    {deleteModel && <DeletePrintingRecordModal
      title={"Delete model · " + deleteModel.name}
      description={"Delete " + deleteModel.name + " and its " + deleteModel.revision_count + " revision" + (deleteModel.revision_count === 1 ? "" : "s") + "?"}
      warning="Model revisions and their attachment links are removed. Shared MakerVault file records and stored STL/3MF/CAD files are kept, and print-history records are retained."
      endpoint={"/api/printing/models/" + deleteModel.id + "/"}
      onClose={() => setDeleteModel(null)}
      onDeleted={async () => { setDeleteModel(null); await onChanged(); }}
    />}
  </div>;
}


function DeletePrintingRecordModal({ title, description, warning, endpoint, onClose, onDeleted }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function remove() {
    setBusy(true); setError("");
    try {
      await apiFetch(endpoint, { method: "DELETE" });
      await onDeleted();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={title} subtitle="This action cannot be undone." onClose={busy ? () => {} : onClose}>
    <div className="formGrid">
      {error && <div className="formError full">{error}</div>}
      <div className="settingsCallout full">
        <strong>{description}</strong>
        <p>{warning}</p>
      </div>
      <div className="formActions full">
        <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="dangerButton" type="button" onClick={remove} disabled={busy}>{busy ? "Deleting…" : "Delete permanently"}</button>
      </div>
    </div>
  </Modal>;
}


function LocationModal({ onClose, onSaved }) {
  const [form, setForm] = useState({ name: "", kind: "storage", notes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/locations/", { method: "POST", body: form });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add printing location" subtitle="Create reusable storage and printer locations for spools and owned machines." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Name<input required value={form.name} onChange={e => set("name", e.target.value)} placeholder="Workshop shelf A" /></label>
      <label>Type<select value={form.kind} onChange={e => set("kind", e.target.value)}>
        <option value="room">Room / area</option>
        <option value="workshop">Workshop</option>
        <option value="shelf">Shelf</option>
        <option value="drybox">Dry box</option>
        <option value="storage">Storage</option>
        <option value="other">Other</option>
      </select></label>
      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Add location"}</button></div>
    </form>
  </Modal>;
}

function PrinterManageModal({ printer, manufacturers, models, locations, onClose, onSaved }) {
  const initialMaker = printer.manufacturer_id || manufacturers.find(x => x.name === printer.manufacturer)?.id || "";
  const [form, setForm] = useState({
    name: printer.name || "",
    printer_manufacturer_id: initialMaker,
    catalog_model_id: printer.catalog_model_id || "",
    model: printer.model || "",
    serial_number: printer.serial_number || "",
    location_id: printer.location_id || "",
    connection_host: printer.connection_host || "",
    is_active: printer.is_active !== false,
    multi_material_installed: printer.multi_material_installed === true,
    build_volume_x_mm: printer.build_volume?.x ?? "",
    build_volume_y_mm: printer.build_volume?.y ?? "",
    build_volume_z_mm: printer.build_volume?.z ?? "",
    nozzle_mm: printer.nozzle_mm ?? "0.4",
  });
  const [customModel, setCustomModel] = useState(!printer.catalog_model_id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));
  const modelOptions = models.filter(item => item.manufacturer_id === form.printer_manufacturer_id);
  const selectedModel = models.find(item => item.id === form.catalog_model_id);

  function makerChanged(value) {
    setCustomModel(false);
    setForm(current => ({
      ...current,
      printer_manufacturer_id: value,
      catalog_model_id: "",
      model: "",
      multi_material_installed: false,
      build_volume_x_mm: "",
      build_volume_y_mm: "",
      build_volume_z_mm: "",
      nozzle_mm: "0.4",
    }));
  }

  function modelChanged(value) {
    if (value === "__custom__") {
      setCustomModel(true);
      setForm(current => ({ ...current, catalog_model_id: "", model: "", multi_material_installed: false }));
      return;
    }
    const selected = models.find(item => item.id === value);
    if (!selected) return;
    setCustomModel(false);
    setForm(current => ({
      ...current,
      catalog_model_id: selected.id,
      model: selected.name,
      multi_material_installed: false,
      build_volume_x_mm: selected.build_volume?.x ?? "",
      build_volume_y_mm: selected.build_volume?.y ?? "",
      build_volume_z_mm: selected.build_volume?.z ?? "",
      nozzle_mm: selected.nozzle_mm ?? "0.4",
    }));
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/printers/" + printer.id + "/", {
        method: "PATCH",
        body: form,
      });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={"Manage printer · " + printer.name} subtitle="Update the owned-printer record, catalogue profile, location and local connection used by optional integrations." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Manufacturer<select required value={form.printer_manufacturer_id} onChange={e => makerChanged(e.target.value)}>
        <option value="">Choose manufacturer…</option>
        {manufacturers.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
      </select></label>
      <label>Model<select value={customModel ? "__custom__" : form.catalog_model_id} onChange={e => modelChanged(e.target.value)} disabled={!form.printer_manufacturer_id}>
        <option value="">Choose model…</option>
        {modelOptions.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
        <option value="__custom__">Other / custom model</option>
      </select></label>
      {customModel && <label>Custom model<input required value={form.model} onChange={e => set("model", e.target.value)} /></label>}
      <label>Printer name<input required value={form.name} onChange={e => set("name", e.target.value)} /></label>
      <label>Serial number<input value={form.serial_number} onChange={e => set("serial_number", e.target.value)} /></label>
      <label>Location<select value={form.location_id} onChange={e => set("location_id", e.target.value)}><option value="">Unassigned</option>{locations.map(x => <option key={x.id} value={x.id}>{x.name} · {x.kind_label}</option>)}</select></label>
      <label>Local host / IP<input value={form.connection_host} onChange={e => set("connection_host", e.target.value)} placeholder="192.168.1.34" /></label>
      {selectedModel?.multi_material_system && <label className="settingsToggle full"><div><strong>{selectedModel.multi_material_label} installed</strong><small>This is an optional add-on for this owned printer. Turning it off retires its live slot assignments until it is enabled and synced again.</small></div><input type="checkbox" checked={form.multi_material_installed} onChange={e => set("multi_material_installed", e.target.checked)} /></label>}
      <label>Nozzle (mm)<input type="number" min="0.1" step="0.05" value={form.nozzle_mm} onChange={e => set("nozzle_mm", e.target.value)} /></label>
      <label>Build X (mm)<input type="number" min="1" step="0.1" value={form.build_volume_x_mm} onChange={e => set("build_volume_x_mm", e.target.value)} /></label>
      <label>Build Y (mm)<input type="number" min="1" step="0.1" value={form.build_volume_y_mm} onChange={e => set("build_volume_y_mm", e.target.value)} /></label>
      <label>Build Z (mm)<input type="number" min="1" step="0.1" value={form.build_volume_z_mm} onChange={e => set("build_volume_z_mm", e.target.value)} /></label>
      <label className="settingsToggle full"><div><strong>Currently in use</strong><small>Inactive printers remain available in historical print records.</small></div><input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save printer"}</button></div>
    </form>
  </Modal>;
}

function PrinterModal({ manufacturers, models, locations, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: "",
    printer_manufacturer_id: manufacturers[0]?.id || "",
    catalog_model_id: "",
    model: "",
    serial_number: "",
    location_id: "",
    connection_host: "",
    is_active: true,
    multi_material_installed: false,
    build_volume_x_mm: "",
    build_volume_y_mm: "",
    build_volume_z_mm: "",
    nozzle_mm: "0.4",
    notes: "",
  });
  const [customModel, setCustomModel] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));

  const modelOptions = models.filter(item => item.manufacturer_id === form.printer_manufacturer_id);
  const selectedModel = models.find(item => item.id === form.catalog_model_id);

  function manufacturerChanged(value) {
    setCustomModel(false);
    setForm(current => ({
      ...current,
      printer_manufacturer_id: value,
      catalog_model_id: "",
      model: "",
      multi_material_installed: false,
      build_volume_x_mm: "",
      build_volume_y_mm: "",
      build_volume_z_mm: "",
      nozzle_mm: "0.4",
    }));
  }

  function modelChanged(value) {
    if (value === "__custom__") {
      setCustomModel(true);
      setForm(current => ({
        ...current,
        catalog_model_id: "",
        model: "",
        multi_material_installed: false,
        build_volume_x_mm: "",
        build_volume_y_mm: "",
        build_volume_z_mm: "",
        nozzle_mm: "0.4",
      }));
      return;
    }
    const selected = models.find(item => item.id === value);
    if (!selected) return;
    setCustomModel(false);
    setForm(current => ({
      ...current,
      catalog_model_id: selected.id,
      model: selected.name,
      name: current.name || selected.name,
      multi_material_installed: false,
      build_volume_x_mm: selected.build_volume?.x ?? "",
      build_volume_y_mm: selected.build_volume?.y ?? "",
      build_volume_z_mm: selected.build_volume?.z ?? "",
      nozzle_mm: selected.nozzle_mm ?? "0.4",
    }));
  }

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/printers/", { method: "POST", body: form });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add owned printer" subtitle="Choose a known printer model to populate its specifications, or create a custom printer record." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Manufacturer<select required value={form.printer_manufacturer_id} onChange={e => manufacturerChanged(e.target.value)}>
        <option value="">Choose manufacturer…</option>
        {manufacturers.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
      </select></label>
      <label>Model<select required={!!form.printer_manufacturer_id} value={customModel ? "__custom__" : form.catalog_model_id} onChange={e => modelChanged(e.target.value)} disabled={!form.printer_manufacturer_id}>
        <option value="">Choose model…</option>
        {modelOptions.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
        <option value="__custom__">Other / custom model</option>
      </select></label>
      {customModel && form.printer_manufacturer_id && <label>Custom model<input required value={form.model} onChange={e => set("model", e.target.value)} placeholder="Printer model" /></label>}
      <label>Printer name<input required value={form.name} onChange={e => set("name", e.target.value)} placeholder={selectedModel ? selectedModel.display_name : "Desk printer"} /></label>
      <label>Serial number<input value={form.serial_number} onChange={e => set("serial_number", e.target.value)} /></label>
      <label>Location<select value={form.location_id} onChange={e => set("location_id", e.target.value)}><option value="">Unassigned</option>{locations.map(x => <option key={x.id} value={x.id}>{x.name} · {x.kind_label}</option>)}</select></label>
      <label>Local host / IP<input value={form.connection_host} onChange={e => set("connection_host", e.target.value)} placeholder="192.168.1.34" /><small>Used by optional local printer/CFS adapters.</small></label>
      {selectedModel?.multi_material_system && <label className="settingsToggle full"><div><strong>{selectedModel.multi_material_label} installed</strong><small>This printer model supports the add-on, but it is optional. Check this only when the hardware is actually fitted.</small></div><input type="checkbox" checked={form.multi_material_installed} onChange={e => set("multi_material_installed", e.target.checked)} /></label>}
      <label>Nozzle (mm)<input type="number" min="0.1" step="0.05" value={form.nozzle_mm} onChange={e => set("nozzle_mm", e.target.value)} /></label>
      <label>Build X (mm)<input type="number" min="1" step="0.1" value={form.build_volume_x_mm} onChange={e => set("build_volume_x_mm", e.target.value)} /></label>
      <label>Build Y (mm)<input type="number" min="1" step="0.1" value={form.build_volume_y_mm} onChange={e => set("build_volume_y_mm", e.target.value)} /></label>
      <label>Build Z (mm)<input type="number" min="1" step="0.1" value={form.build_volume_z_mm} onChange={e => set("build_volume_z_mm", e.target.value)} /></label>
      <label className="settingsToggle full"><div><strong>Currently in use</strong><small>Inactive printers remain in your owned-printer catalogue and print history.</small></div><input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} /></label>
      {selectedModel && <div className="settingsCallout full"><strong>Catalogue profile</strong><p>{selectedModel.build_volume?.x || "?"} × {selectedModel.build_volume?.y || "?"} × {selectedModel.build_volume?.z || "?"} mm · {selectedModel.enclosed === true ? "Enclosed" : selectedModel.enclosed === false ? "Open" : "Enclosure unknown"}{selectedModel.multi_material_label ? " · " + selectedModel.multi_material_label : ""}</p></div>}
      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !form.printer_manufacturer_id}>{busy ? "Saving…" : "Add printer"}</button></div>
    </form>
  </Modal>;
}


function FilamentLibraryPage({ filaments, manufacturers, materials, canChangeFilament, onBack, onChanged }) {
  const [query, setQuery] = useState("");
  const [editFilament, setEditFilament] = useState(null);
  const term = query.trim().toLowerCase();
  const rows = newestFirst(filaments).filter(item => !term || [
    item.display_name, item.name, item.manufacturer, item.material, item.color_name,
    item.finish, item.pattern, item.source,
  ].filter(Boolean).join(" ").toLowerCase().includes(term));

  return <div className="printingStack">
    <section className="panel printingLibraryHero">
      <div>
        <span className="settingsEyebrow">3D Printing</span>
        <h2>Filament Library</h2>
        <p>Saved filament products shared by physical spools. Editing a product updates its descriptive data everywhere that product is used.</p>
      </div>
      <div className="printingHeroActions">
        <button onClick={onBack}>← Printing overview</button>
      </div>
    </section>

    <section className="panel printingSection">
      <div className="printingLibraryToolbar">
        <div><strong>{filaments.length} filament product{filaments.length === 1 ? "" : "s"}</strong><small>{rows.length !== filaments.length ? rows.length + " matching" : "Newest updated first"}</small></div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search manufacturer, product, material, colour or source…" />
      </div>
      <div className="printingList">
        {rows.map(item => <article className="printingListRow printingLibraryRow" key={item.id}>
          <span className={"printingSwatch filamentPreview-" + (item.transparency || "opaque")} style={filamentSwatchStyle(item)} />
          <div>
            <strong>{item.display_name || item.name}</strong>
            <small>{[item.manufacturer, item.material, item.color_name].filter(Boolean).join(" · ")}</small>
            <small>{item.diameter_mm || "?"} mm · {grams(item.nominal_weight_g)} nominal · {item.source || "Manual"}</small>
          </div>
          <div className="printingBadges">
            {item.transparency && item.transparency !== "opaque" && <Badge>{item.transparency_label || item.transparency}</Badge>}
            {item.glow && <Badge>Glow</Badge>}
            {canChangeFilament && <button type="button" onClick={() => setEditFilament(item)}>Edit</button>}
          </div>
        </article>)}
        {!rows.length && <div className="printingEmptyInline">{term ? "No filament products match this search." : "No saved filament products yet."}</div>}
      </div>
    </section>

    {editFilament && <FilamentEditModal
      filament={editFilament}
      manufacturers={manufacturers}
      materials={materials}
      onClose={() => setEditFilament(null)}
      onSaved={async () => { setEditFilament(null); await onChanged(); }}
    />}
  </div>;
}


function FilamentEditModal({ filament, manufacturers, materials, onClose, onSaved }) {
  const manufacturerNames = Array.from(new Set([
    ...manufacturers.map(item => item.name),
    filament.manufacturer,
  ].filter(Boolean))).sort((a, b) => a.localeCompare(b));
  const materialNames = Array.from(new Set([
    ...materials,
    filament.material,
  ].filter(Boolean))).sort((a, b) => a.localeCompare(b));

  const [customManufacturer, setCustomManufacturer] = useState(
    Boolean(filament.manufacturer) && !manufacturerNames.includes(filament.manufacturer)
  );
  const [customMaterial, setCustomMaterial] = useState(
    Boolean(filament.material) && !materialNames.includes(filament.material)
  );
  const [form, setForm] = useState({
    manufacturer_name: filament.manufacturer || "",
    name: filament.name || "",
    material: filament.material || "",
    color_name: filament.color_name || "",
    color_hex: filament.color_hex || "#777777",
    color_hexes: filament.color_hexes || [],
    transparency: filament.transparency || "opaque",
    multi_color_direction: filament.multi_color_direction || "",
    finish: filament.finish || "",
    pattern: filament.pattern || "",
    glow: Boolean(filament.glow),
    diameter_mm: filament.diameter_mm ?? "1.75",
    density_g_cm3: filament.density_g_cm3 ?? "",
    nominal_weight_g: filament.nominal_weight_g ?? "",
    empty_spool_weight_g: filament.empty_spool_weight_g ?? "",
    nozzle_temp_min_c: filament.nozzle_temp_min_c ?? "",
    nozzle_temp_max_c: filament.nozzle_temp_max_c ?? "",
    bed_temp_min_c: filament.bed_temp_min_c ?? "",
    bed_temp_max_c: filament.bed_temp_max_c ?? "",
    drying_temp_c: filament.drying_temp_c ?? "",
    drying_time_hours: filament.drying_time_hours ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/filaments/" + filament.id + "/", {
        method: "PATCH",
        body: form,
      });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal
    title={"Edit filament · " + (filament.display_name || filament.name)}
    subtitle="Changes apply to this shared filament product and therefore to every spool that uses it."
    onClose={onClose}
    wide
  >
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}

      <label>Manufacturer<select value={customManufacturer ? "__custom__" : form.manufacturer_name} onChange={e => {
        if (e.target.value === "__custom__") {
          setCustomManufacturer(true);
          set("manufacturer_name", "");
        } else {
          setCustomManufacturer(false);
          set("manufacturer_name", e.target.value);
        }
      }}>
        <option value="">Choose manufacturer…</option>
        {manufacturerNames.map(name => <option key={name} value={name}>{name}</option>)}
        <option value="__custom__">Other / custom manufacturer</option>
      </select></label>
      {customManufacturer && <label>Custom manufacturer<input required value={form.manufacturer_name} onChange={e => set("manufacturer_name", e.target.value)} /></label>}

      <label>Material<select value={customMaterial ? "__custom__" : form.material} onChange={e => {
        if (e.target.value === "__custom__") {
          setCustomMaterial(true);
          set("material", "");
        } else {
          setCustomMaterial(false);
          set("material", e.target.value);
        }
      }}>
        <option value="">Choose material…</option>
        {materialNames.map(name => <option key={name} value={name}>{name}</option>)}
        <option value="__custom__">Other / custom material</option>
      </select></label>
      {customMaterial && <label>Custom material<input required value={form.material} onChange={e => set("material", e.target.value)} /></label>}

      <label>Product name<input required value={form.name} onChange={e => set("name", e.target.value)} /></label>
      <label>Colour name<input value={form.color_name} onChange={e => set("color_name", e.target.value)} /></label>
      <label>Appearance<select value={form.transparency} onChange={e => set("transparency", e.target.value)}><option value="opaque">Opaque</option><option value="translucent">Translucent</option><option value="transparent">Transparent</option></select></label>
      <label>Colour<div className="filamentCustomColour"><input type="color" value={form.color_hex || "#777777"} onChange={e => setForm(current => ({ ...current, color_hex: e.target.value, color_hexes: [] }))} /><input value={form.color_hex} onChange={e => setForm(current => ({ ...current, color_hex: e.target.value, color_hexes: [] }))} maxLength="9" placeholder="#RRGGBB" /></div></label>
      <label>Finish<input value={form.finish} onChange={e => set("finish", e.target.value)} placeholder="Matte, silk, textured…" /></label>
      <label>Pattern<input value={form.pattern} onChange={e => set("pattern", e.target.value)} placeholder="Optional pattern" /></label>
      <label>Multi-colour direction<input value={form.multi_color_direction} onChange={e => set("multi_color_direction", e.target.value)} placeholder="Optional" /></label>
      <label className="settingsToggle"><div><strong>Glow filament</strong><small>Mark this product as glow-in-the-dark.</small></div><input type="checkbox" checked={form.glow} onChange={e => set("glow", e.target.checked)} /></label>
      <label>Diameter (mm)<input type="number" min="0.1" step="0.01" value={form.diameter_mm} onChange={e => set("diameter_mm", e.target.value)} /></label>
      <label>Density (g/cm³)<input type="number" min="0" step="0.001" value={form.density_g_cm3} onChange={e => set("density_g_cm3", e.target.value)} /></label>
      <label>Nominal weight (g)<input type="number" min="0" step="0.01" value={form.nominal_weight_g} onChange={e => set("nominal_weight_g", e.target.value)} /></label>
      <label>Empty spool weight (g)<input type="number" min="0" step="0.01" value={form.empty_spool_weight_g} onChange={e => set("empty_spool_weight_g", e.target.value)} /></label>
      <label>Nozzle temp min (°C)<input type="number" value={form.nozzle_temp_min_c} onChange={e => set("nozzle_temp_min_c", e.target.value)} /></label>
      <label>Nozzle temp max (°C)<input type="number" value={form.nozzle_temp_max_c} onChange={e => set("nozzle_temp_max_c", e.target.value)} /></label>
      <label>Bed temp min (°C)<input type="number" value={form.bed_temp_min_c} onChange={e => set("bed_temp_min_c", e.target.value)} /></label>
      <label>Bed temp max (°C)<input type="number" value={form.bed_temp_max_c} onChange={e => set("bed_temp_max_c", e.target.value)} /></label>
      <label>Drying temp (°C)<input type="number" value={form.drying_temp_c} onChange={e => set("drying_temp_c", e.target.value)} /></label>
      <label>Drying time (hours)<input type="number" min="0" step="0.1" value={form.drying_time_hours} onChange={e => set("drying_time_hours", e.target.value)} /></label>

      <div className="settingsCallout full">
        <strong>Source provenance is preserved</strong>
        <p>{filament.source || "Manual"}{filament.source_type && filament.source_type !== "manual" ? " · " + filament.source_type : ""}. Editing does not discard the original catalogue/source attribution.</p>
      </div>
      <div className="formActions full">
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !form.manufacturer_name || !form.material || !form.name}>{busy ? "Saving…" : "Save filament changes"}</button>
      </div>
    </form>
  </Modal>;
}


const FILAMENT_COLOUR_PALETTE = [
  ["Black", "#111111"], ["White", "#f4f4f4"], ["Grey", "#808080"], ["Silver", "#b9bec4"],
  ["Red", "#d32f2f"], ["Orange", "#ef6c00"], ["Yellow", "#f9a825"], ["Lime", "#7cb342"],
  ["Green", "#2e7d32"], ["Teal", "#00897b"], ["Cyan", "#00acc1"], ["Blue", "#1565c0"],
  ["Navy", "#283593"], ["Purple", "#7b1fa2"], ["Pink", "#d81b60"], ["Brown", "#6d4c41"],
  ["Beige", "#d7c7a3"], ["Gold", "#c9a227"], ["Copper", "#b87333"], ["Natural", "#e8dfc8"],
];

function FilamentModal({ manufacturers, materials, onClose, onSaved }) {
  const [form, setForm] = useState({
    manufacturer_name: manufacturers[0]?.name || "",
    name: "",
    material: materials[0] || "PLA",
    color_name: "",
    color_hex: "#777777",
    color_hexes: [],
    transparency: "opaque",
    diameter_mm: "1.75",
    nominal_weight_g: "1000",
    catalogue_external_id: "",
  });
  const [meta, setMeta] = useState({ manufacturers: [], materials: [] });
  const [products, setProducts] = useState([]);
  const [customManufacturer, setCustomManufacturer] = useState(false);
  const [customMaterial, setCustomMaterial] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [error, setError] = useState("");

  const set = (key, value, clearCatalogue = false) => setForm(value0 => ({
    ...value0,
    [key]: value,
    ...(clearCatalogue ? { catalogue_external_id: "" } : {}),
  }));

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/printing/catalogue/filaments/meta/")
      .then(result => {
        if (!cancelled) setMeta({
          manufacturers: result.manufacturers || [],
          materials: result.materials || [],
        });
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const manufacturerOptions = Array.from(new Set([
    ...manufacturers.map(item => item.name),
    ...(meta.manufacturers || []),
  ])).sort((a, b) => a.localeCompare(b));
  const materialOptions = Array.from(new Set([
    ...materials,
    ...(meta.materials || []),
  ])).sort((a, b) => a.localeCompare(b));

  useEffect(() => {
    if (!form.manufacturer_name || !form.material || customManufacturer || customMaterial) {
      setProducts([]);
      return;
    }
    let cancelled = false;
    setLoadingProducts(true);
    const path = "/api/printing/catalogue/filaments/?manufacturer=" +
      encodeURIComponent(form.manufacturer_name) + "&material=" +
      encodeURIComponent(form.material) + "&limit=100";
    apiFetch(path)
      .then(result => {
        if (cancelled) return;
        const unique = [];
        const seen = new Set();
        for (const row of result.rows || []) {
          if (seen.has(row.name)) continue;
          seen.add(row.name);
          unique.push(row);
        }
        setProducts(unique);
      })
      .catch(() => { if (!cancelled) setProducts([]); })
      .finally(() => { if (!cancelled) setLoadingProducts(false); });
    return () => { cancelled = true; };
  }, [form.manufacturer_name, form.material, customManufacturer, customMaterial]);

  function chooseProduct(externalId) {
    const row = products.find(item => item.external_id === externalId);
    if (!row) {
      set("catalogue_external_id", "");
      return;
    }
    setForm(current => ({
      ...current,
      catalogue_external_id: row.external_id,
      name: row.name,
      material: row.material,
      color_name: row.color_name || current.color_name,
      color_hex: row.color_hex || current.color_hex,
      color_hexes: row.color_hexes || [],
      transparency: row.transparency || "opaque",
      diameter_mm: row.diameter_mm || current.diameter_mm,
      nominal_weight_g: row.nominal_weight_g || current.nominal_weight_g,
    }));
  }

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (form.catalogue_external_id) {
        await apiFetch("/api/printing/catalogue/filaments/import/", {
          method: "POST",
          body: { external_id: form.catalogue_external_id },
        });
      } else {
        await apiFetch("/api/printing/filaments/", {
          method: "POST",
          body: {
            ...form,
            catalogue_external_id: undefined,
          },
        });
      }
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add filament product" subtitle="Choose a known manufacturer/product from the open catalogue or create a fully custom filament." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Manufacturer<select value={customManufacturer ? "__custom__" : form.manufacturer_name} onChange={e => {
        if (e.target.value === "__custom__") {
          setCustomManufacturer(true);
          set("manufacturer_name", "", true);
        } else {
          setCustomManufacturer(false);
          set("manufacturer_name", e.target.value, true);
        }
      }}>
        <option value="">Choose manufacturer…</option>
        {manufacturerOptions.map(name => <option key={name} value={name}>{name}</option>)}
        <option value="__custom__">Other / custom manufacturer</option>
      </select></label>
      {customManufacturer && <label>Custom manufacturer<input required value={form.manufacturer_name} onChange={e => set("manufacturer_name", e.target.value, true)} /></label>}

      <label>Material<select value={customMaterial ? "__custom__" : form.material} onChange={e => {
        if (e.target.value === "__custom__") {
          setCustomMaterial(true);
          set("material", "", true);
        } else {
          setCustomMaterial(false);
          set("material", e.target.value, true);
        }
      }}>
        <option value="">Choose material…</option>
        {materialOptions.map(name => <option key={name} value={name}>{name}</option>)}
        <option value="__custom__">Other / custom material</option>
      </select></label>
      {customMaterial && <label>Custom material<input required value={form.material} onChange={e => set("material", e.target.value, true)} /></label>}

      <label className="full">Known product offering<select value={form.catalogue_external_id} onChange={e => chooseProduct(e.target.value)} disabled={!products.length}>
        <option value="">{loadingProducts ? "Loading manufacturer products…" : products.length ? "Custom / choose product…" : "No catalogue products found — enter one manually"}</option>
        {products.map(item => <option key={item.external_id} value={item.external_id}>{item.name}</option>)}
      </select></label>

      <label>Product name<input required value={form.name} onChange={e => set("name", e.target.value, true)} placeholder="PLA Basic" /></label>
      <label>Colour name<input value={form.color_name} onChange={e => set("color_name", e.target.value, true)} placeholder="Manufacturer colour name" /></label>
      <label>Appearance<select value={form.transparency} onChange={e => set("transparency", e.target.value, true)}><option value="opaque">Opaque</option><option value="translucent">Translucent</option><option value="transparent">Transparent</option></select></label>
      <div className="full filamentColourField">
        <span>Colour palette</span>
        <div className="filamentPalette" role="group" aria-label="Filament colour palette">
          {FILAMENT_COLOUR_PALETTE.map(([name, hex]) => <button
            key={hex}
            type="button"
            className={form.color_hex.toLowerCase() === hex ? "selected" : ""}
            title={name}
            aria-label={name}
            onClick={() => setForm(value => ({ ...value, color_hex: hex, color_hexes: [], color_name: value.color_name || name, catalogue_external_id: "" }))}
          ><span style={{ background: hex }} /></button>)}
        </div>
      </div>
      <label>Custom colour<div className="filamentCustomColour"><input type="color" value={form.color_hex || "#777777"} onChange={e => setForm(value => ({ ...value, color_hex: e.target.value, color_hexes: [], catalogue_external_id: "" }))} /><input value={form.color_hex} onChange={e => setForm(value => ({ ...value, color_hex: e.target.value, color_hexes: [], catalogue_external_id: "" }))} maxLength="9" placeholder="#RRGGBB" /></div></label>
      <label>Preview<div className={`filamentPreview filamentPreview-${form.transparency}`}><span style={filamentSwatchStyle(form)} /><strong>{form.color_name || "Selected colour"}</strong><small>{form.transparency}{form.catalogue_external_id ? " · catalogue product" : ""}</small></div></label>
      <label>Diameter (mm)<input type="number" step="0.01" min="0.1" value={form.diameter_mm} onChange={e => set("diameter_mm", e.target.value, true)} /></label>
      <label>Nominal weight (g)<input type="number" step="1" min="0" value={form.nominal_weight_g} onChange={e => set("nominal_weight_g", e.target.value, true)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !form.manufacturer_name || !form.material}>{busy ? "Saving…" : form.catalogue_external_id ? "Import product" : "Add filament"}</button></div>
    </form>
  </Modal>;
}


function filamentSwatchStyle(item) {
  const colours = (item?.color_hexes || []).map(value => String(value || "").slice(0, 7)).filter(Boolean);
  if (colours.length > 1) {
    const width = 100 / colours.length;
    const stops = colours.flatMap((colour, index) => [
      `${colour} ${(index * width).toFixed(1)}%`,
      `${colour} ${((index + 1) * width).toFixed(1)}%`,
    ]);
    return { background: `linear-gradient(135deg, ${stops.join(", ")})` };
  }
  return item?.color_hex ? { background: item.color_hex } : undefined;
}

function FilamentCatalogueModal({ onClose, onImported }) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(null);
  const [source, setSource] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");

  async function search(event) {
    event?.preventDefault();
    setBusy(true); setError(""); setSelected(null);
    try {
      const result = await apiFetch("/api/printing/catalogue/filaments/?q=" + encodeURIComponent(query) + "&limit=50");
      setRows(result.rows || []);
      setTotal(result.total ?? 0);
      setSource(result.source || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function importSelected() {
    if (!selected) return;
    setImporting(true); setError("");
    try {
      await apiFetch("/api/printing/catalogue/filaments/import/", {
        method: "POST",
        body: { external_id: selected.external_id },
      });
      await onImported();
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  }

  return <Modal title="Open filament catalogue" subtitle="Search SpoolmanDB, preview the source record, then import it as a normal native MakerVault filament product." onClose={onClose} wide>
    <div className="filamentCatalogueModal">
      {error && <div className="formError">{error}</div>}
      <form className="filamentCatalogueSearch" onSubmit={search}>
        <input autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="Search brand, product, material, colour…" />
        <button className="primary" disabled={busy}>{busy ? "Searching…" : "Search catalogue"}</button>
      </form>
      <div className="filamentCatalogueMeta">
        <span>{total == null ? "Search the public catalogue to begin." : `${total.toLocaleString()} matching variants · showing up to 50`}</span>
        {source && <span>{source.name} · {source.license}</span>}
      </div>

      <div className={`filamentCatalogueLayout${selected ? " hasPreview" : ""}`}>
        <div className="filamentCatalogueResults">
          {rows.map(item => <button type="button" className={`filamentCatalogueRow${selected?.external_id === item.external_id ? " selected" : ""}`} key={item.external_id} onClick={() => setSelected(item)}>
            <span className={`printingSwatch catalogueSwatch filamentPreview-${item.transparency}`} style={filamentSwatchStyle(item)} />
            <span><strong>{item.manufacturer} · {item.name}</strong><small>{item.material} · {item.diameter_mm || "?"} mm · {grams(item.nominal_weight_g)}</small></span>
            <span className="printingBadges">{item.transparency !== "opaque" && <Badge>{item.transparency}</Badge>}{item.color_hexes?.length > 1 && <Badge tone="accent">{item.color_hexes.length} colours</Badge>}{item.glow && <Badge>Glow</Badge>}</span>
          </button>)}
          {!busy && total === 0 && <div className="printingEmptyInline">No matching filament variants.</div>}
          {!busy && total == null && <div className="printingEmptyInline">Try a manufacturer, material such as PLA/PETG/ASA, product name or colour.</div>}
        </div>

        {selected && <div className="filamentCataloguePreview">
          <div className={`filamentCatalogueHero filamentPreview-${selected.transparency}`}>
            <span style={filamentSwatchStyle(selected)} />
          </div>
          <span className="settingsEyebrow">SpoolmanDB preview</span>
          <h3>{selected.manufacturer} · {selected.name}</h3>
          <div className="badgeRow"><Badge tone="accent">{selected.material}</Badge><Badge>{selected.transparency}</Badge>{selected.finish && <Badge>{selected.finish}</Badge>}{selected.pattern && <Badge>{selected.pattern}</Badge>}{selected.glow && <Badge>Glow</Badge>}</div>
          <dl className="detailSpecs">
            <div><dt>Diameter</dt><dd>{selected.diameter_mm || "—"} mm</dd></div>
            <div><dt>Net weight</dt><dd>{grams(selected.nominal_weight_g)}</dd></div>
            <div><dt>Spool weight</dt><dd>{grams(selected.empty_spool_weight_g)}</dd></div>
            <div><dt>Density</dt><dd>{selected.density_g_cm3 ? `${selected.density_g_cm3} g/cm³` : "—"}</dd></div>
            <div><dt>Nozzle</dt><dd>{selected.nozzle_temp_min_c == null ? "—" : `${selected.nozzle_temp_min_c}–${selected.nozzle_temp_max_c} °C`}</dd></div>
            <div><dt>Bed</dt><dd>{selected.bed_temp_min_c == null ? "—" : `${selected.bed_temp_min_c}–${selected.bed_temp_max_c} °C`}</dd></div>
            <div><dt>Colour mode</dt><dd>{selected.color_hexes?.length > 1 ? `${selected.color_hexes.length}-colour ${selected.multi_color_direction || "multi-colour"}` : selected.color_hex || "—"}</dd></div>
            <div><dt>Source ID</dt><dd>{selected.external_id}</dd></div>
          </dl>
          <button className="primary" disabled={importing} onClick={importSelected}>{importing ? "Importing…" : "Import into MakerVault"}</button>
          <p className="muted">The imported record remains editable and usable without SpoolmanDB. Source provenance is retained separately.</p>
        </div>}
      </div>
    </div>
  </Modal>;
}

function normaliseDetectedText(value) {
  return String(value || "").trim().toLowerCase();
}

function findDetectedFilamentMatch(filaments, slot) {
  const vendor = normaliseDetectedText(slot?.vendor);
  const product = normaliseDetectedText(slot?.product_name);
  const material = normaliseDetectedText(slot?.material);
  const colour = normaliseDetectedText(slot?.color_hex);
  let best = null;
  let bestScore = 0;

  for (const filament of filaments || []) {
    let score = 0;
    const candidateVendor = normaliseDetectedText(filament.manufacturer);
    const candidateName = normaliseDetectedText(filament.name);
    const candidateMaterial = normaliseDetectedText(filament.material);
    const candidateColour = normaliseDetectedText(filament.color_hex);

    if (colour && candidateColour !== colour) continue;
    if (material && candidateMaterial === material) score += 6;
    if (vendor && candidateVendor === vendor) score += 5;
    if (product && candidateName) {
      if (candidateName === product) score += 6;
      else if (candidateName.includes(product) || product.includes(candidateName)) score += 3;
    }
    if (colour && candidateColour === colour) score += 3;

    if (score > bestScore) {
      best = filament;
      bestScore = score;
    }
  }
  return bestScore >= 6 ? best : null;
}

function DiscoveredSpoolModal({ printer, slot, filaments, spools, currency, canCreateFilament, canLinkExisting, onClose, onSaved }) {
  const initialMatch = findDetectedFilamentMatch(filaments, slot);
  const [physicalMode, setPhysicalMode] = useState("create");
  const [existingSpoolId, setExistingSpoolId] = useState("");
  const [availableFilaments, setAvailableFilaments] = useState(filaments || []);
  const [mode, setMode] = useState(initialMatch ? "existing" : "new");
  const [form, setForm] = useState({
    filament_id: initialMatch?.id || "",
    rfid_uid: slot.rfid_uid || "",
    initial_weight_g: initialMatch?.nominal_weight_g || "",
    remaining_weight_g: "",
    purchase_cost: "",
    currency,
    status: "open",
    opened_on: "",
    notes: "",
  });
  const [newFilament, setNewFilament] = useState({
    manufacturer_name: slot.vendor || "",
    name: slot.product_name || slot.material || "",
    material: slot.material || "",
    color_name: "",
    color_hex: slot.color_hex || "#777777",
    transparency: "opaque",
    diameter_mm: "1.75",
    nominal_weight_g: "",
  });
  const [busy, setBusy] = useState(false);
  const [loadingFilaments, setLoadingFilaments] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));
  const setNew = (key, value) => setNewFilament(current => ({ ...current, [key]: value }));

  useEffect(() => {
    let cancelled = false;
    setLoadingFilaments(true);
    apiFetch("/api/printing/filaments/")
      .then(result => {
        if (cancelled) return;
        const rows = result.rows || [];
        setAvailableFilaments(rows);
        const match = findDetectedFilamentMatch(rows, slot);
        if (match) {
          setMode(current => current === "new" && !canCreateFilament ? "existing" : current);
          setForm(current => ({
            ...current,
            filament_id: current.filament_id || match.id,
            initial_weight_g: current.initial_weight_g || match.nominal_weight_g || "",
          }));
        } else if (!canCreateFilament) {
          setMode("existing");
        }
      })
      .catch(err => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoadingFilaments(false); });
    return () => { cancelled = true; };
  }, []);

  function existingFilamentChanged(value) {
    const selected = availableFilaments.find(item => item.id === value);
    setForm(current => ({
      ...current,
      filament_id: value,
      initial_weight_g: current.initial_weight_g || selected?.nominal_weight_g || "",
    }));
  }

  const candidateSpools = [...(spools || [])]
    .filter(spool => !spool.loaded_slots?.length)
    .sort((a, b) => {
      const score = spool => {
        let value = 0;
        if (normaliseDetectedText(spool.material) === normaliseDetectedText(slot.material)) value += 4;
        if (slot.color_hex && normaliseDetectedText(spool.color_hex) === normaliseDetectedText(slot.color_hex)) value += 5;
        if (slot.vendor && normaliseDetectedText(spool.manufacturer) === normaliseDetectedText(slot.vendor)) value += 3;
        if (slot.product_name && normaliseDetectedText(spool.filament).includes(normaliseDetectedText(slot.product_name))) value += 2;
        return value;
      };
      return score(b) - score(a);
    });

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const body = physicalMode === "link"
        ? { existing_spool_id: existingSpoolId }
        : {
            ...form,
            filament_id: mode === "existing" ? form.filament_id : "",
            new_filament: mode === "new" ? newFilament : undefined,
          };
      await apiFetch("/api/printing/slots/" + slot.id + "/add-to-inventory/", {
        method: "POST",
        body,
      });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const detectedPercent = slot.remaining_percent != null ? Math.round(slot.remaining_percent) : null;
  const cfsWithoutPhysicalUid = slot.system === "creality_cfs" && !slot.physical_tag_uid_available;

  return <Modal
    title="Identify detected physical spool"
    subtitle={"MakerVault discovered this material through " + slot.system_label + ". Confirm whether it is an existing physical spool or a new inventory item."}
    onClose={onClose}
    wide
  >
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}

      <div className="settingsCallout full detectedSpoolSummary">
        <strong>Detected in {printer.name} · {slot.system_label} unit {slot.unit_index + 1}, slot {slot.slot_index + 1}</strong>
        <p>{[slot.vendor, slot.product_name, slot.material].filter(Boolean).join(" · ") || "Unknown filament"}{detectedPercent != null ? " · " + detectedPercent + "% remaining" : ""}</p>
        <div className="badgeRow">
          {slot.vendor && <Badge>{slot.vendor}</Badge>}
          {slot.product_name && <Badge tone="accent">{slot.product_name}</Badge>}
          {slot.material && <Badge>{slot.material}</Badge>}
          {slot.rfid_detected && <Badge tone="good">RFID material detected</Badge>}
          {slot.rfid_uid && <Badge>Tag {slot.rfid_uid}</Badge>}
        </div>
      </div>

      {cfsWithoutPhysicalUid && <div className="settingsCallout full">
        <strong>CFS cannot uniquely identify this physical reel</strong>
        <p>Creality's local CFS feed reports an RFID material/profile code{slot.material_code ? " (" + slot.material_code + ")" : ""}, but not the unique serial of the RFID chip. MakerVault therefore will not auto-link this slot to a physical spool. Confirm the reel below.</p>
      </div>}

      <label className="full">Physical spool action<select value={physicalMode} onChange={e => setPhysicalMode(e.target.value)}>
        <option value="create">Create a new physical spool</option>
        {canLinkExisting && <option value="link">Link an existing MakerVault spool</option>}
      </select></label>

      {physicalMode === "link" && <>
        <label className="full">Existing physical spool<select required value={existingSpoolId} onChange={e => setExistingSpoolId(e.target.value)}>
          <option value="">Choose an unloaded spool…</option>
          {candidateSpools.map(spool => <option key={spool.id} value={spool.id}>
            {spool.spool_id} · {spool.filament}{spool.color_name ? " · " + spool.color_name : ""}{spool.rfid_uid ? " · RFID " + spool.rfid_uid : ""}
          </option>)}
        </select><small>Matching material and colour are shown first, but the final choice is yours.</small></label>
        {!candidateSpools.length && <div className="formError full">There are no currently unloaded MakerVault spools available to link.</div>}
      </>}

      {physicalMode === "create" && <>
        <label>Filament record<select value={mode} onChange={e => setMode(e.target.value)}>
          <option value="existing">Use existing MakerVault filament</option>
          {canCreateFilament && <option value="new">Create a new filament product from detected data</option>}
        </select></label>

        {mode === "existing" && <label>Existing filament<select required value={form.filament_id} onChange={e => existingFilamentChanged(e.target.value)} disabled={loadingFilaments}>
          <option value="">{loadingFilaments ? "Loading filaments…" : "Choose filament…"}</option>
          {availableFilaments.map(item => <option key={item.id} value={item.id}>{item.display_name} · {item.material}{item.color_name ? " · " + item.color_name : ""}</option>)}
        </select></label>}

        {mode === "new" && <>
          <label>Manufacturer<input value={newFilament.manufacturer_name} onChange={e => setNew("manufacturer_name", e.target.value)} placeholder="eSUN" /></label>
          <label>Product name<input required value={newFilament.name} onChange={e => setNew("name", e.target.value)} placeholder="PLA+ HS" /></label>
          <label>Material<input required value={newFilament.material} onChange={e => setNew("material", e.target.value)} placeholder="PLA" /></label>
          <label>Colour name<input value={newFilament.color_name} onChange={e => setNew("color_name", e.target.value)} placeholder="Manufacturer colour name" /></label>
          <label>Detected colour<div className="colorInputRow"><input type="color" value={(newFilament.color_hex || "#777777").slice(0, 7)} onChange={e => setNew("color_hex", e.target.value)} /><input value={newFilament.color_hex} onChange={e => setNew("color_hex", e.target.value)} placeholder="#7b1fa2" /></div></label>
          <label>Filament diameter (mm)<input type="number" min="0.5" step="0.01" value={newFilament.diameter_mm} onChange={e => setNew("diameter_mm", e.target.value)} /></label>
          <label>Nominal spool weight (g)<input type="number" min="0" step="0.1" value={newFilament.nominal_weight_g} onChange={e => { setNew("nominal_weight_g", e.target.value); if (!form.initial_weight_g) set("initial_weight_g", e.target.value); }} placeholder="1000" /></label>
        </>}

        <label>Physical RFID tag ID<input value={form.rfid_uid} onChange={e => set("rfid_uid", e.target.value.toUpperCase())} placeholder="Optional unique chip/tag serial" /><small>{slot.rfid_uid ? "A unique tag ID was supplied by this integration." : "Optional. Do not enter the CFS material code here; this field is for a genuinely unique physical tag ID."}</small></label>
        <label>Initial filament weight (g)<input type="number" min="0" step="0.1" value={form.initial_weight_g} onChange={e => set("initial_weight_g", e.target.value)} placeholder="1000" /></label>
        <label>Remaining weight (g)<input type="number" min="0" step="0.1" value={form.remaining_weight_g} onChange={e => set("remaining_weight_g", e.target.value)} placeholder={detectedPercent != null ? "Auto from " + detectedPercent + "% if left blank" : ""} /></label>
        <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}><option value="open">Open</option><option value="sealed">Sealed</option><option value="drying">Drying</option><option value="empty">Empty</option><option value="retired">Retired</option></select></label>
        <label>Purchase cost<input type="number" min="0" step="0.01" value={form.purchase_cost} onChange={e => set("purchase_cost", e.target.value)} /></label>
        <label>Opened on<input type="date" value={form.opened_on} onChange={e => set("opened_on", e.target.value)} /></label>
        <div className="settingsCallout"><strong>Placement</strong><p>This spool is currently loaded in {printer.name}, so MakerVault will assign it to that printer automatically.</p></div>
        <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      </>}

      <div className="formActions full">
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={
          busy ||
          (physicalMode === "link" && !existingSpoolId) ||
          (physicalMode === "create" && mode === "existing" && !form.filament_id) ||
          (physicalMode === "create" && mode === "new" && (!newFilament.name || !newFilament.material))
        }>
          {busy ? "Saving…" : physicalMode === "link" ? "Link physical spool" : "Add to inventory & link slot"}
        </button>
      </div>
    </form>
  </Modal>;
}


function SpoolModal({ filaments, locations, printers, currency, onClose, onSaved }) {
  const [availableFilaments, setAvailableFilaments] = useState(filaments || []);
  const [placementType, setPlacementType] = useState("location");
  const [form, setForm] = useState({
    filament_id: filaments[0]?.id || "",
    rfid_uid: "",
    initial_weight_g: "",
    remaining_weight_g: "",
    purchase_cost: "",
    currency,
    storage_location_id: locations[0]?.id || "",
    assigned_printer_id: "",
    status: "sealed",
    opened_on: "",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [loadingFilaments, setLoadingFilaments] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));

  useEffect(() => {
    let cancelled = false;
    setLoadingFilaments(true);
    apiFetch("/api/printing/filaments/")
      .then(result => {
        if (cancelled) return;
        const rows = result.rows || [];
        setAvailableFilaments(rows);
        if (!form.filament_id && rows.length) {
          setForm(current => ({ ...current, filament_id: rows[0].id }));
        }
      })
      .catch(err => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoadingFilaments(false); });
    return () => { cancelled = true; };
  }, []);

  function placementChanged(value) {
    setPlacementType(value);
    setForm(current => ({
      ...current,
      storage_location_id: value === "location" ? (current.storage_location_id || locations[0]?.id || "") : "",
      assigned_printer_id: value === "printer" ? (current.assigned_printer_id || printers.find(item => item.is_active)?.id || "") : "",
    }));
  }

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/spools/", {
        method: "POST",
        body: {
          ...form,
          storage_location_id: placementType === "location" ? form.storage_location_id : "",
          assigned_printer_id: placementType === "printer" ? form.assigned_printer_id : "",
        },
      });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add physical spool" subtitle="Choose a native MakerVault filament, then store the spool at a custom location or assign it to one of your printers." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <div className="settingsCallout"><strong>Spool ID</strong><p>MakerVault assigns the next available SPL-#### ID automatically when this spool is created.</p></div>
      <label>Filament<select required value={form.filament_id} onChange={e => set("filament_id", e.target.value)} disabled={loadingFilaments}>
        <option value="">{loadingFilaments ? "Loading filaments…" : "Choose filament…"}</option>
        {availableFilaments.map(x => <option key={x.id} value={x.id}>{x.display_name} · {x.material}</option>)}
      </select></label>
      {!loadingFilaments && !availableFilaments.length && <div className="formError full">No filament products exist yet. Add or import a filament first, then reopen this dialog.</div>}

      <label>Placement<select value={placementType} onChange={e => placementChanged(e.target.value)}>
        <option value="location">Storage location</option>
        <option value="printer">Assigned to printer</option>
        <option value="none">Unassigned</option>
      </select></label>
      {placementType === "location" && <label>Location<select value={form.storage_location_id} onChange={e => set("storage_location_id", e.target.value)}>
        <option value="">Choose location…</option>
        {locations.map(x => <option key={x.id} value={x.id}>{x.name} · {x.kind_label}</option>)}
      </select></label>}
      {placementType === "printer" && <label>Printer<select value={form.assigned_printer_id} onChange={e => set("assigned_printer_id", e.target.value)}>
        <option value="">Choose printer…</option>
        {printers.filter(x => x.is_active).map(x => <option key={x.id} value={x.id}>{x.name} · {x.model}</option>)}
      </select></label>}

      <label>RFID tag ID<input value={form.rfid_uid} onChange={e => set("rfid_uid", e.target.value.toUpperCase())} placeholder="Optional physical tag ID" /><small>Use this to distinguish otherwise identical physical spools.</small></label>
      <label>Initial weight (g)<input type="number" min="0" step="0.1" value={form.initial_weight_g} onChange={e => set("initial_weight_g", e.target.value)} /></label>
      <label>Remaining weight (g)<input type="number" min="0" step="0.1" value={form.remaining_weight_g} onChange={e => set("remaining_weight_g", e.target.value)} /></label>
      <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}><option value="sealed">Sealed</option><option value="open">Open</option><option value="drying">Drying</option><option value="empty">Empty</option><option value="retired">Retired</option></select></label>
      <label>Purchase cost<input type="number" min="0" step="0.01" value={form.purchase_cost} onChange={e => set("purchase_cost", e.target.value)} /></label>
      <label>Opened on<input type="date" value={form.opened_on} onChange={e => set("opened_on", e.target.value)} /></label>
      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !availableFilaments.length || !form.filament_id}>{busy ? "Saving…" : "Add spool"}</button></div>
    </form>
  </Modal>;
}


function ModelModal({ projects, canUpload, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: "",
    project_id: "",
    description: "",
    source_url: "",
    license: "",
    tags: "",
    revision_version: "1.0",
    revision_notes: "",
  });
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));

  function fileChanged(event) {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    if (selected && !form.name) {
      set("name", selected.name.replace(/\.(stl|3mf)$/i, ""));
    }
  }

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (file) {
        const body = new FormData();
        for (const [key, value] of Object.entries(form)) body.append(key, value ?? "");
        body.append("file", file);
        await apiFetch("/api/printing/models/", { method: "POST", body });
      } else {
        await apiFetch("/api/printing/models/", { method: "POST", body: form });
      }
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add 3D model" subtitle="Upload an STL/3MF directly from this device, or create an empty model record and attach existing MakerVault files later." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      {canUpload && <label className="full modelFilePicker">
        <span>STL / 3MF file</span>
        <input type="file" accept=".stl,.3mf,model/stl,application/vnd.ms-package.3dmanufacturing-3dmodel+xml" onChange={fileChanged} />
        <small>{file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB` : "Browse this computer, phone or tablet. The file is stored in MakerVault Files and attached to revision 1.0 by default."}</small>
      </label>}
      <label>Name<input required={!file} value={form.name} onChange={e => set("name", e.target.value)} placeholder={file ? "Defaults to file name" : "Model name"} /></label>
      <label>Project<select value={form.project_id} onChange={e => set("project_id", e.target.value)}><option value="">Standalone model</option>{projects.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      {file && <label>Initial revision<input required value={form.revision_version} onChange={e => set("revision_version", e.target.value)} placeholder="1.0" /></label>}
      {file && <label>Revision notes<input value={form.revision_notes} onChange={e => set("revision_notes", e.target.value)} /></label>}
      <label className="full">Description<textarea rows="3" value={form.description} onChange={e => set("description", e.target.value)} /></label>
      <label>Source URL<input type="url" value={form.source_url} onChange={e => set("source_url", e.target.value)} /></label>
      <label>Licence<input value={form.license} onChange={e => set("license", e.target.value)} placeholder="CC BY 4.0, personal use…" /></label>
      <label className="full">Tags<input value={form.tags} onChange={e => set("tags", e.target.value)} placeholder="Comma-separated" /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? file ? "Uploading…" : "Saving…" : file ? "Upload & add model" : "Add model"}</button></div>
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


function PrintJobModal({ printers, spools, models, projects, currency, onClose, onSaved }) {
  const revisionOptions = models.flatMap(model =>
    model.revisions.map(revision => ({
      id: revision.id,
      label: model.name + " · " + revision.version,
      project_id: model.project_id || "",
    }))
  );
  const [form, setForm] = useState({
    printer_id: printers[0]?.id || "",
    model_revision_id: "",
    project_id: "",
    status: "success",
    quantity: 1,
    estimated_minutes: "",
    actual_minutes: "",
    layer_height_mm: "",
    nozzle_mm: "",
    slicer: "",
    notes: "",
  });
  const [usages, setUsages] = useState([
    { spool_id: spools[0]?.id || "", used_g: "", waste_g: "", material_cost: "", currency },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));
  const setUsage = (index, key, value) => setUsages(rows => rows.map((row, i) => i === index ? { ...row, [key]: value } : row));

  function addUsage() {
    setUsages(rows => [...rows, { spool_id: "", used_g: "", waste_g: "", material_cost: "", currency }]);
  }

  function removeUsage(index) {
    setUsages(rows => rows.filter((_, i) => i !== index));
  }

  function revisionChanged(value) {
    const revision = revisionOptions.find(option => option.id === value);
    setForm(current => ({
      ...current,
      model_revision_id: value,
      project_id: revision?.project_id || current.project_id,
    }));
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const material_usages = usages
        .filter(row => row.spool_id || row.used_g || row.waste_g || row.material_cost)
        .map(row => ({
          ...row,
          used_g: row.used_g || 0,
          waste_g: row.waste_g || 0,
        }));
      await apiFetch("/api/printing/jobs/", {
        method: "POST",
        body: { ...form, material_usages },
      });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add print history" subtitle="Record a completed, failed, cancelled or planned print. Multiple spools can be recorded for multi-material jobs." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}

      <label>Printer<select required value={form.printer_id} onChange={e => set("printer_id", e.target.value)}>
        <option value="">Choose printer…</option>
        {printers.map(printer => <option key={printer.id} value={printer.id}>{printer.name} · {printer.model}</option>)}
      </select></label>
      <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}>
        <option value="planned">Planned</option>
        <option value="printing">Printing</option>
        <option value="success">Success</option>
        <option value="failed">Failed</option>
        <option value="cancelled">Cancelled</option>
      </select></label>

      <label>Model revision<select value={form.model_revision_id} onChange={e => revisionChanged(e.target.value)}>
        <option value="">Unlinked print</option>
        {revisionOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
      </select></label>
      <label>Project<select value={form.project_id} onChange={e => set("project_id", e.target.value)}>
        <option value="">No project</option>
        {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select></label>

      <label>Quantity<input type="number" min="1" step="1" value={form.quantity} onChange={e => set("quantity", e.target.value)} /></label>
      <label>Actual duration (min)<input type="number" min="1" step="1" value={form.actual_minutes} onChange={e => set("actual_minutes", e.target.value)} /></label>
      <label>Estimated duration (min)<input type="number" min="1" step="1" value={form.estimated_minutes} onChange={e => set("estimated_minutes", e.target.value)} /></label>
      <label>Layer height (mm)<input type="number" min="0" step="0.01" value={form.layer_height_mm} onChange={e => set("layer_height_mm", e.target.value)} /></label>
      <label>Nozzle (mm)<input type="number" min="0.1" step="0.05" value={form.nozzle_mm} onChange={e => set("nozzle_mm", e.target.value)} /></label>
      <label>Slicer<input value={form.slicer} onChange={e => set("slicer", e.target.value)} placeholder="OrcaSlicer, Creality Print…" /></label>

      <div className="full printingUsageEditor">
        <div className="printingUsageTitle"><div><strong>Material usage</strong><small>Optional. Add one row per spool/material used.</small></div><button type="button" onClick={addUsage}>＋ Material</button></div>
        {usages.map((row, index) => <div className="printingUsageRow" key={index}>
          <label>Spool<select value={row.spool_id} onChange={e => setUsage(index, "spool_id", e.target.value)}>
            <option value="">Choose spool…</option>
            {spools.map(spool => <option key={spool.id} value={spool.id}>{spool.spool_id} · {spool.filament} · {grams(spool.remaining_weight_g)}</option>)}
          </select></label>
          <label>Used (g)<input type="number" min="0" step="0.01" value={row.used_g} onChange={e => setUsage(index, "used_g", e.target.value)} /></label>
          <label>Waste (g)<input type="number" min="0" step="0.01" value={row.waste_g} onChange={e => setUsage(index, "waste_g", e.target.value)} /></label>
          <label>Cost<input type="number" min="0" step="0.01" value={row.material_cost} onChange={e => setUsage(index, "material_cost", e.target.value)} /></label>
          {usages.length > 1 && <button type="button" className="assetDanger" onClick={() => removeUsage(index)}>Remove</button>}
        </div>)}
      </div>

      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      {!printers.length && <div className="formError full">Create a printer before recording print history.</div>}
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !printers.length}>{busy ? "Saving…" : "Add print"}</button></div>
    </form>
  </Modal>;
}
