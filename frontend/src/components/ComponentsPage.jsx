import React, { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { themeQuartz } from "ag-grid-community";
import { apiFetch } from "../api";
import { Badge, BoardImage, ImageManagerModal, LoadingBlock, Modal } from "./Common";

function prettyKey(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
}

function prettyValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value ?? "");
}

export default function ComponentsPage({ components, setComponents, config, refreshDashboard }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const categories = useMemo(() => [...new Set(components.map(c => c.category).filter(Boolean))].sort(), [components]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return components.filter(c =>
      (!category || c.category === category)
      && (!q || [c.name, c.manufacturer, c.category, c.part_number, c.type, c.interface].join(" ").toLowerCase().includes(q))
    );
  }, [components, query, category]);

  const columns = useMemo(() => [
    { headerName: "", field: "image", width: 72, sortable: false, filter: false, cellRenderer: p => <BoardImage src={p.value} alt={p.data?.name || ""} size="tiny" placeholder="PART" /> },
    { field: "category", minWidth: 155 },
    { field: "manufacturer", minWidth: 145 },
    { field: "name", headerName: "Component", minWidth: 255, flex: 1 },
    { field: "part_number", headerName: "Part / IC", minWidth: 135 },
    { field: "type", headerName: "Type", minWidth: 130 },
    { field: "interface", headerName: "Interface", minWidth: 125 },
    { field: "voltage", headerName: "Voltage / input", minWidth: 130 },
  ], []);

  async function chooseComponent(component) {
    setSelected(component);
    setLoadingDetail(true);
    try {
      const result = await apiFetch(`/api/components/${component.id}/`);
      setSelected(result.component);
    } finally {
      setLoadingDetail(false);
    }
  }

  function replaceComponent(updated) {
    setComponents(rows => rows.map(row => row.id === updated.id ? updated : row));
    setSelected(updated);
  }

  return <div className={`catalogueLayout ${selected ? "hasDetail" : ""}`}>
    <section className="panel pagePanel cataloguePanel">
      <div className="panelHead panelHeadWrap">
        <div><h3>Component catalogue</h3><p>{filtered.length} of {components.length} reusable component definitions across {categories.length} categories</p></div>
        <div className="toolbarActions">
          <input className="searchInput" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search components, ICs, interfaces…" />
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
          onRowClicked={e => chooseComponent(e.data)}
        />
      </div>
    </section>
    {selected && <ComponentDetail
      component={selected}
      loading={loadingDetail}
      canEdit={config?.permissions?.change_component}
      onClose={() => setSelected(null)}
      onChanged={replaceComponent}
    />}
    {showAdd && <AddComponentModal
      onClose={() => setShowAdd(false)}
      categories={categories}
      onCreated={async c => {
        setComponents(rows => [...rows, c].sort((a, b) => a.name.localeCompare(b.name)));
        setShowAdd(false);
        setSelected(c);
        await refreshDashboard();
      }}
    />}
  </div>;
}

function ComponentDetail({ component, loading, canEdit, onClose, onChanged }) {
  const [imageOpen, setImageOpen] = useState(false);
  const specs = Object.entries(component.specifications || {})
    .filter(([key]) => !["starter_catalogue", "catalogue_version", "external_image_url", "image_source_url", "image_source_type", "image_cached_at", "image_source_provider", "image_source_page", "image_source_query", "image_license", "image_author", "auto_image_seeded", "auto_image_seeded_at", "auto_image_last_attempt", "auto_image_opt_out"].includes(key));

  return <aside className="detailPane">
    <div className="detailHead"><h3>Component details</h3><button className="iconButton" onClick={onClose}>×</button></div>
    {loading ? <LoadingBlock label="Loading component details…" /> : <>
      <BoardImage src={component.image} alt={component.name} size="large" placeholder="PART" />
      <div className="detailTitleRow"><div><h2>{component.name}</h2><p className="muted detailMaker">{component.manufacturer} · {component.category}</p></div>{canEdit && <button onClick={() => setImageOpen(true)}>Image</button>}</div>
      <p className="muted">{component.description || "Reusable makerspace component definition."}</p>
      <div className="badgeRow">
        {component.type && <Badge tone="accent">{component.type}</Badge>}
        {component.interface && <Badge>{component.interface}</Badge>}
        {component.part_number && <Badge>{component.part_number}</Badge>}
        {component.image_cached && <Badge tone="good">Image cached</Badge>}
      </div>
      <dl className="specList">
        <div><dt>Manufacturer</dt><dd>{component.manufacturer}</dd></div>
        <div><dt>Part / IC</dt><dd>{component.part_number || "—"}</dd></div>
        <div><dt>Category</dt><dd>{component.category}</dd></div>
        <div><dt>Source</dt><dd>{component.source_url ? <a href={component.source_url} target="_blank" rel="noreferrer">{component.source} ↗</a> : component.source}</dd></div>
      </dl>
      <h4>Specifications</h4>
      {specs.length ? <dl className="detailSpecs">{specs.map(([key, value]) => <div key={key}><dt>{prettyKey(key)}</dt><dd>{prettyValue(value)}</dd></div>)}</dl> : <p className="muted">No structured specifications yet.</p>}
      {(component.image_source_page || component.image_source_url) && <p className="provenance"><span>{component.image_source_provider ? `Image: ${component.image_source_provider}${component.image_license ? ` · ${component.image_license}` : ""}` : "Image source"}</span><a href={component.image_source_page || component.image_source_url} target="_blank" rel="noreferrer">Open source ↗</a></p>}
    </>}
    {imageOpen && <ImageManagerModal
      title={`Image — ${component.name}`}
      endpoint={`/api/components/${component.id}/image/`}
      responseKey="component"
      currentImage={component.image}
      onClose={() => setImageOpen(false)}
      onUpdated={updated => { onChanged(updated); setImageOpen(false); }}
    />}
  </aside>;
}

function AddComponentModal({ onClose, onCreated, categories }) {
  const [form, setForm] = useState({
    manufacturer: "", category: categories[0] || "", name: "", part_number: "", description: "",
    type: "", interface: "", voltage: "", package: ""
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(f => ({ ...f, [key]: value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const specifications = Object.fromEntries(
        [["type", form.type], ["interface", form.interface], ["voltage", form.voltage], ["package", form.package]]
          .filter(([, value]) => value.trim())
      );
      const result = await apiFetch("/api/components/", {
        method: "POST",
        body: {
          manufacturer: form.manufacturer,
          category: form.category,
          name: form.name,
          part_number: form.part_number,
          description: form.description,
          specifications,
        }
      });
      onCreated(result.component);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add component" subtitle="Create a reusable component definition for BOMs and physical stock." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Manufacturer<input value={form.manufacturer} onChange={e => set("manufacturer", e.target.value)} placeholder="Generic" /></label>
      <label>Category<input list="component-categories" value={form.category} onChange={e => set("category", e.target.value)} /><datalist id="component-categories">{categories.map(x => <option key={x} value={x} />)}</datalist></label>
      <label className="full">Name<input required value={form.name} onChange={e => set("name", e.target.value)} /></label>
      <label>Part / IC<input value={form.part_number} onChange={e => set("part_number", e.target.value)} /></label>
      <label>Type<input value={form.type} onChange={e => set("type", e.target.value)} placeholder="sensor, relay, connector…" /></label>
      <label>Interface<input value={form.interface} onChange={e => set("interface", e.target.value)} placeholder="I2C, SPI, UART…" /></label>
      <label>Voltage / input<input value={form.voltage} onChange={e => set("voltage", e.target.value)} placeholder="3.3-5 V" /></label>
      <label>Package / form<input value={form.package} onChange={e => set("package", e.target.value)} placeholder="module, TO-92, 5 mm…" /></label>
      <label className="full">Description<textarea rows="3" value={form.description} onChange={e => set("description", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Adding…" : "Add component"}</button></div>
    </form>
  </Modal>;
}
