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
  const canAddPrintJob = Boolean(config?.permissions?.add_printjob);
  const canAddLocation = Boolean(config?.permissions?.add_printing_location);

  return <div className="printingStack">
    <section className="panel printingHero">
      <div>
        <span className="settingsEyebrow">v0.6.0 foundation</span>
        <h2>3D Printing &amp; Model Library</h2>
        <p>Native MakerVault models, printers and spool inventory stay authoritative. External services and printer filament systems plug into this data rather than replacing it.</p>
      </div>
      <div className="printingHeroActions">
        {canAddPrinter && <button onClick={() => setModal("printer")}>＋ Printer</button>}
        {canAddLocation && <button onClick={() => setModal("location")}>＋ Location</button>}
        {canAddFilament && <button onClick={() => setModal("filament")}>＋ Filament</button>}
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

    <section className="panel printingSection">
      <div className="panelHead"><div><h3>Printers &amp; loaded filament</h3><p>Filament slots are provider-neutral so CFS, AMS and later systems can use the same model.</p></div></div>
      <div className="printingCards">
        {(data?.printers || []).map(printer => <article className="printingCard" key={printer.id}>
          <div className="printingCardHead">
            <div><strong>{printer.name}</strong><small>{[printer.manufacturer, printer.model, printer.location].filter(Boolean).join(" · ")}</small></div>
            <div className="printingBadges">{printer.is_active ? <Badge tone="good">Active</Badge> : <Badge>Inactive</Badge>}{printer.catalogue?.multi_material_label && <Badge>{printer.catalogue.multi_material_label}</Badge>}<Badge>{printer.slots.length} slots</Badge></div>
          </div>
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
            <span className={`printingSwatch filamentPreview-${spool.transparency || "opaque"}`} style={filamentSwatchStyle(spool)} />
            <div><strong>{spool.spool_id} · {spool.filament}</strong><small>{spool.material} · {grams(spool.remaining_weight_g)} remaining{spool.location ? " · " + spool.location : ""}</small></div>
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

    {modal === "printer" && <PrinterModal manufacturers={data?.printer_manufacturers || []} models={data?.printer_catalogue_models || []} locations={data?.locations || []} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "location" && <LocationModal onClose={() => setModal("")} onSaved={saved} />}
    {modal === "filament" && <FilamentModal manufacturers={data?.filament_manufacturers || []} materials={data?.common_filament_materials || []} onClose={() => setModal("")} onSaved={saved} />}
    {modal === "filamentCatalogue" && <FilamentCatalogueModal onClose={() => setModal("")} onImported={saved} />}
    {modal === "spool" && <SpoolModal filaments={data?.filaments || []} locations={data?.locations || []} printers={data?.printers || []} currency={config?.currency || "GBP"} onClose={() => setModal("")} onSaved={saved} />}
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
    {manageModel && <ModelManageModal
      model={manageModel}
      files={data?.model_files || []}
      onClose={() => setManageModel(null)}
      onChanged={async () => { setManageModel(null); await load(); }}
    />}
  </div>;
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
    build_volume_x_mm: "",
    build_volume_y_mm: "",
    build_volume_z_mm: "",
    nozzle_mm: "0.4",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(value0 => ({ ...value0, [key]: value }));

  const modelOptions = models.filter(item => item.manufacturer_id === form.printer_manufacturer_id);
  const selectedModel = models.find(item => item.id === form.catalog_model_id);

  function manufacturerChanged(value) {
    setForm(current => ({
      ...current,
      printer_manufacturer_id: value,
      catalog_model_id: "",
      model: "",
      build_volume_x_mm: "",
      build_volume_y_mm: "",
      build_volume_z_mm: "",
      nozzle_mm: "0.4",
    }));
  }

  function modelChanged(value) {
    if (value === "__custom__") {
      setForm(current => ({
        ...current,
        catalog_model_id: "",
        model: "",
        build_volume_x_mm: "",
        build_volume_y_mm: "",
        build_volume_z_mm: "",
        nozzle_mm: "0.4",
      }));
      return;
    }
    const selected = models.find(item => item.id === value);
    if (!selected) return;
    setForm(current => ({
      ...current,
      catalog_model_id: selected.id,
      model: selected.name,
      name: current.name || selected.name,
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
      <label>Model<select required={!!form.printer_manufacturer_id} value={form.catalog_model_id || (form.model ? "__custom__" : "")} onChange={e => modelChanged(e.target.value)} disabled={!form.printer_manufacturer_id}>
        <option value="">Choose model…</option>
        {modelOptions.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
        <option value="__custom__">Other / custom model</option>
      </select></label>
      {!form.catalog_model_id && form.printer_manufacturer_id && <label>Custom model<input required value={form.model} onChange={e => set("model", e.target.value)} placeholder="Printer model" /></label>}
      <label>Printer name<input required value={form.name} onChange={e => set("name", e.target.value)} placeholder={selectedModel ? selectedModel.display_name : "Desk printer"} /></label>
      <label>Serial number<input value={form.serial_number} onChange={e => set("serial_number", e.target.value)} /></label>
      <label>Location<select value={form.location_id} onChange={e => set("location_id", e.target.value)}><option value="">Unassigned</option>{locations.map(x => <option key={x.id} value={x.id}>{x.name} · {x.kind_label}</option>)}</select></label>
      <label>Local host / IP<input value={form.connection_host} onChange={e => set("connection_host", e.target.value)} placeholder="192.168.1.34" /><small>Used by optional local printer/CFS adapters.</small></label>
      <label>Nozzle (mm)<input type="number" min="0.1" step="0.05" value={form.nozzle_mm} onChange={e => set("nozzle_mm", e.target.value)} /></label>
      <label>Build X (mm)<input type="number" min="1" step="0.1" value={form.build_volume_x_mm} onChange={e => set("build_volume_x_mm", e.target.value)} /></label>
      <label>Build Y (mm)<input type="number" min="1" step="0.1" value={form.build_volume_y_mm} onChange={e => set("build_volume_y_mm", e.target.value)} /></label>
      <label>Build Z (mm)<input type="number" min="1" step="0.1" value={form.build_volume_z_mm} onChange={e => set("build_volume_z_mm", e.target.value)} /></label>
      <label className="settingsToggle full"><div><strong>Currently in use</strong><small>Inactive printers remain in your owned-printer catalogue and print history.</small></div><input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} /></label>
      {selectedModel && <div className="settingsCallout full"><strong>Catalogue profile</strong><p>{selectedModel.build_volume?.x || "?"} × {selectedModel.build_volume?.y || "?"} × {selectedModel.build_volume?.z || "?"} mm · {selectedModel.enclosed ? "Enclosed" : "Open"}{selectedModel.multi_material_label ? " · " + selectedModel.multi_material_label : ""}</p></div>}
      <label className="full">Notes<textarea rows="3" value={form.notes} onChange={e => set("notes", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !form.printer_manufacturer_id}>{busy ? "Saving…" : "Add printer"}</button></div>
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

function FilamentModal({ manufacturers, onClose, onSaved }) {
  const [form, setForm] = useState({ manufacturer_id: "", name: "", material: "PLA", color_name: "", color_hex: "#777777", transparency: "opaque", diameter_mm: "1.75", nominal_weight_g: "1000" });
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
      <label>Colour name<input value={form.color_name} onChange={e => set("color_name", e.target.value)} placeholder="Manufacturer colour name" /></label>
      <label>Appearance<select value={form.transparency} onChange={e => set("transparency", e.target.value)}><option value="opaque">Opaque</option><option value="translucent">Translucent</option><option value="transparent">Transparent</option></select></label>
      <div className="full filamentColourField">
        <span>Colour palette</span>
        <div className="filamentPalette" role="group" aria-label="Filament colour palette">
          {FILAMENT_COLOUR_PALETTE.map(([name, hex]) => <button
            key={hex}
            type="button"
            className={form.color_hex.toLowerCase() === hex ? "selected" : ""}
            title={name}
            aria-label={name}
            onClick={() => setForm(value => ({ ...value, color_hex: hex, color_name: value.color_name || name }))}
          ><span style={{ background: hex }} /></button>)}
        </div>
      </div>
      <label>Custom colour<div className="filamentCustomColour"><input type="color" value={form.color_hex || "#777777"} onChange={e => set("color_hex", e.target.value)} /><input value={form.color_hex} onChange={e => set("color_hex", e.target.value)} maxLength="9" placeholder="#RRGGBB" /></div></label>
      <label>Preview<div className={`filamentPreview filamentPreview-${form.transparency}`}><span style={{ background: form.color_hex || "#777777" }} /><strong>{form.color_name || "Selected colour"}</strong><small>{form.transparency}</small></div></label>
      <label>Diameter (mm)<input type="number" step="0.01" min="0.1" value={form.diameter_mm} onChange={e => set("diameter_mm", e.target.value)} /></label>
      <label>Nominal weight (g)<input type="number" step="1" min="0" value={form.nominal_weight_g} onChange={e => set("nominal_weight_g", e.target.value)} /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Add filament"}</button></div>
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
