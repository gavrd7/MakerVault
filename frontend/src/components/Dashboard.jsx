import { PrinterCameraPreview } from "./PrinterCameras";
import React from "react";
import PrinterJobControls from "./PrinterJobControls";
import StorageSummary from "./StorageSummary";
import { Badge } from "./Common";

function liveStateTone(row) {
  if (row?.stale || ["error", "disconnected"].includes(row?.connection_status) || ["error", "failed"].includes(row?.state)) return "danger";
  if (["printing", "processing", "self-testing", "paused"].includes(row?.state)) return "accent";
  if (["idle", "complete", "completed", "success"].includes(row?.state)) return "good";
  return "neutral";
}

function liveProgress(row) {
  const value = row?.job?.progress;
  if (value == null || Number.isNaN(Number(value))) return null;
  return Math.max(0, Math.min(100, Number(value)));
}

function showLiveProgress(row) {
  const pct = liveProgress(row);
  const state = String(row?.state || "").toLowerCase();
  return pct != null && Boolean(
    row?.job?.file_name
    || pct > 0
    || ["printing", "processing", "paused", "complete", "completed"].includes(state)
  );
}

function liveTemp(temp) {
  if (temp?.actual_c == null) return null;
  return Math.round(Number(temp.actual_c)) + "°";
}

export default function Dashboard({ dashboard, inventory, onNavigate, onOpenLive, onOpenCamera, onOpenProject, onChanged }) {
  const cards = dashboard ? [
    ["Inventory", dashboard.inventory_total, `${dashboard.inventory_available} available · ${dashboard.inventory_in_use} in use`, "Inventory"],
    ["Projects", dashboard.projects_total, `${dashboard.projects_active} active`, "Projects"],
    ["Maker Tags", dashboard.maker_tags || 0, "active physical identities", "Maker Tags"],
    ["Board models", dashboard.board_models, "catalogue records", "Board Catalogue"],
    ["Components", dashboard.component_models, "catalogue records", "Components"],
    ["Filaments / spools", `${dashboard.filament_products} / ${dashboard.spools}`, "products / physical spools", "3D Printing"],
    ["3D", `${dashboard.printers} / ${dashboard.models_3d}`, "printers / models", "3D Printing"],
  ] : [];

  return <>
    <section className="hero">
      <div>
        <span className="eyebrow">Your makerspace, connected</span>
        <h2>Electronics, projects, filament and fabrication in one inventory.</h2>
        <p>MakerVault brings together inventory, projects, files, BOMs, 3D printing, model intelligence and print history in one self-hosted workspace.</p>
      </div>
    </section>
    <section className="cards">
      {cards.map(([label, value, sub, target]) => <button className="metricCard" key={label} onClick={() => onNavigate(target)}>
        <span>{label}</span><strong>{value}</strong><small>{sub}</small>
      </button>)}
    </section>
    {!!dashboard?.project_attention?.length && <section className="panel dashboardProjectAttention">
      <div className="panelHead">
        <div>
          <h3>Projects needing attention</h3>
          <p>{dashboard.projects_deadline_alerts ? `${dashboard.projects_deadline_alerts} deadline alert${dashboard.projects_deadline_alerts === 1 ? "" : "s"} · ` : ""}ranked by deadline urgency and priority.</p>
        </div>
        <button onClick={() => onNavigate("Projects")}>Open projects →</button>
      </div>
      <div className="dashboardProjectAttentionList">
        {dashboard.project_attention.map(project => <button key={project.id} className={`dashboardProjectAttentionRow deadline-${project.deadline_state || "none"}`} onClick={() => onOpenProject?.(project)}>
          <div className="dashboardProjectAttentionMain">
            <strong>{project.name}</strong>
            <small>{project.status_label}</small>
          </div>
          <div className="dashboardProjectAttentionBadges">
            {project.priority != null && <span className={`projectPriority projectPriority-p${project.priority}`}>P{project.priority}</span>}
            {project.due_date && <span className={`projectDeadline projectDeadline-${project.deadline_state || "scheduled"}`}>{project.deadline_label || project.due_date}</span>}
          </div>
        </button>)}
      </div>
    </section>}
    {!!dashboard?.live_printers?.length && <section className="panel dashboardLivePanel">
      <div className="panelHead">
        <div><h3>Live printers</h3><p>Current printer telemetry from configured local/provider sources.</p></div>
        <button onClick={() => onNavigate("3D Printing")}>Open 3D Printing →</button>
      </div>
      <div className="dashboardLiveGrid">
        {dashboard.live_printers.map(printer => {
          const pct = liveProgress(printer);
          const showProgress = showLiveProgress(printer);
          const tone = liveStateTone(printer);
          return <article className={"dashboardLivePrinter dashboardLivePrinter-" + (printer.state || "unknown")} key={printer.id}>
            <div className="dashboardLivePrinterImage">
              {printer.image ? <img src={printer.image} alt="" loading="lazy" /> : <span>3D</span>}
            </div>
            <div className="dashboardLivePrinterMain">
              <div className="dashboardLivePrinterHead">
                <div>
                  <strong>{printer.name}</strong>
                  <small>{[printer.manufacturer, printer.model, printer.location].filter(Boolean).join(" · ")}</small>
                </div>
                <Badge tone={tone}>{printer.stale ? "Stale" : (printer.state_label || printer.connection_status_label)}</Badge>
              </div>
              <div className="dashboardLivePrinterMeta">
                <span>{printer.job?.file_name || printer.adapter_label}</span>
                <span>{[
                  liveTemp(printer.temperatures?.tool0) ? "Nozzle " + liveTemp(printer.temperatures?.tool0) : "",
                  liveTemp(printer.temperatures?.bed) ? "Bed " + liveTemp(printer.temperatures?.bed) : "",
                  liveTemp(printer.temperatures?.chamber) ? "Chamber " + liveTemp(printer.temperatures?.chamber) : "",
                ].filter(Boolean).join(" · ")}</span>
              </div>
              {showProgress && <div className="dashboardLiveProgress"><span style={{ width: pct + "%" }} /></div>}
              {showProgress && <small className="dashboardLiveProgressLabel">{pct.toFixed(pct % 1 ? 1 : 0)}%</small>}
              <div className="printerLiveActions">
                <PrinterJobControls printer={printer} connection={{ id: printer.connection_id, controls: printer.controls, snapshot: { job: printer.job } }} canControl={printer.can_control} onChanged={onChanged} />
                <button type="button" className="printerLiveOpen" onClick={() => onOpenLive(printer)}>Open live</button>
              </div>
              <PrinterCameraPreview printer={printer} />
            </div>
          </article>;
        })}
      </div>
    </section>}
    <StorageSummary />
    <section className="panel">
      <div className="panelHead"><div><h3>Inventory snapshot</h3><p>Most recently loaded records</p></div><button onClick={() => onNavigate("Inventory")}>Open inventory →</button></div>
      <MiniTable rows={inventory.slice(0, 8)} />
    </section>
  </>;
}

function MiniTable({ rows }) {
  return <div className="miniTable">
    <div className="miniHead"><span>ID</span><span>Item</span><span>Status</span><span>Project</span></div>
    {rows.length ? rows.map(r => <div className="miniRow" key={r.id}>
      <span>{r.inventory_id}</span><strong>{r.name}</strong><span>{r.status_label}</span><span>{r.project || "—"}</span>
    </div>) : <div className="noRows">No inventory yet. Open Inventory and add your first board or component.</div>}
  </div>;
}

