import React, { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { themeQuartz } from "ag-grid-community";
import { apiFetch } from "../api";
import { Badge, BoardImage, ImageManagerModal, LoadingBlock, Modal } from "./Common";

function prettySpecKey(key) {
  const labels = {
    clock_mhz: "Clock",
    cpu_cores: "CPU cores",
    sram_kb: "SRAM",
    adc_channels: "ADC channels",
    dac_channels: "DAC channels",
    uart_count: "UART",
    spi_count: "SPI",
    i2c_count: "I²C",
    pwm_channels: "PWM channels",
    pin_count: "Pins",
    operating_voltage: "Operating voltage",
    native_usb: "Native USB",
  };
  return labels[key] || key.replaceAll("_", " ").replace(/\b\w/g, char => char.toUpperCase());
}

function prettySpecValue(key, value) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  if (key === "clock_mhz" && value !== "") return `${value} MHz`;
  if (key === "sram_kb" && value !== "") return `${value} KB`;
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "—");
}

export default function BoardsPage({ boards, setBoards, config, onOpenImport, refreshDashboard }) {
  const [query, setQuery] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [family, setFamily] = useState("");
  const [selected, setSelected] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  const manufacturers = useMemo(() => [...new Set(boards.map(b => b.manufacturer).filter(Boolean))].sort(), [boards]);
  const families = useMemo(() => [...new Set(boards.map(b => b.family).filter(Boolean))].sort(), [boards]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return boards.filter(board =>
      (!manufacturer || board.manufacturer === manufacturer)
      && (!family || board.family === family)
      && (!q || [board.name, board.manufacturer, board.family, board.mcu, board.variant].join(" ").toLowerCase().includes(q))
    );
  }, [boards, query, manufacturer, family]);

  const columns = useMemo(() => [
    { headerName: "", field: "image", width: 72, sortable: false, filter: false, cellRenderer: p => <BoardImage src={p.value} alt={p.data?.name || ""} size="tiny" /> },
    { field: "manufacturer", minWidth: 150 },
    { field: "name", headerName: "Board", minWidth: 230, flex: 1 },
    { field: "family", minWidth: 125 },
    { field: "mcu", headerName: "MCU", minWidth: 135 },
    { field: "flash_mb", headerName: "Flash", width: 105, valueFormatter: p => p.value == null ? "" : `${p.value} MB` },
    { headerName: "Wireless", minWidth: 190, valueGetter: p => [p.data.wifi && "Wi-Fi", p.data.bluetooth && "BT", p.data.zigbee && "Zigbee", p.data.thread && "Thread"].filter(Boolean).join(" · ") },
    { field: "source", minWidth: 145 },
  ], []);

  async function chooseBoard(board) {
    setSelected(board);
    setLoadingDetail(true);
    try {
      const result = await apiFetch(`/api/boards/${board.id}/`);
      setSelected(result.board);
    } finally {
      setLoadingDetail(false);
    }
  }

  return <div className={`catalogueLayout ${selected ? "hasDetail" : ""}`}>
    <section className="panel pagePanel cataloguePanel">
      <div className="panelHead panelHeadWrap">
        <div><h3>Board catalogue</h3><p>{filtered.length} of {boards.length} board models</p></div>
        <div className="toolbarActions">
          <input className="searchInput" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search boards…" />
          <select value={manufacturer} onChange={e => setManufacturer(e.target.value)}><option value="">All manufacturers</option>{manufacturers.map(x => <option key={x}>{x}</option>)}</select>
          <select value={family} onChange={e => setFamily(e.target.value)}><option value="">All families</option>{families.map(x => <option key={x}>{x}</option>)}</select>
          {config?.permissions?.add_board && <>
            <button onClick={() => setShowAdd(true)}>＋ Manual</button>
            <button className="primary" onClick={onOpenImport}>＋ Import URL</button>
          </>}
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
          onRowClicked={e => chooseBoard(e.data)}
          getRowId={p => p.data.id}
        />
      </div>
    </section>
    {selected && <BoardDetail
      board={selected}
      loading={loadingDetail}
      canEdit={config?.permissions?.change_board}
      onClose={() => setSelected(null)}
      onChanged={updated => {
        setBoards(rows => rows.map(row => row.id === updated.id ? updated : row));
        setSelected(updated);
      }}
    />}
    {showAdd && <AddBoardModal onClose={() => setShowAdd(false)} onCreated={async board => {
      setBoards(rows => [...rows, board].sort((a, b) => a.display_name.localeCompare(b.display_name)));
      setShowAdd(false);
      setSelected(board);
      await refreshDashboard();
    }} />}
  </div>;
}

function BoardDetail({ board, loading, canEdit, onClose, onChanged }) {
  const [imageOpen, setImageOpen] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichMessage, setEnrichMessage] = useState("");
  const radios = [[board.wifi, "Wi-Fi"], [board.bluetooth, "Bluetooth"], [board.zigbee, "Zigbee"], [board.thread, "Thread"]]
    .filter(([on]) => on).map(([, label]) => label);

  const hiddenSpecKeys = new Set([
    "external_image_url", "image_source_url", "image_source_page", "image_source_provider",
    "image_source_query", "image_source_type", "image_license", "image_author", "image_cached_at",
    "auto_image_seeded", "auto_image_seeded_at", "auto_image_last_attempt", "auto_image_opt_out",
    "starter_catalogue", "catalogue_version", "source_url", "imported_from",
    "technical_source_url", "technical_source_provider", "technical_enriched_at",
    "datasheet_url", "pinout_url",
  ]);
  const technicalSpecs = Object.entries(board.specifications || {})
    .filter(([key, value]) => !hiddenSpecKeys.has(key) && value !== null && value !== "" && value !== undefined);

  async function enrichBoard() {
    setEnriching(true); setEnrichMessage("");
    try {
      const result = await apiFetch(`/api/boards/${board.id}/enrich/`, { method: "POST" });
      onChanged(result.board);
      setEnrichMessage(result.changed ? "Technical specifications updated from ESPBoards.dev." : "No additional matching ESPBoards data was found.");
    } catch (error) {
      setEnrichMessage(error.message);
    } finally {
      setEnriching(false);
    }
  }

  return <aside className="detailPane boardDetailPane">
    <div className="detailHead"><h3>Board details</h3><button className="iconButton" onClick={onClose}>×</button></div>
    {loading ? <LoadingBlock label="Loading board details…" /> : <>
      <BoardImage src={board.image} alt={board.display_name} size="large" />
      <div className="detailTitleRow">
        <h2>{board.display_name}</h2>
        <div className="detailActions">
          {canEdit && <button onClick={() => setImageOpen(true)}>Image</button>}
          {canEdit && /ESP32|ESP8266/i.test([board.family, board.mcu, board.name].join(" ")) && <button onClick={enrichBoard} disabled={enriching}>{enriching ? "Refreshing…" : "Refresh specs"}</button>}
        </div>
      </div>
      <p className="muted">{board.description || `${board.family || "Development board"}${board.mcu ? ` · ${board.mcu}` : ""}`}</p>
      {enrichMessage && <div className="detailNotice">{enrichMessage}</div>}
      <div className="badgeRow">{radios.map(x => <Badge key={x} tone="accent">{x}</Badge>)}{board.usb_connector && <Badge>{board.usb_connector}</Badge>}</div>

      <h4>Core specifications</h4>
      <dl className="specList">
        <div><dt>MCU</dt><dd>{board.mcu || "—"}</dd></div><div><dt>Architecture</dt><dd>{board.architecture || "—"}</dd></div>
        <div><dt>Flash</dt><dd>{board.flash_mb == null ? "—" : `${board.flash_mb} MB`}</dd></div><div><dt>PSRAM</dt><dd>{board.psram_mb == null ? "—" : `${board.psram_mb} MB`}</dd></div>
        <div><dt>RAM / SRAM</dt><dd>{board.ram_kb == null ? (board.specifications?.sram_kb == null ? "—" : `${board.specifications.sram_kb} KB`) : `${board.ram_kb} KB`}</dd></div><div><dt>GPIO</dt><dd>{board.gpio_count ?? "—"}</dd></div>
        <div><dt>USB</dt><dd>{board.usb_connector || "—"}</dd></div><div><dt>Dimensions</dt><dd>{board.dimensions_mm?.length && board.dimensions_mm?.width ? `${board.dimensions_mm.length} × ${board.dimensions_mm.width} mm` : "—"}</dd></div>
      </dl>

      <h4>Technical details</h4>
      {technicalSpecs.length ? <dl className="detailSpecs">{technicalSpecs.map(([key, value]) => <div key={key}><dt>{prettySpecKey(key)}</dt><dd>{prettySpecValue(key, value)}</dd></div>)}</dl> : <p className="muted">No extended technical data has been populated yet.</p>}

      <h4>Compatibility</h4>
      <div className="compatList">{board.compatibility?.length ? board.compatibility.map(item => <div key={item.platform}><strong>{item.platform}</strong><Badge tone={item.support_level === "full" ? "good" : "neutral"}>{item.support_label}</Badge></div>) : <span className="muted">No compatibility records yet.</span>}</div>

      <div className="boardLinks">
        {board.specifications?.datasheet_url && <a className="detailLink" href={board.specifications.datasheet_url} target="_blank" rel="noreferrer">Datasheet ↗</a>}
        {board.specifications?.pinout_url && <a className="detailLink" href={board.specifications.pinout_url} target="_blank" rel="noreferrer">Pinout ↗</a>}
        {board.specifications?.technical_source_url && <a className="detailLink" href={board.specifications.technical_source_url} target="_blank" rel="noreferrer">Technical source ↗</a>}
      </div>
      {(board.image_source_page || board.image_source_url) && <p className="provenance"><span>{board.image_source_provider ? `Image: ${board.image_source_provider}${board.image_license ? ` · ${board.image_license}` : ""}` : "Image source"}</span><a href={board.image_source_page || board.image_source_url} target="_blank" rel="noreferrer">Open source ↗</a></p>}
    </>}
    {imageOpen && <ImageManagerModal
      title={`Image — ${board.display_name}`}
      endpoint={`/api/boards/${board.id}/image/`}
      responseKey="board"
      currentImage={board.image}
      onClose={() => setImageOpen(false)}
      onUpdated={updated => { onChanged(updated); setImageOpen(false); }}
    />}
  </aside>;
}

function AddBoardModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    manufacturer: "", name: "", family: "", mcu: "", architecture: "", flash_mb: "",
    psram_mb: "", gpio_count: "", usb_connector: "", wifi: false, bluetooth: false,
    zigbee: false, thread: false
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key, value) => setForm(v => ({ ...v, [key]: value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch("/api/boards/", { method: "POST", body: form });
      onCreated(result.board);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Add board model" subtitle="Create a catalogue entry manually. You can add a physical unit to Inventory afterwards." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Manufacturer<input value={form.manufacturer} onChange={e => set("manufacturer", e.target.value)} placeholder="Generic" /></label>
      <label>Board name<input required value={form.name} onChange={e => set("name", e.target.value)} /></label>
      <label>Family<input value={form.family} onChange={e => set("family", e.target.value)} placeholder="ESP32-S3, RP2040…" /></label>
      <label>MCU<input value={form.mcu} onChange={e => set("mcu", e.target.value)} /></label>
      <label>Architecture<input value={form.architecture} onChange={e => set("architecture", e.target.value)} /></label>
      <label>USB<input value={form.usb_connector} onChange={e => set("usb_connector", e.target.value)} placeholder="USB-C" /></label>
      <label>Flash (MB)<input type="number" step="0.01" value={form.flash_mb} onChange={e => set("flash_mb", e.target.value)} /></label>
      <label>PSRAM (MB)<input type="number" step="0.01" value={form.psram_mb} onChange={e => set("psram_mb", e.target.value)} /></label>
      <label>GPIO count<input type="number" value={form.gpio_count} onChange={e => set("gpio_count", e.target.value)} /></label>
      <div className="checkRow full">{["wifi", "bluetooth", "zigbee", "thread"].map(key => <label key={key}><input type="checkbox" checked={form[key]} onChange={e => set(key, e.target.checked)} /> {key === "wifi" ? "Wi-Fi" : key[0].toUpperCase() + key.slice(1)}</label>)}</div>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Adding…" : "Add board"}</button></div>
    </form>
  </Modal>;
}

export function ImportBoardModal({ onClose, onImported }) {
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function previewUrl(e) {
    e?.preventDefault();
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const result = await apiFetch("/api/import/board/preview/", { method: "POST", body: { url } });
      setPreview(result.preview);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch("/api/import/board/commit/", { method: "POST", body: { url } });
      onImported(result.board, result.created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="Import board from URL" subtitle="MakerVault securely supports ESPBoards.dev. More source adapters will plug into the same workflow." onClose={onClose} wide>
    <form className="importForm" onSubmit={previewUrl}>
      <input type="url" required value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.espboards.dev/esp32/…" />
      <button className="primary" disabled={busy}>{busy ? "Reading…" : "Preview"}</button>
    </form>
    {error && <div className="formError">{error}</div>}
    {preview && <div className="importPreview">
      <BoardImage src={preview.image_url} alt={preview.name} size="large" />
      <div className="importSummary"><span className="eyebrow">Detected board</span><h3>{preview.manufacturer} {preview.name}</h3><p>{preview.description}</p>
        <div className="previewSpecs">
          <span><b>MCU</b>{preview.mcu || "—"}</span><span><b>Flash</b>{preview.flash_mb == null ? "—" : `${preview.flash_mb} MB`}</span>
          <span><b>GPIO</b>{preview.gpio_count ?? "—"}</span><span><b>USB</b>{preview.usb_connector || "—"}</span>
        </div>
        <div className="badgeRow">{preview.wifi && <Badge tone="accent">Wi-Fi</Badge>}{preview.bluetooth && <Badge tone="accent">Bluetooth</Badge>}{preview.zigbee && <Badge tone="accent">Zigbee</Badge>}{preview.thread && <Badge tone="accent">Thread</Badge>}</div>
      </div>
    </div>}
    {preview && <div className="formActions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="button" onClick={commit} disabled={busy}>{busy ? "Importing…" : "Import into catalogue"}</button></div>}
  </Modal>;
}
