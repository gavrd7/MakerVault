import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import PrintedPartsSection from "./PrintedPartsSection";
import { printerIntent } from "./printerNavigation";
import { PrinterCameraPreview, PrinterCameraSetupModal } from "./PrinterCameras";
import PrinterJobControls from "./PrinterJobControls";
import { Badge, ImageManagerModal, LoadingBlock, Modal } from "./Common";
import ModelViewerModal, { isViewableModelFile } from "./ModelViewer";
import { suggestNextVersion } from "./FileVersionModal";

function grams(value) {
  if (value == null) return "—";
  return `${Number(value).toFixed(0)} g`;
}

function recordedGrams(value) {
  if (value == null) return "Not recorded";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(value)) + " g";
}

function formatDate(value) {
  if (!value) return "Never";
  try { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
}

function formatMoney(value, currency = "GBP") {
  if (value == null || value === "") return "—";
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value)); }
  catch { return currency + " " + Number(value).toFixed(2); }
}

function formatDurationMinutes(value) {
  const minutes = Number(value || 0);
  if (!minutes) return "0 min";
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return hours ? hours + "h " + remainder + "m" : remainder + " min";
}

function liveStateKey(snapshot, connection = null) {
  if (connection?.stale) return "stale";
  if (connection && ["error", "disconnected"].includes(connection.status)) return "error";
  const state = String(snapshot?.state || "unknown").toLowerCase();
  if (["printing", "processing", "self-testing"].includes(state)) return "printing";
  if (state === "paused") return "paused";
  if (["complete", "completed", "success"].includes(state)) return "complete";
  if (["error", "failed"].includes(state)) return "error";
  if (["cancelled", "canceled", "stopped"].includes(state)) return "stopped";
  if (state === "idle") return "idle";
  return "unknown";
}

function liveProgress(snapshot) {
  const value = snapshot?.job?.progress;
  if (value == null || Number.isNaN(Number(value))) return null;
  return Math.max(0, Math.min(100, Number(value)));
}

function shouldShowLiveProgress(snapshot) {
  const pct = liveProgress(snapshot);
  const state = String(snapshot?.state || "").toLowerCase();
  return pct != null && Boolean(
    snapshot?.job?.file_name
    || pct > 0
    || ["printing", "processing", "paused", "complete", "completed"].includes(state)
  );
}

function liveNozzles(snapshot) {
  return Object.entries(snapshot.temperatures || {})
    .filter(([key, value]) => /^tool\d+$/.test(key) && value?.actual_c != null)
    .sort(([a], [b]) => Number(a.slice(4)) - Number(b.slice(4)));
}

function liveNozzleLabel(snapshot, key) {
  const label = liveNozzles(snapshot).length > 1 ? `Nozzle ${Number(key.slice(4)) + 1}` : "Nozzle";
  return snapshot.source_metadata?.active_tool === key ? `${label} · active` : label;
}

function liveTemperature(temp) {
  if (temp?.actual_c == null) return "—";
  const actual = Number(temp.actual_c).toFixed(1).replace(".0", "");
  if (temp.target_c == null || Number(temp.target_c) <= 0) return actual + "°";
  const target = Number(temp.target_c).toFixed(0);
  return actual + "° / " + target + "°";
}

function PrinterLiveSummary({ printer, onOpen, canControl, onChanged }) {
  const connection = printer.live_status || (printer.live_connections || []).find(item => item.enabled);
  if (!connection) return null;
  const snapshot = connection.snapshot || {};
  const stateKey = liveStateKey(snapshot, connection);
  const pct = liveProgress(snapshot);
  const showProgress = shouldShowLiveProgress(snapshot);
  const job = snapshot.job || {};
  const temps = snapshot.temperatures || {};
  const connected = connection.status === "connected" && !connection.stale;

  return <div className={"printerLiveSummary printerLiveSummary-" + stateKey}>
    <div className="printerLiveSummaryHead">
      <div className="printerLiveState">
        <span className="printerLiveStateDot" aria-hidden="true" />
        <div>
          <strong>{connected ? (snapshot.state_label || "Connected") : (connection.status_label || "Unavailable")}</strong>
          <small>{job.file_name || connection.adapter_label || "Live printer source"}</small>
        </div>
      </div>
    </div>
    {showProgress && <div className="printerLiveProgressLine">
      <div className="printerLiveProgressTrack"><span style={{ width: pct + "%" }} /></div>
      <strong>{pct.toFixed(pct % 1 ? 1 : 0)}%</strong>
    </div>}
    <div className="printerLiveActions">
      <PrinterJobControls printer={printer} connection={connection} canControl={canControl} onChanged={onChanged} />
      <button type="button" className="printerLiveOpen" onClick={onOpen}>Open live</button>
    </div>
    <div className="printerLiveQuickStats">
      {liveNozzles(snapshot).map(([key, temp]) => <span key={key}><small>{liveNozzleLabel(snapshot, key)}</small><strong>{liveTemperature(temp)}</strong></span>)}
      {temps.bed?.actual_c != null && <span><small>Bed</small><strong>{liveTemperature(temps.bed)}</strong></span>}
      {temps.chamber?.actual_c != null && <span><small>Chamber</small><strong>{liveTemperature(temps.chamber)}</strong></span>}
      {(job.current_layer != null || job.total_layers != null) && <span><small>Layer</small><strong>{job.current_layer ?? "—"} / {job.total_layers ?? "—"}</strong></span>}
      {job.remaining_seconds != null && Number(job.remaining_seconds) > 0 && <span><small>Remaining</small><strong>{Math.max(1, Math.round(Number(job.remaining_seconds) / 60))} min</strong></span>}
    </div>
  </div>;
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

export default function PrintingPage({ config, projects, searchTarget = null, onOpenConsumed }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [sourceNotice, setSourceNotice] = useState("");
  const [partJob, setPartJob] = useState(null);
  const [modal, setModal] = useState("");
  const [manageModel, setManageModel] = useState(null);
  const [managePrinter, setManagePrinter] = useState(null);
  const [livePrinter, setLivePrinter] = useState(null);
  const [cameraSetup, setCameraSetup] = useState(null);
  const [cameraOffer, setCameraOffer] = useState(null);
  const [previewPrinter, setPreviewPrinter] = useState("");
  const [claimSlot, setClaimSlot] = useState(null);
  const [workspaceView, setWorkspaceView] = useState("overview");

  async function load() {
    setError("");
    try {
      const fresh = await apiFetch("/api/printing/");
      setData(fresh);
      return fresh;
    } catch (err) {
      setError(err.message);
      return null;
    }
  }

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (workspaceView !== "overview") return undefined;
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, [workspaceView]);

  useEffect(() => {
    if (!searchTarget?.type) return;
    if (searchTarget.type === "models") setWorkspaceView("models");
    else if (searchTarget.type === "spools") setWorkspaceView("spools");
    else if (searchTarget.type === "filaments") setWorkspaceView("filaments");
    else if (searchTarget.type === "printed_parts") setWorkspaceView("overview");
    else if (searchTarget.type === "printers") setWorkspaceView("overview");
  }, [searchTarget?.token]);

  useEffect(() => {
    if (!data || searchTarget?.type !== "printers" || !searchTarget.id) return;
    const timer = window.setTimeout(() => {
      document.getElementById("printer-search-target-" + searchTarget.id)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [data, searchTarget?.token, searchTarget?.id]);

  const [openedLiveTarget, setOpenedLiveTarget] = useState(null);
  useEffect(() => {
    const intent = printerIntent(searchTarget, data?.printers, openedLiveTarget);
    if (!intent) return;
    if (intent.camera) setPreviewPrinter(intent.printer.id);
    else { setPreviewPrinter(""); setLivePrinter(intent.printer); }
    setOpenedLiveTarget(intent.token);
    onOpenConsumed?.(intent.token);
  }, [data, searchTarget, openedLiveTarget]);

  useEffect(() => {
    if (previewPrinter) document.getElementById("printer-search-target-" + previewPrinter)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [previewPrinter]);

  async function saved() {
    setModal("");
    await load();
  }

  if (!data && !error) return <LoadingBlock label="Loading 3D printing workspace…" />;

  const summary = data?.summary || {};
  const canAddPrinter = Boolean(config?.permissions?.add_printer);
  const canChangePrinter = Boolean(config?.permissions?.change_printer);
  const canDeletePrinter = Boolean(config?.permissions?.delete_printer);
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

  if (workspaceView === "reusableSpools") {
    return <ReusableSpoolsPage
      onBack={() => setWorkspaceView("overview")}
      onOpenModels={() => setWorkspaceView("models")}
      models={data?.models || []}
      spools={data?.spools || []}
      locations={data?.locations || []}
      filamentProducts={data?.filaments || []}
      materialOptions={data?.common_filament_materials || []}
      canAdd={Boolean(config?.permissions?.add_spool)}
      canChange={Boolean(config?.permissions?.change_spool)}
      canDelete={Boolean(config?.permissions?.delete_spool)}
      canAddDesign={Boolean(config?.permissions?.add_filament)}
      canChangeDesign={Boolean(config?.permissions?.change_filament)}
    />;
  }

  if (workspaceView === "filaments") {
    return <FilamentLibraryPage
      filaments={data?.filaments || []}
      manufacturers={data?.filament_manufacturers || []}
      materials={data?.common_filament_materials || []}
      canChangeFilament={canChangeFilament}
      canAddFilament={canAddFilament}
      onBack={() => setWorkspaceView("overview")}
      onChanged={load}
      searchTarget={searchTarget}
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
      canChangeFilament={canChangeFilament}
      onBack={() => setWorkspaceView("overview")}
      onChanged={load}
      searchTarget={searchTarget}
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
      searchTarget={searchTarget}
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
        <button type="button" onClick={load}>Refresh</button>
      </div>
      <div className="printingActionGroups">
        <section className="printingActionGroup" aria-labelledby="printing-printers-heading">
          <h3 id="printing-printers-heading">Printers &amp; locations</h3>
          <div className="printingHeroActions">
            {canAddPrinter && <button type="button" onClick={() => setModal("printer")}>Add printer</button>}
            {canAddLocation && <button type="button" onClick={() => setModal("location")}>Add location</button>}
          </div>
        </section>
        <section className="printingActionGroup" aria-labelledby="printing-models-heading">
          <h3 id="printing-models-heading">Models &amp; print history</h3>
          <div className="printingHeroActions">
            <button type="button" onClick={() => setWorkspaceView("models")}>Model library</button>
            {canAddModel && <button type="button" onClick={() => setModal("model")}>Add model</button>}
            {canAddPrintJob && <button type="button" onClick={() => setModal("print")}>Add print history</button>}
          </div>
        </section>
        <section className="printingActionGroup">
          <h3>Filaments</h3>
          <div className="printingHeroActions">
            {canAddSpool && <button type="button" onClick={() => setModal("spool")}>Add spool</button>}
            <button type="button" onClick={() => setWorkspaceView("spools")}>Spool inventory</button>
            <button type="button" onClick={() => setWorkspaceView("reusableSpools")}>Reusable spools</button>
            <button type="button" onClick={() => setWorkspaceView("filaments")}>Filament library</button>
            {canAddFilament && <button type="button" onClick={() => setModal("filamentCatalogue")}>Filament catalogue</button>}
          </div>
        </section>
      </div>
    </section>

    {error && <div className="error">{error}</div>}
    {sourceNotice && <div className="notice printingSourceNotice" role="status"><span>{sourceNotice}</span><button type="button" aria-label="Dismiss confirmation" onClick={() => setSourceNotice("")}>×</button></div>}

    <div className="printingMetrics">
      <article><span>Models</span><strong>{summary.models || 0}</strong></article>
      <article><span>Active printers</span><strong>{summary.active_printers || 0}</strong></article>
      <article><span>Filaments</span><strong>{summary.filaments || 0}</strong></article>
      <article><span>Spools</span><strong>{summary.spools || 0}</strong></article>
      <article><span>Loaded slots</span><strong>{summary.loaded_slots || 0}</strong></article>
      <article><span>Print jobs</span><strong>{summary.print_jobs || 0}</strong></article>
    </div>


    {data?.analytics && <section className="panel printingSection printingAnalyticsPanel">
      <div className="panelHead">
        <div><h3>Print analytics</h3><p>Recorded MakerVault print history and material costs.</p></div>
        <Badge tone={data.analytics.success_rate != null && data.analytics.success_rate >= 90 ? "good" : "neutral"}>
          {data.analytics.success_rate != null ? data.analytics.success_rate + "% success" : "No completed prints"}
        </Badge>
      </div>
      <div className="printingAnalyticsMetrics">
        <article><span>Successful</span><strong>{data.analytics.successful || 0}</strong><small>of {data.analytics.completed || 0} completed</small></article>
        <article><span>Print time</span><strong>{formatDurationMinutes(data.analytics.actual_minutes)}</strong><small>actual recorded time</small></article>
        <article><span>Filament used</span><strong>{recordedGrams(data.analytics.filament_used_g)}</strong><small>{data.analytics.filament_used_g == null ? "No material usage recorded" : `${data.analytics.waste_g == null ? "Waste not recorded" : "plus " + recordedGrams(data.analytics.waste_g) + " waste"} · ${data.analytics.jobs_with_material_usage} of ${data.analytics.jobs} prints with usage${data.analytics.estimated_usage_jobs ? " · includes " + data.analytics.estimated_usage_jobs + " estimated" : ""}`}</small></article>
        <article><span>Material cost</span><strong>{data.analytics.material_cost == null ? "Not recorded" : formatMoney(data.analytics.material_cost, data.analytics.currency || config?.currency)}</strong><small>{data.analytics.foreign_cost_rows_excluded ? data.analytics.foreign_cost_rows_excluded + " other-currency row(s) excluded" : "recorded/estimated spool cost"}</small></article>
      </div>
      {!!data.analytics.printers?.length && <div className="printingAnalyticsPrinters">
        {data.analytics.printers.slice(0, 6).map(printer => <div key={printer.printer_id}>
          <div><strong>{printer.printer}</strong><small>{printer.jobs} job{printer.jobs === 1 ? "" : "s"} · {formatDurationMinutes(printer.actual_minutes)}</small></div>
          <Badge tone={printer.success_rate != null && printer.success_rate >= 90 ? "good" : "neutral"}>{printer.success_rate == null ? "No completed prints" : printer.success_rate + "% success"}</Badge>
        </div>)}
      </div>}
    </section>}

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
      <div className="printingCards printingPrinterCards">
        {(data?.printers || []).map(printer => <article className={"printingCard printingPrinterCard" + (searchTarget?.type === "printers" && searchTarget.id === printer.id ? " searchTargetRow" : "")} id={"printer-search-target-" + printer.id} key={printer.id}>
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
                <div className="printingPrinterIdentity">
                  <strong>{printer.name}</strong>
                  <small>{[printer.manufacturer, printer.model, printer.location].filter(Boolean).join(" · ")}</small>
                </div>
                <div className="printingPrinterControls">
                  <div className="printingPrinterStatus" aria-label={"Status for " + printer.name}>
                    {printer.is_active ? <Badge tone="good">Active</Badge> : <Badge>Inactive</Badge>}
                    {printer.simplyprint?.external_id && <Badge tone={printer.simplyprint?.online ? "good" : printer.simplyprint?.state === "offline" ? "danger" : "accent"}>SimplyPrint · {printer.simplyprint?.state || (printer.simplyprint?.online ? "online" : "linked")}</Badge>}
                    {printer.live_status && <Badge tone="good">{printer.live_status.adapter_label} · {printer.live_status.snapshot?.state_label || "Connected"}</Badge>}
                    {!printer.live_status && printer.live_connections?.length > 0 && <Badge tone={printer.live_connections.some(item => item.status === "error" || item.status === "disconnected") ? "danger" : "neutral"}>{printer.live_connections.length} live source{printer.live_connections.length === 1 ? "" : "s"}</Badge>}
                    {printer.installed_multi_material_label && <Badge>{printer.installed_multi_material_label}</Badge>}
                    {printer.multi_material_installed && <Badge>{printer.slots.length} slots</Badge>}
                  </div>
                  {canChangePrinter && <div className="printingPrinterActions" aria-label={"Actions for " + printer.name}>
                    <button className="printingPrinterAction printingPrinterActionLive" type="button" onClick={() => setLivePrinter(printer)}>Live monitor</button>
                    <button className="printingPrinterAction" type="button" onClick={() => setCameraSetup({ printerId: printer.id })}>Camera setup</button>
                    <button className="printingPrinterAction" type="button" onClick={() => setManagePrinter(printer)}>Manage printer</button>
                  </div>}
                </div>
              </div>
              {((printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_source_provider) || printer.catalogue?.image_source_provider) && <small className="printingPrinterImageCredit">
                Image: {(printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_source_provider) || printer.catalogue?.image_source_provider}
                {((printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_license) || printer.catalogue?.image_license) ? " · " + ((printer.multi_material_installed && printer.catalogue?.image_multi_material && printer.catalogue?.image_multi_material_license) || printer.catalogue?.image_license) : ""}
              </small>}
            </div>
          </div>
          <PrinterLiveSummary printer={printer} onOpen={() => setLivePrinter(printer)} canControl={canChangePrinter} onChanged={load} />
          <PrinterCameraPreview printer={printer} suspended={Boolean(cameraSetup || livePrinter || cameraOffer)} />
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
        <div className="printingList printingModelList">
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
        {data.recent_prints.map(job => <article className="printingListRow printingRecentPrintRow" key={job.id}>
          <div>
            <strong>{job.model || job.filename || "Unlinked print"}{job.revision ? ` · ${job.revision}` : ""}</strong>
            <small>{job.printer} · {formatDate(job.created_at)}{job.actual_minutes ? " · " + formatDurationMinutes(job.actual_minutes) : ""}{job.history_source === "live_printer" ? " · Auto-tracked" : ""}</small>
          </div>
          <div className="printingRecentPrintStats">
            <span>{job.filament_used_g == null ? "Filament not recorded" : recordedGrams(job.filament_used_g) + (job.filament_usage_estimated ? " estimated" : " used")}{job.waste_g > 0 ? " · " + recordedGrams(job.waste_g) + " waste" : ""}</span>
            {job.filament_usage_source && <small>{({ uploaded_gcode: "Uploaded G-code", printer_report: "Printer report", printer_gcode_metadata: "Printer G-code estimate", recorded: "Recorded usage" })[job.filament_usage_source] || job.filament_usage_source}</small>}
            {job.material_cost != null && <strong>{formatMoney(job.material_cost, config?.currency || "GBP")}</strong>}
          </div>
          <div className="printingBadges">
          {job.status === "success" && config?.permissions?.add_printedpart && <button onClick={() => setPartJob(job)}>Create printed parts</button>}
          <Badge tone={job.status === "success" ? "good" : job.status === "failed" ? "danger" : job.status === "printing" ? "accent" : "neutral"}>{job.status_label}</Badge>
          </div>
        </article>)}
      </div>
    </section>}

    <PrintedPartsSection config={config} projects={projects || []} createJob={partJob} onCreateConsumed={() => setPartJob(null)} focusId={searchTarget?.type === "printed_parts" ? searchTarget.id : ""} refreshToken={data} />

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
      gcodeFiles={data?.gcode_files || []}
      spools={data?.spools || []}
      models={data?.models || []}
      projects={projects || []}
      currency={config?.currency || "GBP"}
      onClose={() => setModal("")}
      onSaved={saved}
    />}
    {livePrinter && <PrinterConnectionsModal
      printer={livePrinter}
      onClose={() => setLivePrinter(null)}
      onAdded={async connection => {
        setSourceNotice(`${connection.adapter_label} successfully added for ${livePrinter.name}. Open live to check the connection status.`);
        setCameraOffer({ printerId: livePrinter.id, connectionId: connection.id, name: livePrinter.name });
        setLivePrinter(null);
        await load();
      }}
      onChanged={async () => {
        const fresh = await load();
        const updated = fresh?.printers?.find(item => item.id === livePrinter.id);
        if (updated) setLivePrinter(updated);
        return fresh;
      }}
    />}
    {cameraOffer && <Modal title="Live source added" subtitle={"Step 2 · Optional camera for " + cameraOffer.name} onClose={() => setCameraOffer(null)}>
      <p>Your live monitor is ready. Would you like to add a camera now? You can also do this later using Camera setup on the printer card.</p>
      <div className="settingsActions"><button type="button" onClick={() => setCameraOffer(null)}>Not now</button><button type="button" className="primary" onClick={() => { setCameraSetup(cameraOffer); setCameraOffer(null); }}>Add camera</button></div>
    </Modal>}
    {cameraSetup && <PrinterCameraSetupModal printer={data.printers.find(item => item.id === cameraSetup.printerId) || { id: cameraSetup.printerId, name: "Printer", live_connections: [] }} initialConnectionId={cameraSetup.connectionId} onClose={() => setCameraSetup(null)} onChanged={load} />}
    {managePrinter && <PrinterManageModal
      printer={managePrinter}
      manufacturers={data?.printer_manufacturers || []}
      models={data?.printer_catalogue_models || []}
      locations={data?.locations || []}
      canDelete={canDeletePrinter}
      onClose={() => setManagePrinter(null)}
      onSaved={async () => { setManagePrinter(null); await load(); }}
    />}
    {manageModel && <ModelManageModal
      model={manageModel}
      files={data?.model_files || []}
      printers={data?.printers || []}
      canUpload={Boolean(config?.permissions?.add_file)}
      onClose={() => setManageModel(null)}
      onChanged={async () => {
        const fresh = await load();
        const updated = fresh?.models?.find(item => item.id === manageModel.id);
        if (updated) setManageModel(updated);
        return fresh;
      }}
    />}
  </div>;
}

function SpoolInventoryPage({ spools, filaments, locations, printers, currency, canAddSpool, canChangeSpool, canDeleteSpool, canChangeFilament, onBack, onChanged, searchTarget = null }) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (searchTarget?.type !== "spools" || !searchTarget.id) return;
    setQuery("");
    const timer = window.setTimeout(() => {
      document.getElementById("spool-search-target-" + searchTarget.id)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [spools.length, searchTarget?.token, searchTarget?.id]);
  const [addOpen, setAddOpen] = useState(false);
  const [manageSpool, setManageSpool] = useState(null);
  const [dryingSpool, setDryingSpool] = useState(null);
  const [detailFilament, setDetailFilament] = useState(null);
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
        {canAddSpool && <button className="primary" onClick={() => setAddOpen(true)}>Add spool</button>}
      </div>
    </section>

    <section className="panel printingSection">
      <div className="printingLibraryToolbar">
        <div><strong>{spools.length} spool{spools.length === 1 ? "" : "s"}</strong><small>{rows.length !== spools.length ? rows.length + " matching" : "Newest updated first"}</small></div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search ID, filament, material, location or integration…" />
      </div>
      <div className="printingList">
        {rows.map(spool => <article className={"printingListRow printingLibraryRow" + (searchTarget?.id === spool.id ? " searchTargetRow" : "")} id={"spool-search-target-" + spool.id} key={spool.id}>
          <span className={"printingSwatch filamentPreview-" + (spool.transparency || "opaque")} style={filamentSwatchStyle(spool)} />
          <div>
            <strong>{spool.spool_id} · {spool.filament}</strong>
            <small>{[spool.manufacturer, spool.material, spool.color_name].filter(Boolean).join(" · ")} · {grams(spool.remaining_weight_g)} remaining{spool.location ? " · " + spool.location : ""}</small>
            <small>{spool.rfid_uid ? "RFID " + spool.rfid_uid + " · " : ""}Updated {formatDate(spool.updated_at)} · Last dried: {spool.last_dried_at || "Not recorded"}</small>
          </div>
          <div className="printingBadges">
            {spool.loaded_slots?.length > 0 && <Badge tone="accent">Loaded</Badge>}
            <Badge tone={spool.catalogue_matched ? "good" : "warning"}>
              {spool.catalogue_matched ? "✓ Matched" : "Unmatched"}
            </Badge>
            <Badge>{spool.status_label || spool.status}</Badge>
            {(spool.external_links || []).map(link => <Badge key={link.id}>{link.provider_label}</Badge>)}
            <button type="button" onClick={() => setDetailFilament(filaments.find(item => item.id === spool.filament_id) || null)}>Filament details</button>
            {canChangeSpool && <button type="button" onClick={() => setManageSpool(spool)}>RFID / identity</button>}
            {canChangeSpool && <button type="button" onClick={() => setDryingSpool(spool)}>Drying</button>}
            {canDeleteSpool && <button className="dangerButton" type="button" onClick={() => setDeleteSpool(spool)}>Delete</button>}
          </div>
        </article>)}
        {!rows.length && <div className="printingEmptyInline">{term ? "No spools match this search." : "No spool records yet."}</div>}
      </div>
    </section>

    {addOpen && <SpoolModal filaments={filaments} locations={locations} printers={printers} currency={currency} onClose={() => setAddOpen(false)} onSaved={async () => { setAddOpen(false); await onChanged(); }} />}
    {dryingSpool && <SpoolDryingModal spool={dryingSpool} onClose={() => setDryingSpool(null)} onSaved={async () => { setDryingSpool(null); await onChanged(); }} />}
    {manageSpool && <SpoolIdentityModal spool={manageSpool} onClose={() => setManageSpool(null)} onSaved={async () => { setManageSpool(null); await onChanged(); }} />}
    {detailFilament && <FilamentDetailsModal
      filament={detailFilament}
      canChangeFilament={canChangeFilament}
      onChanged={onChanged}
      onClose={() => setDetailFilament(null)}
    />}
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


function SpoolDryingModal({ spool, onClose, onSaved }) {
  const [lastDried, setLastDried] = useState(spool.last_dried_at || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiFetch("/api/printing/spools/" + spool.id + "/", {
        method: "PATCH",
        body: { last_dried_at: lastDried || null },
      });
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={"Drying · " + spool.spool_id} subtitle="Track when this filament was last dried. Clearing the date marks it as not recorded." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <div className="settingsCallout full"><strong>{spool.filament}</strong><p>{[spool.material, spool.color_name].filter(Boolean).join(" · ")}</p></div>
      <label className="full">Last dried<input type="date" value={lastDried} onChange={event => setLastDried(event.target.value)} /><small>Leave blank if unknown. The date belongs to this filament spool record.</small></label>
      <div className="formActions full"><button type="button" onClick={() => setLastDried("")}>Clear date</button><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save drying date"}</button></div>
    </form>
  </Modal>;
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


function ModelLibraryPage({ models, files, printers, projects, canAddModel, canChangeModel, canDeleteModel, canUpload, onBack, onChanged, searchTarget = null }) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (searchTarget?.type !== "models" || !searchTarget.id) return;
    setQuery("");
    const timer = window.setTimeout(() => {
      document.getElementById("model-search-target-" + searchTarget.id)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [models.length, searchTarget?.token, searchTarget?.id]);
  const [addOpen, setAddOpen] = useState(false);
  const [manageModel, setManageModel] = useState(null);
  const [viewerModel, setViewerModel] = useState(null);
  const [deleteModel, setDeleteModel] = useState(null);
  const [reusableModelBusy, setReusableModelBusy] = useState("");

  async function toggleReusableModel(model, enabled) {
    setReusableModelBusy(model.id);
    try {
      await apiFetch("/api/printing/models/" + model.id + "/reusable-spool-design/", {
        method: enabled ? "POST" : "DELETE",
      });
      await onChanged();
    } catch (err) {
      window.alert(err.message);
    } finally {
      setReusableModelBusy("");
    }
  }


  async function refreshSelectedModel(modelId, setter) {
    const fresh = await onChanged();
    const updated = fresh?.models?.find(item => item.id === modelId);
    if (updated) setter(updated);
    return fresh;
  }

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
      <div className="printingList printingModelList">
        {rows.map(model => {
          const analysis = newestGeometryAnalysis(model);
          const dims = analysis?.dimensions_mm;
          return <article className={"printingListRow printingModelRow printingLibraryRow" + (searchTarget?.id === model.id ? " searchTargetRow" : "")} id={"model-search-target-" + model.id} key={model.id}>
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
              {canChangeModel && <div className="modelReusableSpoolRow"><label className="modelReusableSpoolToggle"><input type="checkbox" checked={Boolean(model.is_reusable_spool)} disabled={reusableModelBusy === model.id} onChange={e => toggleReusableModel(model, e.target.checked)} /> Reusable spool</label></div>}
            </div>
          </article>;
        })}
        {!rows.length && <div className="printingEmptyInline">{term ? "No models match this search." : "No 3D models yet."}</div>}
      </div>
    </section>

    {addOpen && <ModelModal projects={projects} canUpload={canUpload} onClose={() => setAddOpen(false)} onSaved={async () => { setAddOpen(false); await onChanged(); }} />}
    {manageModel && <ModelManageModal
      model={manageModel}
      files={files}
      printers={printers}
      canUpload={canUpload}
      onClose={() => setManageModel(null)}
      onChanged={() => refreshSelectedModel(manageModel.id, setManageModel)}
    />}
    {viewerModel && <ModelViewerModal
      model={viewerModel}
      printers={printers}
      canAnalyse={canChangeModel}
      onClose={() => setViewerModel(null)}
      onChanged={() => refreshSelectedModel(viewerModel.id, setViewerModel)}
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
  const [deleteArmed, setDeleteArmed] = useState(false);
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

function PrinterConnectionsModal({ printer, onClose, onChanged, onAdded }) {
  const [data, setData] = useState({ rows: [], adapters: [] });
  const [form, setForm] = useState({
    adapter: "moonraker",
    endpoint_url: "",
    poll_interval_seconds: 30,
    api_key: "",
    access_code: "",
    serial: printer.serial_number || "",
    username: "",
    password: "",
    check_code: "",
  });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function loadConnections() {
    try {
      const result = await apiFetch("/api/printing/printers/" + printer.id + "/connections/");
      setData(result);
      return result;
    } catch (err) {
      setError(err.message);
      return null;
    }
  }

  useEffect(() => {
    loadConnections();
    const timer = window.setInterval(loadConnections, 10000);
    return () => window.clearInterval(timer);
  }, [printer.id]);

  const selectableAdapters = (data.adapters || []).filter(item => item.supported);
  const configured = new Set((data.rows || []).map(item => item.adapter));
  const manufacturerKey = String(printer.manufacturer || "").toLowerCase();
  const modelKey = String(printer.model || "").toLowerCase();
  const preferredAdapter = manufacturerKey.includes("creality")
    ? "creality_local"
    : manufacturerKey.includes("bambu")
      ? "bambu_local"
      : manufacturerKey.includes("prusa")
        ? "prusa"
        : manufacturerKey.includes("flashforge")
          ? "flashforge"
          : manufacturerKey.includes("anycubic")
            ? "anycubic"
            : manufacturerKey.includes("elegoo") && (modelKey.includes("neptune 4") || modelKey.includes("orangestorm"))
              ? "elegoo"
              : manufacturerKey.includes("qidi") && ["plus4", "plus 4", "q1 pro", "x-max 3", "x-plus 3", "x-smart 3", "q2"].some(name => modelKey.includes(name))
                ? "qidi"
                : manufacturerKey.includes("sovol") && modelKey.includes("sv08")
                  ? "sovol"
                  : manufacturerKey.includes("snapmaker") && modelKey.includes("u1")
                    ? "snapmaker"
                    : manufacturerKey.includes("voron")
                      ? "voron"
                      : "";
  const available = selectableAdapters
    .filter(item => !configured.has(item.key))
    .sort((left, right) => Number(right.key === preferredAdapter) - Number(left.key === preferredAdapter));
  const selectedAdapterInfo = available.find(item => item.key === form.adapter)
    || selectableAdapters.find(item => item.key === form.adapter)
    || null;

  useEffect(() => {
    if (!available.length) return;
    const nextAdapter = available.some(item => item.key === form.adapter)
      ? form.adapter
      : (available.find(item => item.key === preferredAdapter)?.key || available[0].key);
    setForm(current => ({
      ...current,
      adapter: nextAdapter,
      endpoint_url: ["creality_local", "bambu_local", "prusa", "flashforge", "anycubic", "elegoo", "qidi", "sovol", "snapmaker", "voron"].includes(nextAdapter) && !current.endpoint_url
        ? (printer.connection_host || "")
        : current.endpoint_url,
      serial: ["bambu_local", "flashforge"].includes(nextAdapter) && !current.serial
        ? (printer.serial_number || "")
        : current.serial,
    }));
  }, [available.map(item => item.key).join("|"), preferredAdapter, printer.connection_host]);

  async function addConnection(event) {
    event.preventDefault();
    if (busy) return;
    setBusy("add"); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/printing/printers/" + printer.id + "/connections/", {
        method: "POST",
        body: form,
      });
      await onAdded(result.item);
    } catch (err) {
      const reasons = Object.entries(err.fields || {}).map(([field, messages]) =>
        `${field.replaceAll("_", " ")}: ${Array.isArray(messages) ? messages.join(" ") : messages}`
      ).join("; ");
      setError("Could not add the live source: " + (reasons || err.message));
    } finally {
      setBusy("");
    }
  }

  async function refreshConnection(connection) {
    setBusy(connection.id); setError(""); setNotice("");
    try {
      const result = await apiFetch(
        "/api/printing/printers/" + printer.id + "/connections/" + connection.id + "/refresh/",
        { method: "POST" },
      );
      await loadConnections();
      await onChanged();
      setNotice((result.item?.adapter_label || "Printer source") + " refreshed.");
    } catch (err) {
      setError(err.message);
      await loadConnections();
      await onChanged();
    } finally {
      setBusy("");
    }
  }

  async function toggleConnection(connection) {
    setBusy(connection.id); setError(""); setNotice("");
    try {
      await apiFetch(
        "/api/printing/printers/" + printer.id + "/connections/" + connection.id + "/",
        { method: "PATCH", body: { enabled: !connection.enabled } },
      );
      await loadConnections();
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function toggleControls(connection) {
    setBusy(connection.id); setError(""); setNotice("");
    try {
      await apiFetch("/api/printing/printers/" + printer.id + "/connections/" + connection.id + "/", {
        method: "PATCH", body: { controls_enabled: !connection.controls.enabled },
      });
      await loadConnections();
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function copyDiagnostics(connection) {
    const payload = {
      maker_vault: "printer-adapter-diagnostics",
      printer: {
        name: printer.name,
        manufacturer: printer.manufacturer,
        model: printer.model,
      },
      adapter: {
        key: connection.adapter,
        label: connection.adapter_label,
        protocol: connection.protocol,
        validation: connection.validation,
        validation_label: connection.validation_label,
        compatibility_hint: connection.compatibility_hint,
      },
      connection: {
        status: connection.status,
        stale: connection.stale,
        capabilities: connection.capabilities,
        last_checked_at: connection.last_checked_at,
        last_seen_at: connection.last_seen_at,
        last_error: connection.last_error,
        config_flags: connection.config,
      },
      snapshot: connection.snapshot || {},
    };
    const text = JSON.stringify(payload, null, 2);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
      await navigator.clipboard.writeText(text);
      setNotice(connection.adapter_label + " diagnostics copied. Review filenames/serials before sharing.");
    } catch (_err) {
      window.prompt("Copy these sanitized MakerVault diagnostics:", text);
    }
  }

  async function removeConnection(connection) {
    if (!window.confirm("Remove " + connection.adapter_label + " from " + printer.name + "?")) return;
    setBusy(connection.id); setError(""); setNotice("");
    try {
      await apiFetch(
        "/api/printing/printers/" + printer.id + "/connections/" + connection.id + "/",
        { method: "DELETE" },
      );
      await loadConnections();
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  function progress(snapshot) {
    const value = snapshot?.job?.progress;
    return value == null ? null : Math.max(0, Math.min(100, Number(value)));
  }

  function adapterChanged(adapter) {
    const manufacturerLocal = ["creality_local", "bambu_local", "prusa", "flashforge", "anycubic", "elegoo", "qidi", "sovol", "snapmaker", "voron"].includes(adapter);
    setForm(current => ({
      ...current,
      adapter,
      endpoint_url: manufacturerLocal
        ? (current.endpoint_url || printer.connection_host || "")
        : (["creality_local", "bambu_local", "prusa", "flashforge", "anycubic", "elegoo", "qidi", "sovol", "snapmaker", "voron"].includes(current.adapter) ? "" : current.endpoint_url),
      api_key: ["creality_local", "bambu_local"].includes(adapter) ? "" : current.api_key,
      access_code: adapter === "bambu_local" ? current.access_code : "",
      serial: ["bambu_local", "flashforge"].includes(adapter) ? (current.serial || printer.serial_number || "") : current.serial,
      username: adapter === "prusa" ? current.username : "",
      password: adapter === "prusa" ? current.password : "",
      check_code: adapter === "flashforge" ? current.check_code : "",
    }));
  }


  return <Modal
    title={"Live monitoring · " + printer.name}
    subtitle="Attach one or more provider-neutral status sources to this physical printer. Local connections are preferred and monitoring is read-only by default."
    onClose={onClose}
    wide
  >
    {error && <div className="formError" role="alert">{error}</div>}
    {notice && <div className="notice">{notice}</div>}

    <div className="printingIntegrationGrid printerLiveSources">
      {(data.rows || []).map(connection => {
        const snapshot = connection.snapshot || {};
        const pct = progress(snapshot);
        const showProgress = shouldShowLiveProgress(snapshot);
        const tone = connection.stale ? "danger" : connection.status === "connected" ? "good" : connection.status === "error" || connection.status === "disconnected" ? "danger" : connection.experimental ? "accent" : "neutral";
        return <article key={connection.id}>
          <div className="settingsIntegrationHead">
            <strong>{connection.adapter_label}</strong>
            <div className="printingBadges">
              {connection.experimental && <Badge tone="accent">Experimental</Badge>}
              <Badge tone={tone}>{connection.stale ? "Stale" : connection.status_label}</Badge>
            </div>
          </div>
          <small>{connection.endpoint_url || "Endpoint not configured"}</small>
          {(snapshot.source_metadata?.hostname || snapshot.source_metadata?.model) && <small>
            {[snapshot.source_metadata?.hostname, snapshot.source_metadata?.model].filter(Boolean).join(" · ")}
          </small>}
          <div className={"printingLivePanel printingLivePanel-" + liveStateKey(snapshot, connection)}>
            <div className="printingLivePanelHead">
              <div className="printingLivePanelState">
                <span className="printingLiveStateDot" aria-hidden="true" />
                <div>
                  <strong>{snapshot.state_label || "No live snapshot yet"}</strong>
                  <small>{snapshot.job?.file_name || (connection.status === "connected" ? "Printer reachable · no active file" : "Refresh this source to test the connection")}</small>
                </div>
              </div>
              {showProgress && <strong className="printingLivePercent">{pct.toFixed(pct % 1 ? 1 : 0)}%</strong>}
            </div>
            {showProgress && <div className="printingLiveProgress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct}><span style={{ width: pct + "%" }} /></div>}
            <div className="printingLiveMetrics">
              {liveNozzles(snapshot).map(([key, temp]) => <div key={key}><span>{liveNozzleLabel(snapshot, key)}</span><strong>{liveTemperature(temp)}</strong></div>)}
              {snapshot.temperatures?.bed?.actual_c != null && <div><span>Bed</span><strong>{liveTemperature(snapshot.temperatures.bed)}</strong></div>}
              {snapshot.temperatures?.chamber?.actual_c != null && <div><span>Chamber</span><strong>{liveTemperature(snapshot.temperatures.chamber)}</strong></div>}
              {snapshot.job?.elapsed_seconds != null && <div><span>Elapsed</span><strong>{Math.round(snapshot.job.elapsed_seconds / 60)} min</strong></div>}
              {snapshot.job?.remaining_seconds != null && <div><span>Remaining</span><strong>{Math.round(snapshot.job.remaining_seconds / 60)} min</strong></div>}
              {(snapshot.job?.current_layer != null || snapshot.job?.total_layers != null) && <div><span>Layer</span><strong>{snapshot.job?.current_layer ?? "—"} / {snapshot.job?.total_layers ?? "—"}</strong></div>}
            </div>
            {snapshot.materials?.length > 0 && <div className="printingLiveSectionTitle"><span>{connection.adapter === "bambu_local" ? "AMS live slots" : connection.adapter === "creality_local" ? "CFS live slots" : "Material slots"}</span><small>{snapshot.materials.length} detected</small></div>}
            {snapshot.materials?.length > 0 && <div className="printingLiveMaterials">
              {snapshot.materials.slice(0, 8).map((material, index) => {
                const remaining = material.remaining_percent == null ? null : Math.max(0, Math.min(100, Number(material.remaining_percent)));
                return <div className={"printingLiveMaterial" + (material.selected ? " selected" : "")} key={(material.unit_index ?? 0) + "-" + material.slot_index + "-" + index}>
                  <span className="printingSwatch" style={material.color_hex ? { background: material.color_hex } : undefined} />
                  <div className="printingLiveMaterialMain">
                    <span>{material.system === "bambu_ams" ? "AMS" : material.system === "creality_cfs" ? "CFS" : "Unit"} {Number(material.unit_index || 0) + 1} · slot {Number(material.slot_index || 0) + 1}{material.selected ? " · loaded" : ""}</span>
                    <strong>{material.product_name || material.material || "Filament"}</strong>
                    <small>{[material.vendor, material.material].filter(Boolean).join(" · ") || "Material details unavailable"}</small>
                  </div>
                  {remaining != null && <div className="printingMaterialRemaining">
                    <strong>{Math.round(remaining)}%</strong>
                    <div className="printingMaterialTrack"><span style={{ width: remaining + "%", background: material.color_hex || undefined }} /></div>
                  </div>}
                </div>;
              })}
            </div>}
          </div>
          {snapshot.warnings?.map((warning, index) => <small className="integrationError" key={"warning-" + index}>{warning}</small>)}
          {connection.validation_label && <small>{connection.validation_label}{connection.protocol ? " · " + connection.protocol : ""}</small>}
          <div className="printerLiveFeatures" aria-label="Live data features">
            {[["job", "Job"], ["progress", "Progress"], ["temperatures", "Temperatures"], ["materials", "Loaded filament"]].filter(([key]) => connection.capabilities?.[key]).map(([key, label]) => <Badge key={key}>{label}</Badge>)}
          </div>
          <small>Last seen: {connection.last_seen_at ? formatDate(connection.last_seen_at) : "Never"}</small>
          {connection.last_error && <small className="integrationError">{connection.last_error}</small>}
          {connection.controls?.supported && data.can_control && <div className="settingsCallout printerControlsSettings">
            <label className="printerControlsToggle"><input type="checkbox" checked={connection.controls.enabled} disabled={Boolean(busy)} onChange={() => toggleControls(connection)} /><span>Allow Pause, Resume and Cancel</span></label>
            <small>{connection.controls.enabled ? "Controls enabled for this source. Actions require a current active job." : "Read-only monitoring. Enable controls for this source to act on a print."}</small>
            <PrinterJobControls printer={printer} connection={connection} canControl={data.can_control} disabled={Boolean(busy)} onChanged={async () => { await loadConnections(); await onChanged(); }} />
          </div>}
          <div className="settingsActions compact">
            <button type="button" disabled={busy === connection.id || !connection.enabled || !connection.supported} onClick={() => refreshConnection(connection)}>{busy === connection.id ? "Working…" : "Refresh"}</button>
            <button type="button" onClick={() => copyDiagnostics(connection)}>Copy diagnostics</button>
            <button type="button" disabled={busy === connection.id} onClick={() => toggleConnection(connection)}>{connection.enabled ? "Disable" : "Enable"}</button>
            <button type="button" className="dangerButton" disabled={busy === connection.id} onClick={() => removeConnection(connection)}>Remove</button>
          </div>
        </article>;
      })}
      {!data.rows?.length && <div className="printingEmptyInline">No live printer sources are configured yet.</div>}
    </div>

    {!!available.length && <form className="formGrid" onSubmit={addConnection}>
      <div className="full settingsCallout">
        <strong>Add live source</strong>
        <p>MakerVault supports Moonraker/Klipper and OctoPrint plus experimental manufacturer-local adapters for Creality, Bambu Lab and PrusaLink. A single physical printer can use more than one source without creating duplicate MakerVault printer records.</p>
      </div>
      <label>Adapter<select value={form.adapter} onChange={e => adapterChanged(e.target.value)}>
        {available.map(item => <option key={item.key} value={item.key}>{item.label}{item.experimental ? " · experimental" : ""}</option>)}
      </select></label>
      {selectedAdapterInfo && <div className="settingsCallout">
        <strong>{selectedAdapterInfo.validation_label || (selectedAdapterInfo.experimental ? "Experimental" : "Supported")}</strong>
        <p>{selectedAdapterInfo.compatibility_hint || selectedAdapterInfo.protocol || "MakerVault will use this provider as a read-only live source."}</p>
        {selectedAdapterInfo.protocol && <small>Protocol: {selectedAdapterInfo.protocol}</small>}
      </div>}
      <label>{["creality_local", "bambu_local", "prusa", "flashforge", "anycubic", "elegoo", "qidi", "sovol", "snapmaker", "voron"].includes(form.adapter) ? "Printer host / IP" : "Service URL"}<input required value={form.endpoint_url} onChange={e => setForm(current => ({ ...current, endpoint_url: e.target.value }))} placeholder={form.adapter === "creality_local" ? "192.168.1.34" : form.adapter === "bambu_local" ? "192.168.1.45" : form.adapter === "prusa" ? "prusa.local" : form.adapter === "flashforge" ? "192.168.1.60" : form.adapter === "anycubic" ? "192.168.1.70" : ["moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron"].includes(form.adapter) ? "printer.local or http://printer.local:7125" : "http://octoprint.local"} /></label>
      {!["creality_local", "bambu_local"].includes(form.adapter) && <label>API key (optional)<input type="password" value={form.api_key} onChange={e => setForm(current => ({ ...current, api_key: e.target.value }))} autoComplete="new-password" placeholder={form.adapter === "prusa" ? "Legacy / API-key PrusaLink setups" : "Only when your service requires one"} /></label>}
      {form.adapter === "creality_local" && <div className="settingsCallout">
        <strong>Creality LAN WebSocket</strong>
        <p>MakerVault uses the printer's local Creality Print protocol on port 9999. Your existing printer host/IP is pre-filled when available; no Creality Cloud login is required.</p>
      </div>}
      {form.adapter === "bambu_local" && <>
        <label>Printer serial<input required value={form.serial} onChange={e => setForm(current => ({ ...current, serial: e.target.value }))} placeholder="Printer serial number" /></label>
        <label>LAN access code<input required type="password" value={form.access_code} onChange={e => setForm(current => ({ ...current, access_code: e.target.value }))} autoComplete="new-password" placeholder="LAN access code from printer" /></label>
        <div className="settingsCallout full">
          <strong>Bambu Lab local MQTT</strong>
          <p>MakerVault connects directly to the printer over MQTT/TLS on port 8883 using the LAN access code and serial number. The access code stays server-side. This adapter is experimental until community hardware validation is complete.</p>
        </div>
      </>}
      {form.adapter === "prusa" && <>
        <label>PrusaLink username (optional)<input value={form.username} onChange={e => setForm(current => ({ ...current, username: e.target.value }))} autoComplete="username" placeholder="For HTTP Digest authentication" /></label>
        <label>PrusaLink password (optional)<input type="password" value={form.password} onChange={e => setForm(current => ({ ...current, password: e.target.value }))} autoComplete="new-password" placeholder="For HTTP Digest authentication" /></label>
        <div className="settingsCallout full">
          <strong>PrusaLink local API</strong>
          <p>Current PrusaLink exposes local status and job telemetry through its documented HTTP API. MakerVault supports HTTP Digest credentials and legacy API-key setups; credentials stay server-side.</p>
        </div>
      </>}
      {form.adapter === "flashforge" && <>
        <label>Printer serial<input required value={form.serial} onChange={e => setForm(current => ({ ...current, serial: e.target.value }))} placeholder="Printer serial number" /></label>
        <label>Check code<input required type="password" value={form.check_code} onChange={e => setForm(current => ({ ...current, check_code: e.target.value }))} autoComplete="new-password" placeholder="Local printer check code" /></label>
        <div className="settingsCallout full">
          <strong>FlashForge local API</strong>
          <p>MakerVault polls the printer's local HTTP API on port 8898 using its serial number and check code. Supported telemetry includes job state/progress, layers, temperatures and material-station slots where the printer reports them.</p>
        </div>
      </>}
      {form.adapter === "anycubic" && <div className="settingsCallout full">
        <strong>Anycubic LAN mode</strong>
        <p>MakerVault performs the printer's local signed LAN handshake on port 18910, then opens its temporary MQTT/TLS session on port 9883. No Anycubic Cloud credentials are required. The printer must be in LAN mode; this adapter currently targets the Kobra 3 / S1-generation protocol and remains experimental.</p>
      </div>}
      <label>Polling interval<div className="intervalInput"><input type="number" min="10" max="3600" step="5" value={form.poll_interval_seconds} onChange={e => setForm(current => ({ ...current, poll_interval_seconds: e.target.value }))} /><span>seconds</span></div></label>
      <div className="formActions full"><button className="primary" disabled={busy === "add"}>{busy === "add" ? "Adding…" : "Add live source"}</button></div>
    </form>}

    <div className="settingsCallout">
      <strong>Read-only first</strong>
      <p>All live adapters, including the manufacturer Moonraker profiles, remain read-only in MakerVault even where the upstream printer supports pause/resume/cancel. Control actions stay behind a later permissioned/confirmed pass.</p>
    </div>
  </Modal>;
}


function PrinterManageModal({ printer, manufacturers, models, locations, canDelete, onClose, onSaved }) {
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
  const [deleteArmed, setDeleteArmed] = useState(false);
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

  async function removePrinter() {
    if (!deleteArmed) {
      setDeleteArmed(true);
      setError("");
      return;
    }
    setBusy(true); setError("");
    try {
      await apiFetch("/api/printing/printers/" + printer.id + "/", { method: "DELETE" });
      await onSaved();
    } catch (err) {
      setDeleteArmed(false);
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
      <div className="formActions full">
        {canDelete && <button type="button" className="dangerButton" disabled={busy} onClick={removePrinter}>{deleteArmed ? "Confirm delete printer" : "Delete printer"}</button>}
        {deleteArmed && <button type="button" disabled={busy} onClick={() => setDeleteArmed(false)}>Keep printer</button>}
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy}>{busy ? "Saving…" : "Save printer"}</button>
      </div>
      {deleteArmed && <div className="settingsCallout full"><strong>Delete owned printer?</strong><p>This removes the owned-printer record and its live connection/camera configuration. Existing print history is retained. A printer cannot be deleted while it is currently printing.</p></div>}
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



function ReusableSpoolsPage({ onBack, onOpenModels, models, spools, locations, filamentProducts, materialOptions, canAdd, canChange, canDelete, canAddDesign, canChangeDesign }) {
  const [designs, setDesigns] = useState([]);
  const [manufacturerDesigns, setManufacturerDesigns] = useState([]);
  const [reels, setReels] = useState([]);
  const [densityProductId, setDensityProductId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [working, setWorking] = useState(false);
  const [form, setForm] = useState("");
  const [editing, setEditing] = useState(null);
  const [designForm, setDesignForm] = useState({ name: "", design_type: "printed", manufacturer: "", material: "", nominal_tare_g: "", max_dryer_temp_c: "", temperature_source: "", source_url: "", outer_diameter_mm: "", width_mm: "", hub_diameter_mm: "", capacity_g: "", description: "", model_3d_id: "" });
  const [reelForm, setReelForm] = useState({ code: "", design_id: "", measured_tare_g: "", color_name: "", material_override: "", condition: "usable", storage_location_id: "", filament_spool_id: "", notes: "" });

  async function load() {
    try {
      const [d, r, catalogue] = await Promise.all([
        apiFetch("/api/printing/reusable-spool-designs/"),
        apiFetch("/api/printing/reusable-spools/"),
        apiFetch("/api/printing/reusable-spool-manufacturers/"),
      ]);
      setDesigns(d.rows || []);
      setManufacturerDesigns(catalogue.rows || []);
      setReels(r.rows || []);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { load(); }, []);

  function startDesign(item = null) {
    setError("");
    setEditing(item);
    setDensityProductId("");
    setDesignForm(item ? Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ""])) : { name: "", design_type: "printed", manufacturer: "", material: "", nominal_tare_g: "", max_dryer_temp_c: "", temperature_source: "", source_url: "", outer_diameter_mm: "", width_mm: "", hub_diameter_mm: "", capacity_g: "", description: "", model_3d_id: "" });
    setForm("design");
  }

  function startReel(item = null) {
    setError("");
    setEditing(item);
    setReelForm(item ? Object.fromEntries(Object.entries(item).map(([k, v]) => [k, v ?? ""])) : { design_id: designs[0]?.id || "", measured_tare_g: "", color_name: "", material_override: "", condition: "usable", storage_location_id: "", filament_spool_id: "", notes: "" });
    setForm("reel");
  }

  const manufacturerAliases = {
    "bambu": "Bambu Lab", "bambulab": "Bambu Lab", "bambulabs": "Bambu Lab",
    "prusa": "Prusa Research", "prusament": "Prusa Research",
    "esun": "eSUN", "sunlu": "SUNLU", "creality": "Creality",
    "polymaker": "Polymaker", "panchroma": "Polymaker",
  };
  const manufacturerKey = raw => String(raw || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const manufacturerNames = [...new Set([...manufacturerDesigns.map(x => x.manufacturer), ...designs.map(x => x.manufacturer)].filter(Boolean))];
  function resolveManufacturer(raw) {
    const key = manufacturerKey(raw);
    return manufacturerAliases[key] || manufacturerNames.find(name => manufacturerKey(name) === key) || null;
  }
  const matchedManufacturer = resolveManufacturer(designForm.manufacturer);
  function acceptManufacturer() {
    if (matchedManufacturer) setDesignForm(p => ({ ...p, manufacturer: matchedManufacturer }));
  }

  const selectedModel = models.find(m => m.id === designForm.model_3d_id);
  const geometry = newestGeometryAnalysis(selectedModel);
  const dimensions = geometry?.dimensions_mm;
  const volume = Number(geometry?.volume_cm3);
  const materials = [...new Set([...materialOptions, ...filamentProducts.map(p => p.material), designForm.material].filter(Boolean))].sort();
  const densityProducts = filamentProducts.filter(p =>
    String(p.material || "").trim().toLowerCase() === String(designForm.material || "").trim().toLowerCase() &&
    Number(p.density_g_cm3) > 0
  );
  const sourceProduct = densityProducts.find(p => String(p.id) === densityProductId);
  // Derive a typical density exclusively from recorded MakerVault filament data.
  // Median avoids skew from an outlier; an exact filament selection overrides it.
  const recordedDensities = densityProducts.map(p => Number(p.density_g_cm3)).sort((a, b) => a - b);
  const mid = Math.floor(recordedDensities.length / 2);
  const libraryDensity = recordedDensities.length
    ? (recordedDensities.length % 2 ? recordedDensities[mid] : (recordedDensities[mid - 1] + recordedDensities[mid]) / 2)
    : null;
  const density = sourceProduct ? Number(sourceProduct.density_g_cm3) : libraryDensity;
  // 15% infill baseline, excluding variable walls and top/bottom layers.
  const estimatedMass = Number.isFinite(volume) && volume > 0 && Number.isFinite(density) && density > 0
    ? (volume * density * 0.15).toFixed(2) : null;

  function applyGeometryDimension(field, value) {
    if (Number(value) > 0) setDesignForm(old => ({ ...old, [field]: Number(value).toFixed(2) }));
  }

  async function submit(event) {
    event.preventDefault();
    setWorking(true);
    setError("");
    const isDesign = form === "design";
    const endpoint = isDesign ? "/api/printing/reusable-spool-designs/" : "/api/printing/reusable-spools/";
    try {
      await apiFetch(endpoint + (editing ? editing.id + "/" : ""), {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(isDesign ? designForm : reelForm),
      });
      setNotice(isDesign ? "Spool design saved." : "Reusable spool saved.");
      setForm("");
      setEditing(null);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setWorking(false);
    }
  }

  function lookupKnownManufacturerSpecs() {
    const candidate = manufacturerDesigns.find(x =>
      (x.name || "").trim().toLowerCase() === (designForm.name || "").trim().toLowerCase() &&
      (x.manufacturer || "").trim().toLowerCase() === (designForm.manufacturer || "").trim().toLowerCase()
    );
    if (!candidate) {
      setNotice("No exact manufacturer catalogue match. Keep your values or enter verified specifications manually.");
      return;
    }
    const available = ["source_url", "description", "material", "nominal_tare_g", "max_dryer_temp_c", "temperature_source", "outer_diameter_mm", "width_mm", "hub_diameter_mm", "capacity_g"];
    const update = {};
    for (const key of available) {
      if ((designForm[key] === "" || designForm[key] == null) && candidate[key] !== "" && candidate[key] != null) {
        update[key] = candidate[key];
      }
    }
    setDesignForm(p => ({ ...p, ...update }));
    setNotice(Object.keys(update).length
      ? "Filled available catalogue details without changing your entries. Verify the exact variant."
      : "Catalogue match found, but no additional verified specifications are available yet.");
  }

  async function importManufacturerDesign(item) {
    setWorking(true);
    setError("");
    try {
      await apiFetch("/api/printing/reusable-spool-manufacturers/", { method: "POST", body: JSON.stringify({ key: item.key }) });
      setNotice(item.name + " added to your spool designs.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setWorking(false);
    }
  }

  async function remove(kind, item) {
    if (!window.confirm("Delete " + (item.name || item.code) + "?")) return;
    setWorking(true);
    try {
      await apiFetch("/api/printing/" + (kind === "design" ? "reusable-spool-designs/" : "reusable-spools/") + item.id + "/", { method: "DELETE" });
      setNotice("Record deleted.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setWorking(false);
    }
  }

  const field = (label, key, type = "text") => <label key={key}>{label}
    <input type={type} step={type === "number" ? "any" : undefined} value={(form === "design" ? designForm : reelForm)[key] ?? ""} onChange={e =>
      form === "design" ? setDesignForm(p => ({ ...p, [key]: e.target.value })) : setReelForm(p => ({ ...p, [key]: e.target.value }))
    } />
  </label>;

  return <div className="printingStack">
    <section className="panel printingLibraryHero">
      <div>
        <span className="settingsEyebrow">3D Printing · Filaments</span>
        <h2>Reusable spools</h2>
        <p>Manage refillable empty spool designs and the individual reels you own. A reusable reel is separate from its current filament stock.</p>
      </div>
      <div className="printingHeroActions">
        <button type="button" onClick={onBack}>← Printing overview</button>
        <button type="button" onClick={onOpenModels}>Model library (STL/3MF)</button>
        {canAddDesign && <button type="button" onClick={() => startDesign()}>Add design</button>}
        {canAdd && <button type="button" className="primary" onClick={() => startReel()} disabled={!designs.length}>Add reusable spool</button>}
      </div>
    </section>
    {error && !form && <div className="error" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
    <section className="panel printingSection">
      <div className="panelHead"><h3>Owned reusable spools ({reels.length})</h3></div>
      <div className="printingList">
        {reels.map(reel => <article className="printingListRow" key={reel.id}>
          <div><strong>{reel.code} · {reel.design_name}</strong>
            <small>{[reel.color_name, reel.material_override].filter(Boolean).join(" · ") || "No material/colour recorded"}</small>
            <small>Tare: {reel.effective_tare_g == null ? "Unknown" : reel.effective_tare_g + " g"}{reel.measured_tare_g != null ? " (measured)" : " (design default)"} · {reel.filament_spool_id ? "Loaded with filament" : "Unassigned"}</small>
            <small>Condition: {reel.condition || "usable"}{reel.assignment_history?.length ? " · " + reel.assignment_history.length + " recent assignment change(s)" : ""}</small>
            {(reel.assignment_history || []).slice(0, 3).map((event, i) => <small key={i}>{new Date(event.occurred_at).toLocaleDateString()} · {event.previous_spool_code || "Empty"} → {event.new_spool_code || "Empty"}</small>)}
          </div>
          <div className="spoolRowActions">
            {canChange && <button type="button" onClick={() => startReel(reel)}>Edit</button>}
            {canDelete && <button type="button" className="dangerButton" onClick={() => remove("reel", reel)}>Delete</button>}
          </div>
        </article>)}
        {!reels.length && <div className="printingEmptyInline">No reusable spools registered yet. Add a design, then an individual spool.</div>}
      </div>
    </section>
    <section className="panel printingSection">
      <div className="panelHead"><h3>Manufacturer spool catalogue</h3></div>
      <div className="printingList">
        {manufacturerDesigns.map(item => <article className="printingListRow" key={item.key}>
          <div><strong>{item.name}</strong><small>{item.manufacturer} · Manufacturer reference; check actual tare and drying tolerance before use.</small></div>
          {canAddDesign && <button type="button" disabled={working || designs.some(d => d.name === item.name && d.manufacturer === item.manufacturer)} onClick={() => importManufacturerDesign(item)}>
            {designs.some(d => d.name === item.name && d.manufacturer === item.manufacturer) ? "Added to inventory" : "Add to inventory"}
          </button>}
        </article>)}
      </div>
    </section>
    <section className="panel printingSection">
      <div className="panelHead"><h3>Spool designs ({designs.length})</h3></div>
      <div className="printingList">
        {designs.map(d => <article className="printingListRow" key={d.id}>
          <div><strong>{d.name}</strong>
            <small>{[d.manufacturer, d.design_type, d.material].filter(Boolean).join(" · ")}</small>
            <small>Nominal tare: {d.nominal_tare_g == null ? "Unknown" : d.nominal_tare_g + " g"} · Dryer limit: {d.max_dryer_temp_c == null ? "Unverified" : d.max_dryer_temp_c + " °C"}</small>
            
          </div>
          <div className="spoolRowActions">
            {d.model_3d_id && <button type="button" onClick={onOpenModels}>View linked model</button>}
            {canChangeDesign && <button type="button" onClick={() => startDesign(d)}>Edit</button>}
            {canChangeDesign && <button type="button" className="dangerButton" onClick={() => remove("design", d)}>Delete</button>}
          </div>
        </article>)}
        {!designs.length && <div className="printingEmptyInline">No spool designs yet.</div>}
      </div>
    </section>

    {form && <Modal title={editing ? "Edit " + (form === "design" ? "spool design" : "reusable spool") : "Add " + (form === "design" ? "spool design" : "reusable spool")} onClose={() => setForm("")}>
      <form className="formGrid" onSubmit={submit}>
        {error && <div className="formError full" role="alert">{error}</div>}
        {form === "design" ? <>
          {field("Design name", "name")}
          <label>Type<select value={designForm.design_type} onChange={e => setDesignForm(p => ({ ...p, design_type: e.target.value, ...(e.target.value === "printed" ? { manufacturer: "" } : {}) }))}><option value="printed">3D printed</option><option value="manufacturer">Manufacturer-made</option></select></label>
          {designForm.design_type === "manufacturer" && <label>Manufacturer
            <input value={designForm.manufacturer} onChange={e => setDesignForm(p => ({ ...p, manufacturer: e.target.value }))} onBlur={acceptManufacturer} placeholder="Enter manufacturer (e.g. Bambu)" />
            {matchedManufacturer && matchedManufacturer !== designForm.manufacturer && <small className="manufacturerMatchHint">Recognised manufacturer: <button type="button" onClick={acceptManufacturer}>{matchedManufacturer}</button></small>}
          </label>}
          <label>Material
            <select value={designForm.material || ""} onChange={e => { setDesignForm(p => ({ ...p, material: e.target.value })); setDensityProductId(""); }}>
              <option value="">Choose known material</option>
              {materials.map(material => <option key={material} value={material}>{material}</option>)}
            </select>
          </label>
          {designForm.design_type === "printed" && <>
            <label>Density reference (optional)
              <select value={densityProductId} onChange={e => setDensityProductId(e.target.value)}>
                <option value="">Use library material density (automatic)</option>
                {densityProducts.map(p => <option key={p.id} value={p.id}>{p.name} · {p.density_g_cm3} g/cm³</option>)}
              </select>
            </label>
            <div className="full spoolEstimateBlock">
              {estimatedMass ? <><p className="spoolHelpText">Estimated weight at 15% infill: {estimatedMass} g (mesh volume {volume.toFixed(2)} cm³ × {density.toFixed(2)} g/cm³ {sourceProduct ? "selected filament density" : "MakerVault library material median density"}). This is a rough baseline: walls, solid layers and slicer settings affect the real weight. Use a sliced estimate or measured tare when available.</p>
                <div className="spoolInlineActions"><button type="button" onClick={() => setDesignForm(p => ({ ...p, nominal_tare_g: estimatedMass }))}>Use estimated weight</button></div>
              </> : <small>Choose an analysed model and a material with a recorded density in your MakerVault filament library. Without library density data, no weight estimate is shown. Actual empty spool weight should be measured.</small>}
            </div>
          </>}
          {designForm.design_type === "manufacturer" && <div className="full spoolEstimateBlock">
            <p className="spoolHelpText">Only verified catalogue information will be used, and entered values are preserved.</p>
            <div className="spoolInlineActions"><button type="button" onClick={lookupKnownManufacturerSpecs}>Look up specifications</button></div>
          </div>}
          {field("Nominal empty weight (g)", "nominal_tare_g", "number")}
          {field("Maximum verified dryer temperature (°C)", "max_dryer_temp_c", "number")}
          <small className="full">Material alone does not establish a safe dryer limit. Enter a limit only when verified for the exact printed design/material and record its source; otherwise leave blank.</small>
          {field("Temperature rating source", "temperature_source")}
          {field("Design URL", "source_url", "url")}
          {field("Outer diameter (mm)", "outer_diameter_mm", "number")}
          {field("Width (mm)", "width_mm", "number")}
          {designForm.design_type === "printed" && dimensions && <div className="full spoolEstimateBlock">
            <p className="spoolHelpText">Model bounding box: {Number(dimensions.x).toFixed(1)} × {Number(dimensions.y).toFixed(1)} × {Number(dimensions.z).toFixed(1)} mm. These are orientation-dependent, not verified reel dimensions.</p>
            <div className="spoolInlineActions"><button type="button" onClick={() => {
              const d = [dimensions.x, dimensions.y, dimensions.z].map(Number).sort((a,b) => a-b);
              applyGeometryDimension("outer_diameter_mm", d[2]);
              applyGeometryDimension("width_mm", d[0]);
            }}>Use model dimensions</button></div>
          </div>}
          {field("Hub / bore diameter (mm)", "hub_diameter_mm", "number")}
          {field("Capacity (g)", "capacity_g", "number")}
          <label>Description<textarea rows="3" value={designForm.description || ""} onChange={e => setDesignForm(p => ({ ...p, description: e.target.value }))}/></label>
          <label>3D model (STL/3MF in Model Library)<select value={designForm.model_3d_id} onChange={e => { const model = models.find(m => m.id === e.target.value); setDesignForm(p => ({ ...p, model_3d_id: e.target.value, ...(p.design_type === "printed" && model ? { name: model.name, manufacturer: "" } : {}) })); }}><option value="">Not linked</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        </> : <>
          <div className="spoolAutoIdNote">Spool ID: {editing?.code || "Assigned automatically when saved (RSP-0001, RSP-0002…)"}</div>
          <label>Reusable spool design<select required value={reelForm.design_id} onChange={e => setReelForm(p => ({ ...p, design_id: e.target.value }))}>{designs.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
          {field("Measured empty weight (g)", "measured_tare_g", "number")}
          {field("Colour", "color_name")}
          {field("Printed material", "material_override")}
          <label>Condition<select value={reelForm.condition || "usable"} onChange={e => setReelForm(p => ({ ...p, condition: e.target.value }))}><option value="usable">Usable</option><option value="damaged">Damaged</option><option value="retired">Retired</option></select></label>
          <label>Storage location<select value={reelForm.storage_location_id} onChange={e => setReelForm(p => ({ ...p, storage_location_id: e.target.value }))}><option value="">None</option>{locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
          <label>Assigned filament stock<select value={reelForm.filament_spool_id} onChange={e => setReelForm(p => ({ ...p, filament_spool_id: e.target.value }))}><option value="">Unassigned</option>{spools.map(spool => <option key={spool.id} value={spool.id}>{spool.spool_id} · {spool.filament}</option>)}</select></label>
          {field("Notes", "notes")}
        </>}
        <div className="formActions full">
          <button type="button" onClick={() => setForm("")}>Cancel</button>
          <button type="submit" className="primary" disabled={working}>{working ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </Modal>}
  </div>;
}

function FilamentLibraryPage({ filaments, manufacturers, materials, canChangeFilament, canAddFilament, onBack, onChanged, searchTarget = null }) {
  const [query, setQuery] = useState("");
  const [addFilamentOpen, setAddFilamentOpen] = useState(false);

  useEffect(() => {
    if (searchTarget?.type !== "filaments" || !searchTarget.id) return;
    setQuery("");
    const timer = window.setTimeout(() => {
      document.getElementById("filament-search-target-" + searchTarget.id)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [filaments.length, searchTarget?.token, searchTarget?.id]);
  const [detailFilament, setDetailFilament] = useState(null);
  const [editFilament, setEditFilament] = useState(null);
  const [imageFilament, setImageFilament] = useState(null);
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
        {canAddFilament && <button className="primary" type="button" onClick={() => setAddFilamentOpen(true)}>Add to library</button>}
      </div>
    </section>

    <section className="panel printingSection">
      <div className="printingLibraryToolbar">
        <div><strong>{filaments.length} filament product{filaments.length === 1 ? "" : "s"}</strong><small>{rows.length !== filaments.length ? rows.length + " matching" : "Newest updated first"}</small></div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search manufacturer, product, material, colour or source…" />
      </div>
      <div className="printingList">
        {rows.map(item => <article className={"printingListRow printingLibraryRow" + (searchTarget?.id === item.id ? " searchTargetRow" : "")} id={"filament-search-target-" + item.id} key={item.id}>
          {item.image
            ? <img className="filamentLibraryThumb" src={item.image} alt="" loading="lazy" />
            : <span className={"printingSwatch filamentPreview-" + (item.transparency || "opaque")} style={filamentSwatchStyle(item)} />}
          <div>
            <strong>{item.display_name || item.name}</strong>
            <small>{[item.manufacturer, item.material, item.color_name].filter(Boolean).join(" · ")}</small>
            <small>{item.diameter_mm || "?"} mm · {grams(item.nominal_weight_g)} nominal{item.density_g_cm3 ? " · " + item.density_g_cm3 + " g/cm³" : ""} · {item.source || "Manual"}</small>
            {(item.product_url || item.tds_url || item.sds_url) && <small className="filamentSourceLinks">
              {item.product_url && <a href={item.product_url} target="_blank" rel="noreferrer">Product</a>}
              {item.tds_url && <a href={item.tds_url} target="_blank" rel="noreferrer">TDS</a>}
              {item.sds_url && <a href={item.sds_url} target="_blank" rel="noreferrer">SDS</a>}
            </small>}
          </div>
          <div className="printingBadges">
            {item.spool_type && <Badge>{item.spool_type}</Badge>}
            {item.is_refill && <Badge>Refill</Badge>}
            {item.country_of_origin && <Badge>{item.country_of_origin}</Badge>}
            {item.transparency && item.transparency !== "opaque" && <Badge>{item.transparency_label || item.transparency}</Badge>}
            {item.glow && <Badge>Glow</Badge>}
            <button type="button" onClick={() => setDetailFilament(item)}>Details</button>
            {canChangeFilament && <button type="button" onClick={() => setImageFilament(item)}>Image</button>}
            {canChangeFilament && <button type="button" onClick={() => setEditFilament(item)}>Edit</button>}
          </div>
        </article>)}
        {!rows.length && <div className="printingEmptyInline">{term ? "No filament products match this search." : "No saved filament products yet."}</div>}
      </div>
    </section>

    {detailFilament && <FilamentDetailsModal
      filament={detailFilament}
      canChangeFilament={canChangeFilament}
      onChanged={onChanged}
      onClose={() => setDetailFilament(null)}
    />}

    {imageFilament && <ImageManagerModal
      title={"Image — " + (imageFilament.display_name || imageFilament.name)}
      endpoint={"/api/printing/filaments/" + imageFilament.id + "/image/"}
      responseKey="filament"
      currentImage={imageFilament.image}
      onClose={() => setImageFilament(null)}
      onUpdated={async () => { setImageFilament(null); await onChanged(); }}
    />}

    {addFilamentOpen && <FilamentModal manufacturers={manufacturers} materials={materials} onClose={() => setAddFilamentOpen(false)} onSaved={async () => { setAddFilamentOpen(false); await onChanged(); }} />}

    {editFilament && <FilamentEditModal
      filament={editFilament}
      manufacturers={manufacturers}
      materials={materials}
      onClose={() => setEditFilament(null)}
      onSaved={async () => { setEditFilament(null); await onChanged(); }}
    />}
  </div>;
}


function FilamentDetailsModal({ filament, canChangeFilament = false, onChanged, onClose }) {
  const [current, setCurrent] = useState(filament);
  const [matchOpen, setMatchOpen] = useState(false);
  const [unmatching, setUnmatching] = useState(false);
  const [matchError, setMatchError] = useState("");

  useEffect(() => { setCurrent(filament); }, [filament]);

  const temperatureRange = (min, max) => {
    if (min == null && max == null) return "—";
    if (min != null && max != null && Number(min) !== Number(max)) return `${min}–${max} °C`;
    return `${min ?? max} °C`;
  };
  const drying = current.drying_temp_c == null && current.drying_time_hours == null
    ? "—"
    : [
        current.drying_temp_c != null ? current.drying_temp_c + " °C" : "",
        current.drying_time_hours != null ? current.drying_time_hours + " h" : "",
      ].filter(Boolean).join(" · ");

  async function unmatchCatalogue() {
    const restoreText = current.catalogue_match_restorable
      ? "MakerVault will restore the values saved immediately before this catalogue match."
      : "This is an older match without a saved before-state. MakerVault will remove the catalogue link but retain the current descriptive values.";
    if (!window.confirm("Unmatch this filament from the catalogue?\n\n" + restoreText)) return;
    setUnmatching(true);
    setMatchError("");
    try {
      const result = await apiFetch("/api/printing/filaments/" + current.id + "/catalogue-match/", {
        method: "DELETE",
      });
      if (result.item) setCurrent(result.item);
      await onChanged?.();
    } catch (err) {
      setMatchError(err.message);
    } finally {
      setUnmatching(false);
    }
  }

  return <>
    <Modal
      title={current.display_name || current.name}
      subtitle="Saved filament product details used by every physical spool linked to this product."
      onClose={onClose}
      wide
    >
      <div className="filamentCatalogueLayout">
        <div>
          <div className={`filamentCatalogueHero filamentPreview-${current.transparency || "opaque"}`}>
            {current.image
              ? <img src={current.image} alt="" />
              : <div className="filamentNoImage">
                  <span className="printingSwatch" style={filamentSwatchStyle(current)} aria-hidden="true" />
                  <strong>No product image</strong>
                  <small>{current.color_name || current.color_hex || "Colour preview unavailable"}</small>
                </div>}
          </div>
          <div className="badgeRow">
            {current.material && <Badge tone="accent">{current.material}</Badge>}
            {current.color_name && <Badge>{current.color_name}</Badge>}
            {current.transparency && <Badge>{current.transparency_label || current.transparency}</Badge>}
            {current.finish && <Badge>{current.finish}</Badge>}
            {current.pattern && <Badge>{current.pattern}</Badge>}
            {current.glow && <Badge>Glow</Badge>}
            {current.is_refill && <Badge>Refill</Badge>}
          </div>
          {current.image_source_provider && <small className="muted">
            Image: {current.image_source_provider}
            {current.image_license ? " · " + current.image_license : ""}
            {current.image_author ? " · " + current.image_author : ""}
          </small>}
        </div>
        <div>
          <span className="settingsEyebrow">{current.manufacturer || "Filament product"}</span>
          <h3>{current.name}</h3>
          <dl className="detailSpecs">
            <div><dt>Material</dt><dd>{current.material || "—"}</dd></div>
            <div><dt>Colour</dt><dd>{current.color_name || current.color_hex || "—"}</dd></div>
            <div><dt>Diameter</dt><dd>{current.diameter_mm == null ? "—" : current.diameter_mm + " mm"}</dd></div>
            <div><dt>Density</dt><dd>{current.density_g_cm3 == null ? "—" : current.density_g_cm3 + " g/cm³"}</dd></div>
            <div><dt>Nominal weight</dt><dd>{grams(current.nominal_weight_g)}</dd></div>
            <div><dt>Empty spool</dt><dd>{grams(current.empty_spool_weight_g)}</dd></div>
            <div><dt>Nozzle</dt><dd>{temperatureRange(current.nozzle_temp_min_c, current.nozzle_temp_max_c)}</dd></div>
            <div><dt>Bed</dt><dd>{temperatureRange(current.bed_temp_min_c, current.bed_temp_max_c)}</dd></div>
            <div><dt>Drying</dt><dd>{drying}</dd></div>
            <div><dt>Spool type</dt><dd>{current.spool_type || (current.is_refill ? "Refill" : "—")}</dd></div>
            <div><dt>Origin</dt><dd>{current.country_of_origin || "—"}</dd></div>
            <div><dt>Source</dt><dd>{current.source || "Manual"}{current.source_license ? " · " + current.source_license : ""}</dd></div>
          </dl>
          {(current.product_url || current.tds_url || current.sds_url || current.source_url || current.image_source_page) && <div className="filamentCatalogueLinks">
            {current.product_url && <a href={current.product_url} target="_blank" rel="noreferrer">Manufacturer product page</a>}
            {current.tds_url && <a href={current.tds_url} target="_blank" rel="noreferrer">Technical data sheet</a>}
            {current.sds_url && <a href={current.sds_url} target="_blank" rel="noreferrer">Safety data sheet</a>}
            {!current.product_url && current.source_url && <a href={current.source_url} target="_blank" rel="noreferrer">Catalogue source</a>}
            {current.image_source_page && current.image_source_page !== current.product_url && <a href={current.image_source_page} target="_blank" rel="noreferrer">Image source</a>}
          </div>}
          {current.color_hexes?.length > 1 && <div className="settingsCallout">
            <strong>Multi-colour product</strong>
            <p>{current.color_hexes.length} recorded colours{current.multi_color_direction ? " · " + current.multi_color_direction : ""}</p>
          </div>}
          {matchError && <div className="formError">{matchError}</div>}
          {canChangeFilament && <div className="settingsCallout filamentDetailsMatchCallout">
            <strong>{current.catalogue_matched ? "Catalogue match active" : "Missing or incomplete product data?"}</strong>
            <p>{current.catalogue_matched
              ? "You can review a different catalogue match at any time. Unmatching restores the pre-match values when MakerVault has a saved snapshot."
              : "Match this saved filament to the catalogue to fill available manufacturer, technical and provenance data without overwriting your manual corrections."}</p>
            {current.catalogue_external_id && <small>Catalogue ID · {current.catalogue_external_id}</small>}
          </div>}
          <div className="formActions">
            {canChangeFilament && <button className="primary" type="button" disabled={unmatching} onClick={() => setMatchOpen(true)}>{current.catalogue_matched ? "Rematch catalogue" : "Match catalogue"}</button>}
            {canChangeFilament && current.catalogue_matched && <button className="dangerButton" type="button" disabled={unmatching} onClick={unmatchCatalogue}>{unmatching ? "Unmatching…" : "Unmatch catalogue"}</button>}
            <button type="button" onClick={onClose} disabled={unmatching}>Close</button>
          </div>
        </div>
      </div>
    </Modal>
    {matchOpen && <FilamentCatalogueMatchModal
      filament={current}
      onClose={() => setMatchOpen(false)}
      onApplied={async updated => {
        setMatchOpen(false);
        if (updated) setCurrent(updated);
        await onChanged?.();
      }}
    />}
  </>;
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
  const [matchOpen, setMatchOpen] = useState(false);
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
        <strong>Find catalogue data for this filament</strong>
        <p>Search known filament products using the manufacturer, product name, material and colour already entered. You choose the match before MakerVault fills missing catalogue and technical data.</p>
        <button type="button" onClick={() => setMatchOpen(true)}>Match catalogue</button>
      </div>

      <div className="settingsCallout full">
        <strong>Source provenance is preserved</strong>
        <p>{filament.source || "Manual"}{filament.source_type && filament.source_type !== "manual" ? " · " + filament.source_type : ""}. Editing does not discard the original catalogue/source attribution.</p>
        {(filament.product_url || filament.tds_url || filament.sds_url) && <div className="filamentCatalogueLinks">
          {filament.product_url && <a href={filament.product_url} target="_blank" rel="noreferrer">Product page</a>}
          {filament.tds_url && <a href={filament.tds_url} target="_blank" rel="noreferrer">TDS</a>}
          {filament.sds_url && <a href={filament.sds_url} target="_blank" rel="noreferrer">SDS</a>}
        </div>}
      </div>
      <div className="formActions full">
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !form.manufacturer_name || !form.material || !form.name}>{busy ? "Saving…" : "Save filament changes"}</button>
      </div>
    </form>
    {matchOpen && <FilamentCatalogueMatchModal
      filament={filament}
      onClose={() => setMatchOpen(false)}
      onApplied={async () => { setMatchOpen(false); await onSaved(); }}
    />}
  </Modal>;
}


function FilamentCatalogueMatchModal({ filament, onClose, onApplied }) {
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    apiFetch("/api/printing/filaments/" + filament.id + "/catalogue-match/")
      .then(result => {
        if (cancelled) return;
        const candidates = result.candidates || [];
        setRows(candidates);
        setSelected(candidates[0]?.external_id || "");
      })
      .catch(err => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [filament.id]);

  async function applyMatch() {
    if (!selected) return;
    setApplying(true); setError("");
    try {
      const result = await apiFetch("/api/printing/filaments/" + filament.id + "/catalogue-match/", {
        method: "POST",
        body: { external_id: selected },
      });
      await onApplied(result.item || null);
    } catch (err) {
      const fieldMessages = Object.entries(err.fields || {})
        .flatMap(([field, messages]) => (messages || []).map(message => `${field}: ${message}`));
      setError(fieldMessages.length ? err.message + " " + fieldMessages.join(" · ") : err.message);
    } finally {
      setApplying(false);
    }
  }

  return <Modal
    title={"Match catalogue · " + (filament.display_name || filament.name)}
    subtitle="MakerVault ranks likely known products. Review the manufacturer, material, colour and technical data before applying a match."
    onClose={onClose}
    wide
  >
    <div className="formGrid">
      {error && <div className="formError full">{error}</div>}
      {busy && <div className="printingEmptyInline full">Searching the filament catalogue…</div>}
      {!busy && !rows.length && <div className="settingsCallout full"><strong>No confident catalogue candidates found</strong><p>You can keep this filament as a manual record and try again later as the catalogue grows.</p></div>}
      {!busy && rows.length > 0 && <div className="filamentMatchList full" role="radiogroup" aria-label="Catalogue matches">
        {rows.map(row => {
          const active = selected === row.external_id;
          return <label key={row.external_id} className={"filamentMatchCandidate" + (active ? " filamentMatchCandidateSelected" : "")}>
            <input
              className="filamentMatchRadio"
              type="radio"
              name="filament-catalogue-match"
              checked={active}
              onChange={() => setSelected(row.external_id)}
            />
            <span className={"filamentMatchSelectMark" + (active ? " filamentMatchSelectMarkChecked" : "")} aria-hidden="true">{active ? "✓" : ""}</span>
            <span className="printingSwatch" style={filamentSwatchStyle(row)} aria-hidden="true" />
            <span className="filamentMatchMain">
              <strong>{row.manufacturer} · {row.name}</strong>
              <small>{[row.material, row.color_name || row.color_hex, row.diameter_mm ? row.diameter_mm + " mm" : ""].filter(Boolean).join(" · ")}</small>
              <small>
                {row.nozzle_temp_min_c != null ? "Nozzle " + row.nozzle_temp_min_c + (row.nozzle_temp_max_c != null && row.nozzle_temp_max_c !== row.nozzle_temp_min_c ? "–" + row.nozzle_temp_max_c : "") + " °C" : "No nozzle data"}
                {" · "}
                {row.bed_temp_min_c != null ? "Bed " + row.bed_temp_min_c + (row.bed_temp_max_c != null && row.bed_temp_max_c !== row.bed_temp_min_c ? "–" + row.bed_temp_max_c : "") + " °C" : "No bed data"}
              </small>
            </span>
            <span className="printingBadges">
              <Badge tone={row.match_score >= 75 ? "good" : row.match_score >= 50 ? "accent" : undefined}>{row.match_score}% match</Badge>
              {(row.match_reasons || []).slice(0, 3).map(reason => <Badge key={reason}>{reason}</Badge>)}
            </span>
          </label>;
        })}
      </div>}
      <div className="settingsCallout full">
        <strong>Applying a match is conservative</strong>
        <p>MakerVault links the catalogue source and fills missing metadata. Existing manual identity/colour values are retained. Manufacturer product pages and technical data sheets are then checked for higher-authority print temperatures and related technical data where available.</p>
      </div>
      <div className="formActions full">
        <button type="button" onClick={onClose} disabled={applying}>Cancel</button>
        <button type="button" className="primary" disabled={busy || applying || !selected} onClick={applyMatch}>{applying ? "Applying…" : "Apply selected match"}</button>
      </div>
    </div>
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

  return <Modal title="Open filament catalogue" subtitle="Search MakerVault's merged filament catalogue, review the source record, then import it as a normal native MakerVault filament product." onClose={onClose} wide>
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
            {selected.image
              ? <img src={selected.image} alt="" loading="lazy" />
              : <span style={filamentSwatchStyle(selected)} />}
          </div>
          <span className="settingsEyebrow">{selected.source_name || "Catalogue"} preview</span>
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
            <div><dt>Spool type</dt><dd>{selected.spool_type || (selected.is_refill ? "Refill" : "—")}</dd></div>
            <div><dt>Origin</dt><dd>{selected.country_of_origin || "—"}</dd></div>
            <div><dt>Source ID</dt><dd>{selected.external_id}</dd></div>
          </dl>
          {(selected.product_url || selected.tds_url || selected.sds_url) && <div className="filamentCatalogueLinks">
            {selected.product_url && <a href={selected.product_url} target="_blank" rel="noreferrer">Manufacturer product page</a>}
            {selected.tds_url && <a href={selected.tds_url} target="_blank" rel="noreferrer">Technical data sheet</a>}
            {selected.sds_url && <a href={selected.sds_url} target="_blank" rel="noreferrer">Safety data sheet</a>}
          </div>}
          <button className="primary" disabled={importing} onClick={importSelected}>{importing ? "Importing…" : "Import into MakerVault"}</button>
          <p className="muted">The imported record remains editable and usable without its external source. Source provenance is retained separately.</p>
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
        <div className="detectedSpoolColour">
          <span className="printingSwatch" style={slot.color_hex ? { background: slot.color_hex } : undefined} aria-hidden="true" />
          <strong>Detected colour</strong>
          <span>{slot.color_name || slot.color_hex || "Not reported"}</span>
        </div>
        <div className="badgeRow">
          {slot.vendor && <Badge>{slot.vendor}</Badge>}
          {slot.product_name && <Badge tone="accent">{slot.product_name}</Badge>}
          {slot.material && <Badge>{slot.material}</Badge>}
          {slot.color_hex && <Badge>{slot.color_hex}</Badge>}
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
        <div className="full">
          <strong>Choose an unloaded physical spool</strong>
          <small className="detectedSpoolHint">Best material/colour matches are shown first. Each row includes the details that distinguish otherwise identical reels.</small>
        </div>
        <div className="detectedSpoolCandidateList full" role="radiogroup" aria-label="Existing physical spool">
          {candidateSpools.map(spool => {
            const spoolman = (spool.external_links || []).find(link => link.provider === "spoolman");
            const selected = existingSpoolId === spool.id;
            const colourLabel = spool.color_name || spool.color_hex || "Colour not recorded";
            const placement = spool.location || "Unassigned";
            return <label
              key={spool.id}
              className={"detectedSpoolCandidate" + (selected ? " detectedSpoolCandidateSelected" : "")}
            >
              <input
                className="detectedSpoolCandidateRadio"
                type="radio"
                name="existing-spool"
                value={spool.id}
                checked={selected}
                onChange={() => setExistingSpoolId(spool.id)}
              />
              <span className={"detectedSpoolSelectMark" + (selected ? " detectedSpoolSelectMarkChecked" : "")} aria-hidden="true">{selected ? "✓" : ""}</span>
              <span className={"printingSwatch filamentPreview-" + (spool.transparency || "opaque")} style={filamentSwatchStyle(spool)} aria-hidden="true" />
              <span className="detectedSpoolCandidateMain">
                <strong>{spool.spool_id} · {spool.filament}</strong>
                <small>{[spool.manufacturer, spool.material, colourLabel].filter(Boolean).join(" · ")}</small>
                <small>{grams(spool.remaining_weight_g)} remaining · {placement}</small>
              </span>
              <span className="printingBadges detectedSpoolCandidateBadges">
                {selected && <Badge tone="good">Selected</Badge>}
                {spoolman && <Badge tone="accent">Spoolman #{spoolman.external_id}</Badge>}
                {spool.rfid_uid && <Badge>RFID {spool.rfid_uid}</Badge>}
                <Badge>{spool.status_label || spool.status}</Badge>
              </span>
            </label>;
          })}
        </div>
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
    last_dried_at: "",
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
        <label>Last dried<input type="date" value={form.last_dried_at} onChange={e => set("last_dried_at", e.target.value)} /></label>
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
    is_reusable_spool: false,
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
        const created = await apiFetch("/api/printing/models/", { method: "POST", body });
        if (form.is_reusable_spool) await apiFetch("/api/printing/models/" + created.item.id + "/reusable-spool-design/", { method: "POST" });
      } else {
        const created = await apiFetch("/api/printing/models/", { method: "POST", body: form });
        if (form.is_reusable_spool) await apiFetch("/api/printing/models/" + created.item.id + "/reusable-spool-design/", { method: "POST" });
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
      <label className="full"><input type="checkbox" checked={form.is_reusable_spool} onChange={e => set("is_reusable_spool", e.target.checked)} /> Reusable spool design (also add to reusable spool catalogue)</label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? file ? "Uploading…" : "Saving…" : file ? "Upload & add model" : "Add model"}</button></div>
    </form>
  </Modal>;
}


function ModelManageModal({ model, files, printers, canUpload, onClose, onChanged }) {
  const [version, setVersion] = useState("");
  const [revisionNotes, setRevisionNotes] = useState("");
  const [revisionId, setRevisionId] = useState(model.revisions[0]?.id || "");
  const [fileId, setFileId] = useState("");
  const [role, setRole] = useState("model");
  const [primary, setPrimary] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [viewerAsset, setViewerAsset] = useState(null);
  const [versionUploadOpen, setVersionUploadOpen] = useState(false);

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
        <div className="printingManageSectionHead">
          <h3>Revisions</h3>
          {canUpload && <button className="primary" type="button" onClick={() => setVersionUploadOpen(true)}>＋ Upload new version</button>}
        </div>
        <div className="printingRevisionList">
          {model.revisions.map(revision => <article key={revision.id}>
            <div className="printingRevisionHead"><strong>Revision {revision.version}</strong><small>{revision.notes || "No notes"}</small></div>
            <div className="printingRevisionAssets">
              {revision.assets.map(asset => <div key={asset.id}>
                <div><strong>{asset.file.name}</strong><small>{asset.role_label}{asset.is_primary ? " · Primary" : ""} · {asset.file.filename}</small></div>
                <div className="printingRevisionAssetActions">
                  {isViewableModelFile(asset.file) && <button type="button" onClick={() => setViewerAsset(asset)}>View</button>}
                  <a className="assetButton" href={asset.file.url}>Download</a>
                  <button type="button" disabled={busy} onClick={() => detach(revision, asset)}>Detach</button>
                </div>
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
    {viewerAsset && <ModelViewerModal
      model={model}
      printers={printers || []}
      canAnalyse={true}
      initialAssetId={viewerAsset.id}
      onClose={() => setViewerAsset(null)}
      onChanged={onChanged}
    />}
    {versionUploadOpen && <ModelRevisionUploadModal
      model={model}
      onClose={() => setVersionUploadOpen(false)}
      onSaved={async () => {
        setVersionUploadOpen(false);
        await onChanged?.();
      }}
    />}
  </Modal>;
}


function ModelRevisionUploadModal({ model, onClose, onSaved }) {
  const [file, setFile] = useState(null);
  const [version, setVersion] = useState(suggestNextVersion(model.revisions?.[0]?.version || ""));
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (!file || !version.trim()) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("version", version.trim());
      body.append("notes", notes);
      await apiFetch("/api/printing/models/" + model.id + "/revisions/upload/", {
        method: "POST",
        body,
      });
      await onSaved?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal
    title={"Upload new version · " + model.name}
    subtitle="Creates a new immutable model revision and keeps the previous STL/3MF attached to its existing revision."
    onClose={onClose}
    wide
  >
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">STL / 3MF file
        <input type="file" required accept=".stl,.3mf,model/stl,application/vnd.ms-package.3dmanufacturing-3dmodel+xml" onChange={event => setFile(event.target.files?.[0] || null)} />
        <small>{file ? file.name : "Choose the updated printable model or slicer project."}</small>
      </label>
      <label>Revision version<input required value={version} onChange={event => setVersion(event.target.value)} placeholder="e.g. 1.1, rev B" /></label>
      <label className="full">Revision notes<textarea rows="3" value={notes} onChange={event => setNotes(event.target.value)} /></label>
      <div className="formActions full">
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!file || !version.trim() || busy}>{busy ? "Uploading…" : "Upload new version"}</button>
      </div>
    </form>
  </Modal>;
}


function automaticUsageCost(row, spools, currency) {
  if (row.material_cost !== "" && row.material_cost != null) return null;
  const spool = spools.find(item => item.id === row.spool_id);
  if (!spool?.cost_per_g || spool.currency !== currency) return null;
  const gramsTotal = Number(row.used_g || 0) + Number(row.waste_g || 0);
  if (!gramsTotal) return null;
  return gramsTotal * Number(spool.cost_per_g);
}

function PrintJobModal({ gcodeFiles = [], printers, spools, models, projects, currency, onClose, onSaved }) {
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
    gcode_file_id: "",
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
        .filter(row => ["used_g", "waste_g", "material_cost"].some(key => row[key] !== "" && row[key] != null))
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

      <label className="full">Uploaded G-code estimate (optional)<select value={form.gcode_file_id} onChange={e => set("gcode_file_id", e.target.value)}>
        <option value="">No G-code estimate</option>
        {gcodeFiles.map(file => <option key={file.id} value={file.id}>{file.filename}</option>)}
      </select><small>Upload plain .gcode through Files first. Completed prints can use its explicit gram estimate; entered material usage takes precedence. Estimates do not deduct spool stock.</small></label>

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
          <label>Cost
            <input
              type="number"
              min="0"
              step="0.01"
              value={row.material_cost}
              placeholder={automaticUsageCost(row, spools, currency) != null ? formatMoney(automaticUsageCost(row, spools, currency), currency) + " auto" : "Optional"}
              onChange={e => setUsage(index, "material_cost", e.target.value)}
            />
            {automaticUsageCost(row, spools, currency) != null && <small>Auto {formatMoney(automaticUsageCost(row, spools, currency), currency)} from spool purchase cost. Enter a value to override.</small>}
          </label>
          {usages.length > 1 && <button type="button" className="assetDanger" onClick={() => removeUsage(index)}>Remove</button>}
        </div>)}
      </div>

      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      {!printers.length && <div className="formError full">Create a printer before recording print history.</div>}
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !printers.length}>{busy ? "Saving…" : "Add print"}</button></div>
    </form>
  </Modal>;
}


