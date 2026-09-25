import React, { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { themeQuartz } from "ag-grid-community";
import { apiFetch } from "../api";
import { BoardImage, Modal } from "./Common";

const STATUS_LABELS = {
  available: "Available",
  in_use: "In use",
  reserved: "Reserved",
  repair: "Needs repair",
  retired: "Retired",
};

export default function InventoryPage({ inventory, setInventory, boards, components, projects, config, refreshDashboard }) {
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [message, setMessage] = useState("");
  const [savingCell, setSavingCell] = useState("");

  const projectMap = useMemo(() => Object.fromEntries(projects.map(p => [p.id, p.name])), [projects]);
  const editable = Boolean(config?.permissions?.change_inventory);

  const columns = useMemo(() => [
    {
      headerName: "", field: "image", width: 72, sortable: false, filter: false, editable: false,
      cellRenderer: p => <BoardImage src={p.value} alt={p.data?.name || ""} size="tiny" />
    },
    { field: "inventory_id", headerName: "Inventory ID", pinned: "left", minWidth: 145, editable: false },
    { field: "name", headerName: "Item", minWidth: 230, editable: false },
    { field: "type", headerName: "Type", minWidth: 115, editable: false },
    {
      field: "quantity", headerName: "Qty", width: 95, editable, type: "numericColumn",
      valueParser: p => Number(p.newValue)
    },
    {
      field: "status", headerName: "Status", minWidth: 135, editable,
      cellEditor: "agSelectCellEditor", cellEditorParams: { values: Object.keys(STATUS_LABELS) },
      valueFormatter: p => STATUS_LABELS[p.value] || p.value
    },
    {
      field: "project_id", headerName: "Project", minWidth: 180, editable,
      cellEditor: "agSelectCellEditor", cellEditorParams: { values: ["", ...projects.map(p => p.id)] },
      valueFormatter: p => projectMap[p.value] || ""
    },
    { field: "location", headerName: "Location", minWidth: 165, editable },
    {
      field: "purchase_price", headerName: "Cost", width: 120, editable, type: "numericColumn",
      valueParser: p => p.newValue === "" ? null : Number(p.newValue),
      valueFormatter: p => p.value == null ? "" : `${p.data.currency || config?.currency || "GBP"} ${Number(p.value).toFixed(2)}`
    },
    { field: "supplier", headerName: "Supplier", minWidth: 160, editable },
  ], [config, editable, projectMap, projects]);

  async function updateCell(event) {
    if (!editable || event.newValue === event.oldValue) return;
    const field = event.colDef.field;
    if (!["quantity", "status", "project_id", "location", "purchase_price", "supplier"].includes(field)) return;
    setSavingCell(`${event.data.id}:${field}`);
    setMessage("");
    try {
      const result = await apiFetch(`/api/inventory/${event.data.id}/`, {
        method: "PATCH",
        body: { [field]: event.newValue },
      });
      setInventory(rows => rows.map(row => row.id === result.item.id ? result.item : row));
      await refreshDashboard();
    } catch (error) {
      event.data[field] = event.oldValue;
      setInventory(rows => rows.map(row => row.id === event.data.id ? { ...row, [field]: event.oldValue } : row));
      setMessage(error.message);
      event.api.refreshCells({ force: true });
    } finally {
      setSavingCell("");
    }
  }

  return <section className="panel pagePanel">
    <div className="panelHead panelHeadWrap">
      <div><h3>Inventory</h3><p>Edit quantity, status, project, location and cost directly in the grid.</p></div>
      <div className="toolbarActions">
        <input className="searchInput" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search inventory…" />
        {config?.permissions?.add_inventory && <button className="primary" onClick={() => setShowAdd(true)}>＋ Add item</button>}
      </div>
    </div>
    {message && <div className="inlineError">{message}</div>}
    {savingCell && <div className="saveStrip">Saving change…</div>}
    <div className="gridWrap">
      <AgGridReact
        theme={themeQuartz}
        rowData={inventory}
        columnDefs={columns}
        quickFilterText={search}
        defaultColDef={{ filter: true, sortable: true, resizable: true }}
        pagination
        paginationPageSize={50}
        paginationPageSizeSelector={[25, 50, 100]}
        stopEditingWhenCellsLoseFocus
        onCellValueChanged={updateCell}
        getRowId={params => params.data.id}
      />
    </div>
    {showAdd && <AddInventoryModal
      boards={boards}
      components={components}
      projects={projects}
      config={config}
      onClose={() => setShowAdd(false)}
      onCreated={async item => {
        setInventory(rows => [...rows, item]);
        setShowAdd(false);
        await refreshDashboard();
      }}
    />}
  </section>;
}

function AddInventoryModal({ boards, components, projects, config, onClose, onCreated }) {
  const [form, setForm] = useState({
    item_type: "board",
    board_id: boards[0]?.id || "",
    component_id: components[0]?.id || "",
    quantity: 1,
    status: "available",
    project_id: "",
    location: "",
    purchase_price: "",
    supplier: "",
    custom_name: "",
    inventory_id: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = { ...form, currency: config?.currency || "GBP" };
      if (form.item_type !== "board") payload.board_id = "";
      if (form.item_type !== "component") payload.component_id = "";
      const result = await apiFetch("/api/inventory/", { method: "POST", body: payload });
      onCreated(result.item);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add inventory item" subtitle="Inventory IDs are generated automatically when left blank." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Type<select value={form.item_type} onChange={e => set("item_type", e.target.value)}>
        <option value="board">Microcontroller / board</option>
        <option value="component">Component</option>
        <option value="tool">Tool / asset</option>
        <option value="printed_part">Printed part</option>
        <option value="other">Other</option>
      </select></label>
      <label>Inventory ID<input value={form.inventory_id} placeholder="Auto (e.g. MCU-0001)" onChange={e => set("inventory_id", e.target.value)} /></label>
      {form.item_type === "board" && <label className="full">Board<select required value={form.board_id} onChange={e => set("board_id", e.target.value)}>
        <option value="">Choose a board…</option>
        {boards.map(b => <option key={b.id} value={b.id}>{b.display_name}</option>)}
      </select></label>}
      {form.item_type === "component" && <label className="full">Component<select required value={form.component_id} onChange={e => set("component_id", e.target.value)}>
        <option value="">Choose a component…</option>
        {components.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select></label>}
      {!["board", "component"].includes(form.item_type) && <label className="full">Name<input required value={form.custom_name} onChange={e => set("custom_name", e.target.value)} /></label>}
      <label>Quantity<input type="number" min="0" step="0.001" value={form.quantity} onChange={e => set("quantity", e.target.value)} /></label>
      <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Project<select value={form.project_id} onChange={e => set("project_id", e.target.value)}><option value="">None</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <label>Location<input value={form.location} onChange={e => set("location", e.target.value)} placeholder="Drawer, shelf, box…" /></label>
      <label>Purchase cost<input type="number" step="0.01" value={form.purchase_price} onChange={e => set("purchase_price", e.target.value)} /></label>
      <label>Supplier<input value={form.supplier} onChange={e => set("supplier", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Adding…" : "Add to inventory"}</button></div>
    </form>
  </Modal>;
}
