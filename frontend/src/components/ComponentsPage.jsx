import React, { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { themeQuartz } from "ag-grid-community";
import { apiFetch } from "../api";
import { BoardImage, Modal } from "./Common";

export default function ComponentsPage({ components, setComponents, config, refreshDashboard }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const categories = useMemo(() => [...new Set(components.map(c => c.category).filter(Boolean))].sort(), [components]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return components.filter(c =>
      (!category || c.category === category)
      && (!q || [c.name, c.manufacturer, c.category, c.part_number].join(" ").toLowerCase().includes(q))
    );
  }, [components, query, category]);

  const columns = useMemo(() => [
    { headerName: "", field: "image", width: 72, sortable: false, filter: false, cellRenderer: p => <BoardImage src={p.value} alt={p.data?.name || ""} size="tiny" /> },
    { field: "category", minWidth: 150 },
    { field: "manufacturer", minWidth: 150 },
    { field: "name", headerName: "Component", minWidth: 260, flex: 1 },
    { field: "part_number", headerName: "Part / IC", minWidth: 150 },
    { field: "source", minWidth: 150 },
  ], []);

  return <section className="panel pagePanel">
    <div className="panelHead panelHeadWrap">
      <div><h3>Component catalogue</h3><p>{filtered.length} of {components.length} reusable component definitions</p></div>
      <div className="toolbarActions">
        <input className="searchInput" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search components…" />
        <select value={category} onChange={e => setCategory(e.target.value)}><option value="">All categories</option>{categories.map(x => <option key={x}>{x}</option>)}</select>
        {config?.permissions?.add_component && <button className="primary" onClick={() => setShowAdd(true)}>＋ Add component</button>}
      </div>
    </div>
    <div className="gridWrap">
      <AgGridReact
        theme={themeQuartz}
        rowData={filtered}
        columnDefs={columns}
        defaultColDef={{ filter: true, sortable: true, resizable: true }}
        pagination
        paginationPageSize={50}
        paginationPageSizeSelector={[25, 50, 100]}
        getRowId={p => p.data.id}
      />
    </div>
    {showAdd && <AddComponentModal
      onClose={() => setShowAdd(false)}
      categories={categories}
      onCreated={async c => {
        setComponents(rows => [...rows, c].sort((a, b) => a.name.localeCompare(b.name)));
        setShowAdd(false);
        await refreshDashboard();
      }}
    />}
  </section>;
}

function AddComponentModal({ onClose, onCreated, categories }) {
  const [form, setForm] = useState({ manufacturer: "", category: categories[0] || "", name: "", part_number: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(f => ({ ...f, [key]: value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch("/api/components/", { method: "POST", body: form });
      onCreated(result.component);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add component" subtitle="Create a reusable component definition for BOMs and physical stock." onClose={onClose}>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Manufacturer<input value={form.manufacturer} onChange={e => set("manufacturer", e.target.value)} placeholder="Generic" /></label>
      <label>Category<input list="component-categories" value={form.category} onChange={e => set("category", e.target.value)} /><datalist id="component-categories">{categories.map(x => <option key={x} value={x} />)}</datalist></label>
      <label className="full">Name<input required value={form.name} onChange={e => set("name", e.target.value)} /></label>
      <label>Part / IC<input value={form.part_number} onChange={e => set("part_number", e.target.value)} /></label>
      <label className="full">Description<textarea rows="3" value={form.description} onChange={e => set("description", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Adding…" : "Add component"}</button></div>
    </form>
  </Modal>;
}
