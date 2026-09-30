import React, { useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { themeQuartz } from "ag-grid-community";
import { apiFetch } from "../api";
import { Badge, BoardImage, LoadingBlock, Modal } from "./Common";

const STATUS_LABELS = {
  available: "Available",
  in_use: "In use",
  reserved: "Reserved",
  repair: "Needs repair",
  retired: "Retired",
};

function formatDateTime(value) {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
  } catch {
    return value;
  }
}

export default function InventoryPage({ inventory, setInventory, boards, components, projects, config, refreshDashboard, openItemId = "", openToken = null }) {
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
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
      field: "allocated_quantity", headerName: "BOM alloc.", width: 110, editable: false, type: "numericColumn",
      valueFormatter: p => Number(p.value || 0).toFixed(3).replace(/\.000$/, "")
    },
    {
      field: "available_quantity", headerName: "Free", width: 95, editable: false, type: "numericColumn",
      valueFormatter: p => Number(p.value || 0).toFixed(3).replace(/\.000$/, "")
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

  async function loadDetail(item) {
    setSelected(item);
    setLoadingDetail(true);
    try {
      const result = await apiFetch(`/api/inventory/${item.id}/`);
      setSelected(result.item);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoadingDetail(false);
    }
  }

  useEffect(() => {
    if (!openItemId) return;
    const item = inventory.find(row => row.id === openItemId);
    if (item) loadDetail(item);
  }, [openItemId, openToken]);

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
      if (selected?.id === result.item.id) await loadDetail(result.item);
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

  return <div className={`catalogueLayout ${selected ? "hasDetail" : ""}`}>
    <section className="panel pagePanel cataloguePanel">
      <div className="panelHead panelHeadWrap">
        <div><h3>Inventory</h3><p>Click an item for its full record. Total, BOM-allocated and free quantities stay visible while you quick-edit stock details.</p></div>
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
          onRowClicked={event => {
            if (!event.api.getEditingCells().length) loadDetail(event.data);
          }}
          getRowId={params => params.data.id}
        />
      </div>
    </section>
    {selected && <InventoryDetail
      item={selected}
      loading={loadingDetail}
      projects={projects}
      canEdit={editable}
      canDelete={Boolean(config?.permissions?.delete_inventory)}
      onClose={() => setSelected(null)}
      onDeleted={async deleted => {
        setInventory(rows => rows.filter(row => row.id !== deleted.id));
        setSelected(null);
        await refreshDashboard();
      }}
      onChanged={async updated => {
        setInventory(rows => rows.map(row => row.id === updated.id ? updated : row));
        await loadDetail(updated);
        await refreshDashboard();
      }}
    />}
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
        await loadDetail(item);
      }}
    />}
  </div>;
}

function InventoryDetail({ item, loading, projects, canEdit, canDelete, onClose, onChanged, onDeleted }) {
  const [editing, setEditing] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  if (loading) return <aside className="detailPane"><div className="detailHead"><h3>Inventory details</h3><button className="iconButton" onClick={onClose}>×</button></div><LoadingBlock label="Loading inventory record…" /></aside>;

  const board = item.board;
  const component = item.component;
  const model = board || component;

  return <aside className="detailPane inventoryDetailPane">
    <div className="detailHead"><h3>Inventory details</h3><button className="iconButton" onClick={onClose}>×</button></div>
    <BoardImage src={item.image} alt={item.name} size="large" placeholder={item.item_type === "board" ? "MCU" : "PART"} />
    <div className="inventoryDetailIdentity">
      <span className="inventoryCode">{item.inventory_id}</span>
      <h2>{item.name}</h2>
    </div>
    <div className="inventoryDetailActions">
      {canEdit && <button className="primary" onClick={() => setEditing(true)}>Edit</button>}
      {canEdit && Number(item.allocated_quantity || 0) > 0 && <button onClick={() => setReleaseOpen(true)}>Release from allocation</button>}
      {canDelete && <button
        className="assetDanger"
        disabled={deleting || Number(item.allocated_quantity || 0) > 0}
        title={Number(item.allocated_quantity || 0) > 0 ? "Release BOM allocations before deleting this inventory record." : "Delete this inventory record"}
        onClick={async () => {
          if (!window.confirm('Delete "' + item.inventory_id + ' · ' + item.name + '" from inventory? This cannot be undone.')) return;
          setDeleting(true);
          setDeleteError("");
          try {
            await apiFetch("/api/inventory/" + item.id + "/", { method: "DELETE" });
            await onDeleted(item);
          } catch (error) {
            setDeleteError(error.message);
          } finally {
            setDeleting(false);
          }
        }}
      >{deleting ? "Deleting…" : "Delete"}</button>}
    </div>
    {deleteError && <div className="inlineError">{deleteError}</div>}
    {canDelete && Number(item.allocated_quantity || 0) > 0 && <div className="inventoryDeleteHint">Release this item's BOM allocations before deleting it.</div>}
    <div className="badgeRow">
      <Badge tone={item.status === "available" ? "good" : item.status === "in_use" ? "accent" : "neutral"}>{item.status_label}</Badge>
      <Badge>{item.type}</Badge>
      {item.project && <Badge tone="accent">{item.project}</Badge>}
    </div>

    <dl className="specList inventorySpecList">
      <div><dt>Total quantity</dt><dd>{item.quantity}</dd></div>
      <div><dt>BOM allocated</dt><dd>{item.allocated_quantity ?? 0}</dd></div>
      <div><dt>Free quantity</dt><dd>{item.available_quantity ?? item.quantity}</dd></div>
      <div><dt>Location</dt><dd>{item.location || "—"}</dd></div>
      <div><dt>Project</dt><dd>{item.project || "—"}</dd></div>
      <div><dt>Serial / ID</dt><dd>{item.serial_number || "—"}</dd></div>
      <div><dt>Purchase cost</dt><dd>{item.purchase_price == null ? "—" : `${item.currency} ${Number(item.purchase_price).toFixed(2)}`}</dd></div>
      <div><dt>Purchased</dt><dd>{item.purchased_on || "—"}</dd></div>
      <div><dt>Supplier</dt><dd>{item.supplier || "—"}</dd></div>
      <div><dt>Updated</dt><dd>{formatDateTime(item.updated_at)}</dd></div>
    </dl>

    {item.notes && <section className="detailSection"><h4>Notes</h4><p className="muted detailNotes">{item.notes}</p></section>}

    {model && <section className="detailSection">
      <h4>Catalogue model</h4>
      <div className="catalogueSummary">
        <strong>{board?.display_name || component?.name}</strong>
        <span>{board ? [board.mcu, board.architecture].filter(Boolean).join(" · ") : [component?.category, component?.part_number].filter(Boolean).join(" · ")}</span>
      </div>
    </section>}

    <section className="detailSection">
      <h4>Lifecycle history</h4>
      <div className="historyTimeline">
        {item.history?.length ? item.history.map(entry => <div className="historyEntry" key={entry.id}>
          <span className={`historyDot history-${entry.event_type}`} />
          <div><strong>{entry.summary}</strong><small>{formatDateTime(entry.created_at)}{entry.changed_by ? ` · ${entry.changed_by}` : ""}</small></div>
        </div>) : <p className="muted">No history recorded yet. Changes made from v0.3 onward will appear here.</p>}
      </div>
    </section>

    {item.purchase_url && <a className="detailLink" href={item.purchase_url} target="_blank" rel="noreferrer">Open purchase/source URL ↗</a>}

    {editing && <EditInventoryModal item={item} projects={projects} onClose={() => setEditing(false)} onSaved={updated => { setEditing(false); onChanged(updated); }} />}
    {releaseOpen && <ReleaseBomAllocationModal
      item={item}
      onClose={() => setReleaseOpen(false)}
      onReleased={async () => {
        const result = await apiFetch("/api/inventory/" + item.id + "/");
        setReleaseOpen(false);
        await onChanged(result.item);
      }}
    />}
  </aside>;
}

function ReleaseBomAllocationModal({ item, onClose, onReleased }) {
  const allocations = item.bom_allocations || [];
  const [allocationId, setAllocationId] = useState(allocations[0]?.id ? String(allocations[0].id) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = allocations.find(row => String(row.id) === allocationId);

  async function release(event) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await apiFetch(
        "/api/projects/" + selected.project_id + "/bom/" + selected.bom_item_id + "/allocations/" + selected.id + "/",
        { method: "DELETE" },
      );
      await onReleased();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal
    title={"Release " + item.inventory_id + " from BOM"}
    subtitle="Choose the project and BOM line to release. Only that allocation will be removed."
    onClose={onClose}
    wide
  >
    <form className="formGrid" onSubmit={release}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">Project / BOM allocation
        <select required value={allocationId} onChange={e => setAllocationId(e.target.value)}>
          {allocations.map(allocation => <option key={allocation.id} value={allocation.id}>
            {allocation.project_name + " · " + allocation.bom_item_name + " · " + allocation.quantity + " " + allocation.unit}
          </option>)}
        </select>
      </label>
      {selected && <div className="bomDerivedInventory full">
        <span>Selected allocation</span>
        <strong>{selected.project_name}</strong>
        <small>{selected.bom_item_name + " · " + selected.quantity + " " + selected.unit}</small>
      </div>}
      <div className="formActions full">
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="assetDanger" disabled={busy || !selected}>{busy ? "Releasing…" : "Release from BOM"}</button>
      </div>
    </form>
  </Modal>;
}

function EditInventoryModal({ item, projects, onClose, onSaved }) {
  const [form, setForm] = useState({
    custom_name: item.custom_name || "",
    quantity: item.quantity ?? 1,
    status: item.status || "available",
    project_id: item.project_id || "",
    location: item.location || "",
    serial_number: item.serial_number || "",
    purchase_price: item.purchase_price ?? "",
    currency: item.currency || "GBP",
    supplier: item.supplier || "",
    purchase_url: item.purchase_url || "",
    purchased_on: item.purchased_on || "",
    notes: item.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const result = await apiFetch(`/api/inventory/${item.id}/`, { method: "PATCH", body: form });
      onSaved(result.item);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={`Edit ${item.inventory_id}`} subtitle="Changes to project, status and location are recorded in the lifecycle history." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">Custom name<input value={form.custom_name} onChange={e => set("custom_name", e.target.value)} placeholder={item.name} /></label>
      <label>Quantity<input type="number" min={item.allocated_quantity || 0} step="0.001" value={form.quantity} onChange={e => set("quantity", e.target.value)} /></label>
      <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Project<select value={form.project_id} onChange={e => set("project_id", e.target.value)}><option value="">None</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <label>Location<input value={form.location} onChange={e => set("location", e.target.value)} /></label>
      <label>Serial / unique ID<input value={form.serial_number} onChange={e => set("serial_number", e.target.value)} /></label>
      <label>Purchase date<input type="date" value={form.purchased_on} onChange={e => set("purchased_on", e.target.value)} /></label>
      <label>Purchase price<input type="number" step="0.01" value={form.purchase_price} onChange={e => set("purchase_price", e.target.value)} /></label>
      <label>Currency<input maxLength="3" value={form.currency} onChange={e => set("currency", e.target.value.toUpperCase())} /></label>
      <label>Supplier<input value={form.supplier} onChange={e => set("supplier", e.target.value)} /></label>
      <label className="full">Purchase/source URL<input type="url" value={form.purchase_url} onChange={e => set("purchase_url", e.target.value)} /></label>
      <label className="full">Notes<textarea rows="5" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button></div>
    </form>
  </Modal>;
}

export function AddInventoryModal({
  boards,
  components,
  projects,
  config,
  onClose,
  onCreated,
  initialItemType = "board",
  initialBoard = null,
  initialComponent = null,
  lockCatalogueItem = false,
  title = "Add inventory item",
}) {
  const initialType = initialBoard ? "board" : initialComponent ? "component" : initialItemType;
  const [form, setForm] = useState({
    item_type: initialType,
    board_id: initialBoard?.id || boards[0]?.id || "",
    component_id: initialComponent?.id || components[0]?.id || "",
    quantity: 1, status: "available", project_id: "", location: "", purchase_price: "",
    supplier: "", custom_name: "", inventory_id: "", serial_number: "", purchase_url: "", notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const payload = { ...form, currency: config?.currency || "GBP" };
      if (form.item_type !== "board") payload.board_id = "";
      if (form.item_type !== "component") payload.component_id = "";
      const result = await apiFetch("/api/inventory/", { method: "POST", body: payload });
      onCreated(result.item);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return <Modal title={title} subtitle="Inventory IDs are generated automatically when left blank." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Type<select value={form.item_type} disabled={lockCatalogueItem} onChange={e => set("item_type", e.target.value)}>
        <option value="board">Microcontroller / board</option><option value="component">Component</option><option value="tool">Tool / asset</option><option value="printed_part">Printed part</option><option value="other">Other</option>
      </select></label>
      <label>Inventory ID<input value={form.inventory_id} placeholder="Auto (e.g. MCU-0001)" onChange={e => set("inventory_id", e.target.value)} /></label>
      {form.item_type === "board" && <label className="full">Board<select required disabled={lockCatalogueItem && Boolean(initialBoard)} value={form.board_id} onChange={e => set("board_id", e.target.value)}><option value="">Choose a board…</option>{boards.map(b => <option key={b.id} value={b.id}>{b.display_name}</option>)}</select></label>}
      {form.item_type === "component" && <label className="full">Component<select required disabled={lockCatalogueItem && Boolean(initialComponent)} value={form.component_id} onChange={e => set("component_id", e.target.value)}><option value="">Choose a component…</option>{components.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
      {!["board", "component"].includes(form.item_type) && <label className="full">Name<input required value={form.custom_name} onChange={e => set("custom_name", e.target.value)} /></label>}
      <label>Quantity<input type="number" min="0" step="0.001" value={form.quantity} onChange={e => set("quantity", e.target.value)} /></label>
      <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Project<select value={form.project_id} onChange={e => set("project_id", e.target.value)}><option value="">None</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <label>Location<input value={form.location} onChange={e => set("location", e.target.value)} placeholder="Drawer, shelf, box…" /></label>
      <label>Serial / unique ID<input value={form.serial_number} onChange={e => set("serial_number", e.target.value)} /></label>
      <label>Purchase cost<input type="number" step="0.01" value={form.purchase_price} onChange={e => set("purchase_price", e.target.value)} /></label>
      <label>Supplier<input value={form.supplier} onChange={e => set("supplier", e.target.value)} /></label>
      <label className="full">Purchase/source URL<input type="url" value={form.purchase_url} onChange={e => set("purchase_url", e.target.value)} /></label>
      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Adding…" : "Add to inventory"}</button></div>
    </form>
  </Modal>;
}
