import React from "react";
import StorageSummary from "./StorageSummary";

export default function Dashboard({ dashboard, inventory, onNavigate }) {
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
