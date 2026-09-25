import React, { useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);

const NAV = ["Dashboard", "Inventory", "Projects", "Components", "3D Printing", "Files"];

function App() {
  const [section, setSection] = useState("Dashboard");
  const [dashboard, setDashboard] = useState(null);
  const [inventory, setInventory] = useState([]);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      fetch("/api/dashboard/", { credentials: "same-origin" }).then(r => r.ok ? r.json() : Promise.reject(r)),
      fetch("/api/inventory/", { credentials: "same-origin" }).then(r => r.ok ? r.json() : Promise.reject(r)),
      fetch("/api/config/", { credentials: "same-origin" }).then(r => r.ok ? r.json() : Promise.reject(r)),
    ]).then(([d, i, c]) => { setDashboard(d); setInventory(i.rows || []); setConfig(c); })
      .catch(() => setError("MakerVault could not load its initial data."));
  }, []);

  const columns = useMemo(() => [
    { field: "inventory_id", headerName: "Inventory ID", pinned: "left", minWidth: 145 },
    { field: "name", headerName: "Item", minWidth: 220 },
    { field: "type", headerName: "Type", minWidth: 120 },
    { field: "quantity", headerName: "Qty", width: 95, type: "numericColumn" },
    { field: "status", headerName: "Status", minWidth: 130 },
    { field: "project", headerName: "Project", minWidth: 170 },
    { field: "location", headerName: "Location", minWidth: 160 },
    { field: "purchase_price", headerName: "Cost", width: 110,
      valueFormatter: p => p.value == null ? "" : `${p.data.currency || config?.currency || "GBP"} ${Number(p.value).toFixed(2)}` },
  ], [config]);

  const cards = dashboard ? [
    ["Inventory", dashboard.inventory_total, `${dashboard.inventory_available} available · ${dashboard.inventory_in_use} in use`],
    ["Projects", dashboard.projects_total, `${dashboard.projects_active} active`],
    ["Board models", dashboard.board_models, "catalogue records"],
    ["Components", dashboard.component_models, "catalogue records"],
    ["Filaments / spools", `${dashboard.filament_products} / ${dashboard.spools}`, "products / physical spools"],
    ["3D", `${dashboard.printers} / ${dashboard.models_3d}`, "printers / models"],
  ] : [];

  return <div className="shell">
    <aside>
      <div className="brand"><span className="brandmark">M</span><div><strong>MakerVault</strong><small>v0.1 foundation</small></div></div>
      <nav>{NAV.map(n => <button key={n} className={section === n ? "active" : ""} onClick={() => setSection(n)}>{n}</button>)}</nav>
      <div className="asideBottom">
        <a href="/admin/">Administration</a>
        <a href="/accounts/2fa/">Security / MFA</a>
        <a href="/accounts/logout/">Sign out</a>
      </div>
    </aside>
    <main>
      <header><div><h1>{section}</h1><p>{config ? `${config.user} · ${config.timezone} · ${config.currency}` : "Loading MakerVault…"}</p></div><button className="primary" disabled title="URL importer arrives in v0.2">＋ Import URL</button></header>
      {error && <div className="error">{error}</div>}
      {section === "Dashboard" && <>
        <section className="hero"><div><span className="eyebrow">Your makerspace, connected</span><h2>Electronics, projects, filament and fabrication in one inventory.</h2><p>The v0.1 foundation is running. Add records in Administration now; richer project and importer workflows will layer onto this schema.</p></div></section>
        <section className="cards">{cards.map(([label, value, sub]) => <article key={label}><span>{label}</span><strong>{value}</strong><small>{sub}</small></article>)}</section>
        <section className="panel"><div className="panelHead"><div><h3>Inventory snapshot</h3><p>First 2,000 records</p></div><button onClick={() => setSection("Inventory")}>Open inventory →</button></div><MiniTable rows={inventory.slice(0, 8)} /></section>
      </>}
      {section === "Inventory" && <section className="panel inventoryPanel"><div className="panelHead"><div><h3>Inventory</h3><p>Filter, sort and rearrange columns. Inline persistence is the next UI step.</p></div><a className="buttonLink" href="/admin/core/inventoryitem/add/">＋ Add item</a></div><div className="gridWrap"><AgGridReact theme={themeQuartz} rowData={inventory} columnDefs={columns} defaultColDef={{ filter: true, sortable: true, resizable: true }} pagination paginationPageSize={50} /></div></section>}
      {!["Dashboard", "Inventory"].includes(section) && <section className="empty"><div className="emptyIcon">◇</div><h2>{section} schema is ready</h2><p>This module already has database models in v0.1. Its dedicated React workflow is part of the next interface milestone; records can be managed now through the Django administration panel.</p><a className="buttonLink" href="/admin/">Open Administration</a></section>}
    </main>
  </div>;
}

function MiniTable({ rows }) {
  return <div className="miniTable"><div className="miniHead"><span>ID</span><span>Item</span><span>Status</span><span>Project</span></div>{rows.length ? rows.map(r => <div className="miniRow" key={r.id}><span>{r.inventory_id}</span><strong>{r.name}</strong><span>{r.status}</span><span>{r.project || "—"}</span></div>) : <div className="noRows">No inventory yet. Add your first board in Administration.</div>}</div>;
}

export default App;
