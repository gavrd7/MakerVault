import React, { useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { themeQuartz } from "ag-grid-community";
import { apiFetch } from "../api";
import { Badge, BoardImage, ImageManagerModal, ImageViewer, LoadingBlock, Modal } from "./Common";
import { AddInventoryModal } from "./InventoryPage";

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


function formatMemoryMb(value) {
  if (value == null || value === "") return "";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (number < 1) return `${Math.round(number * 1024)} KB`;
  return Number.isInteger(number) ? `${number} MB` : `${number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")} MB`;
}

function BoardSpecGrid({ rows, status = {} }) {
  return <dl className="boardSpecGrid">
    {rows.map(({ key, label, value }) => {
      const fieldStatus = status[key] || (value === null || value === undefined || value === "" ? "unknown" : "value");
      const display = fieldStatus === "not_applicable"
        ? "N/A"
        : (fieldStatus === "unknown" ? "" : value);
      return <div className={`boardSpecCell spec-${fieldStatus}`} key={key} title={fieldStatus === "unknown" ? "Missing data — eligible for enrichment" : undefined}>
        <dt>{label}</dt>
        <dd>{display}</dd>
      </div>;
    })}
  </dl>;
}

export default function BoardsPage({ boards, setBoards, components, projects, config, onOpenImport, refreshDashboard, onInventoryCreated, openBoardId = "", openToken = null }) {
  const [query, setQuery] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [family, setFamily] = useState("");
  const [boardType, setBoardType] = useState("");
  const [selected, setSelected] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  const manufacturers = useMemo(() => [...new Set(boards.map(b => b.manufacturer).filter(Boolean))].sort(), [boards]);
  const families = useMemo(() => [...new Set(boards.map(b => b.family).filter(Boolean))].sort(), [boards]);
  const boardTypes = useMemo(() => [...new Set(boards.map(b => b.board_type || b.specifications?.board_type).filter(Boolean))].sort(), [boards]);
  const boardTypeLabel = value => ({ microcontroller: "Microcontroller", sbc: "Single-board computer", compute_module: "Compute module / SoM" }[value] || value);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return boards.filter(board =>
      (!manufacturer || board.manufacturer === manufacturer)
      && (!family || board.family === family)
      && (!boardType || (board.board_type || board.specifications?.board_type) === boardType)
      && (!q || [board.name, board.manufacturer, board.family, board.mcu, board.variant].join(" ").toLowerCase().includes(q))
    );
  }, [boards, query, manufacturer, family, boardType]);

  const columns = useMemo(() => [
    { headerName: "", field: "image", width: 72, sortable: false, filter: false, cellRenderer: p => <BoardImage src={p.value} alt={p.data?.name || ""} size="tiny" /> },
    { field: "manufacturer", minWidth: 150 },
    { field: "name", headerName: "Board", minWidth: 230, flex: 1 },
    { headerName: "Type", minWidth: 155, valueGetter: p => boardTypeLabel(p.data?.board_type || p.data?.specifications?.board_type || "microcontroller") },
    { field: "family", minWidth: 125 },
    { field: "mcu", headerName: "Processor / MCU", minWidth: 155 },
    { field: "flash_mb", headerName: "Flash", width: 105, valueFormatter: p => formatMemoryMb(p.value) },
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

  useEffect(() => {
    if (!openBoardId) return;
    const board = boards.find(row => row.id === openBoardId);
    if (board) chooseBoard(board);
  }, [openBoardId, openToken]);

  return <div className={`catalogueLayout boardsCatalogueLayout ${selected ? "hasDetail" : ""}`}>
    <section className="panel pagePanel cataloguePanel">
      <div className="panelHead panelHeadWrap">
        <div><h3>Board catalogue</h3><p>{filtered.length} of {boards.length} board models</p></div>
        <div className="toolbarActions">
          <input className="searchInput" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search boards…" />
          <select value={manufacturer} onChange={e => setManufacturer(e.target.value)}><option value="">All manufacturers</option>{manufacturers.map(x => <option key={x}>{x}</option>)}</select>
          <select value={boardType} onChange={e => setBoardType(e.target.value)}><option value="">All board types</option>{boardTypes.map(x => <option key={x} value={x}>{boardTypeLabel(x)}</option>)}</select>
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
      canAddInventory={config?.permissions?.add_inventory}
      boards={boards}
      components={components}
      projects={projects}
      config={config}
      onInventoryCreated={onInventoryCreated}
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

function BoardDetail({ board, loading, canEdit, canAddInventory, boards, components, projects, config, onInventoryCreated, onClose, onChanged }) {
  const [imageOpen, setImageOpen] = useState(false);
  const [inventoryOpen, setInventoryOpen] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichMessage, setEnrichMessage] = useState("");
  const radios = [[board.wifi, "Wi-Fi"], [board.bluetooth, "Bluetooth"], [board.zigbee, "Zigbee"], [board.thread, "Thread"]]
    .filter(([on]) => on).map(([, label]) => label);

  const specs = board.specifications || {};
  const boardTypeLabel = ({ microcontroller: "Microcontroller", sbc: "Single-board computer", compute_module: "Compute module / SoM" }[specs.board_type] || specs.board_type || "Microcontroller");
  const fieldStatus = specs.technical_field_status || {};
  const coreRows = [
    { key: "mcu", label: "MCU", value: board.mcu || "" },
    { key: "architecture", label: "Architecture", value: board.architecture || "" },
    { key: "flash", label: "Flash", value: specs.flash_kb != null ? `${specs.flash_kb} KB` : formatMemoryMb(board.flash_mb) },
    { key: "psram", label: "PSRAM", value: board.psram_mb == null ? "" : `${board.psram_mb} MB` },
    { key: "ram", label: "RAM / SRAM", value: board.ram_kb == null ? (specs.sram_kb == null ? "" : `${specs.sram_kb} KB`) : `${board.ram_kb} KB` },
    { key: "gpio", label: "GPIO", value: board.gpio_count ?? "" },
    { key: "usb", label: "USB connector", value: board.usb_connector || "" },
    { key: "dimensions", label: "Dimensions", value: board.dimensions_mm?.length && board.dimensions_mm?.width ? `${board.dimensions_mm.length} × ${board.dimensions_mm.width} mm` : "" },
  ];
  const technicalRows = [
    { key: "clock_mhz", label: "Clock", value: specs.clock_mhz == null ? "" : `${specs.clock_mhz} MHz` },
    { key: "eeprom_kb", label: "EEPROM", value: specs.eeprom_kb == null ? "" : `${specs.eeprom_kb} KB` },
    { key: "cpu_cores", label: "CPU cores", value: specs.cpu_cores ?? "" },
    { key: "operating_voltage", label: "Operating voltage", value: specs.operating_voltage || "" },
    { key: "pin_count", label: "Pin count", value: specs.pin_count ?? "" },
    { key: "adc_channels", label: "ADC channels", value: specs.adc_channels ?? "" },
    { key: "dac_channels", label: "DAC channels", value: specs.dac_channels ?? "" },
    { key: "uart_count", label: "UART", value: specs.uart_count ?? "" },
    { key: "spi_count", label: "SPI", value: specs.spi_count ?? "" },
    { key: "i2c_count", label: "I²C", value: specs.i2c_count ?? "" },
    { key: "pwm_channels", label: "PWM channels", value: specs.pwm_channels ?? "" },
    { key: "native_usb", label: "Native USB", value: specs.native_usb === true ? "Yes" : specs.native_usb === false ? "No" : "" },
    { key: "usb_capability", label: "USB capability", value: specs.usb_otg === true ? "USB OTG" : specs.usb_serial_jtag === true ? "USB Serial/JTAG" : "" },
    { key: "wifi_standard", label: "Wi-Fi standard", value: specs.wifi_standard || "" },
    { key: "bluetooth_generation", label: "Bluetooth", value: specs.bluetooth_generation || "" },
    { key: "ieee_802154", label: "802.15.4", value: specs.ieee_802154 === true ? "Yes" : specs.ieee_802154 === false ? "No" : "" },
    { key: "pio_state_machines", label: "PIO state machines", value: specs.pio_state_machines ?? "" },
    { key: "wireless", label: "Wireless", value: radios.length ? radios.join(" · ") : "" },
  ];

  async function enrichBoard() {
    setEnriching(true); setEnrichMessage("");
    try {
      const result = await apiFetch(`/api/boards/${board.id}/enrich/`, { method: "POST" });
      onChanged(result.board);
      setEnrichMessage(result.changed ? "Technical specifications and enrichment status were updated." : "No additional source data was found. Missing fields remain queued for future enrichment.");
    } catch (error) {
      setEnrichMessage(error.message);
    } finally {
      setEnriching(false);
    }
  }

  return <>
    <div className="boardDetailBackdrop" onClick={onClose} aria-hidden="true" />
    <aside className="detailPane boardDetailPane">
      <div className="detailHead boardDetailHead"><h3>Board details</h3><button className="iconButton" onClick={onClose} aria-label="Close board details">×</button></div>
      <div className="boardDetailScroll">
      {loading ? <LoadingBlock label="Loading board details…" /> : <>
      <button type="button" className="boardHeroImage imageViewerTrigger" onClick={() => board.image && setViewerOpen(true)} disabled={!board.image} title={board.image ? "Open image viewer" : undefined}><BoardImage src={board.image} alt={board.display_name} size="large" /></button>
      <div className="detailTitleRow boardTitleRow">
        <h2>{board.display_name}</h2>
        <div className="detailActions">
          {canAddInventory && <button className="primary" onClick={() => setInventoryOpen(true)}>＋ Add to inventory</button>}
          {canEdit && <button onClick={() => setImageOpen(true)}>Image</button>}
          {canEdit && <button onClick={enrichBoard} disabled={enriching}>{enriching ? "Refreshing…" : "Refresh specs"}</button>}
        </div>
      </div>
      <p className="muted boardSubtitle">{board.description || `${board.family || "Development board"}${board.mcu ? ` · ${board.mcu}` : ""}`}</p>
      {enrichMessage && <div className="detailNotice">{enrichMessage}</div>}
      <div className="badgeRow boardBadgeRow"><Badge tone="accent">{boardTypeLabel}</Badge>{radios.map(x => <Badge key={x} tone="accent">{x}</Badge>)}{board.usb_connector && <Badge>{board.usb_connector}</Badge>}</div>

      <section className="boardDetailSection">
        <h4>Core specifications</h4>
        <BoardSpecGrid rows={coreRows} status={fieldStatus} />
      </section>

      {(specs.board_type === "sbc" || specs.board_type === "compute_module") && <section className="boardDetailSection">
        <h4>Computer / module details</h4>
        <dl className="detailSpecs">
          {[
            ["CPU", specs.cpu], ["RAM options", specs.ram_options], ["Storage", specs.storage],
            ["Ethernet", specs.ethernet], ["GPIO / expansion header", specs.gpio_header],
            ["AI / NPU", specs.ai_performance || (specs.npu_tops ? `${specs.npu_tops} TOPS` : "")],
            ["Operating systems", specs.os_support], ["Form factor", specs.form_factor],
            ["Carrier required", specs.carrier_required === true ? "Yes" : specs.carrier_required === false ? "No" : ""],
          ].filter(([, value]) => value !== "" && value != null).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd></div>)}
        </dl>
      </section>}

      <section className="boardDetailSection">
        <h4>Technical details</h4>
        <BoardSpecGrid rows={technicalRows} status={fieldStatus} />
      </section>

      <section className="boardDetailSection">
        <h4>Compatibility</h4>
        <div className="compatList boardCompatList">{board.compatibility?.length ? board.compatibility.map(item => <div key={item.platform}><strong>{item.platform}</strong><Badge tone={item.support_level === "full" ? "good" : "neutral"}>{item.support_label}</Badge></div>) : <div className="compatEmpty">No compatibility records yet.</div>}</div>
      </section>

      <div className="boardLinks">
        {board.specifications?.datasheet_url && <a className="detailLink" href={board.specifications.datasheet_url} target="_blank" rel="noreferrer">Datasheet ↗</a>}
        {board.specifications?.pinout_url && <a className="detailLink" href={board.specifications.pinout_url} target="_blank" rel="noreferrer">Pinout ↗</a>}
        {(board.specifications?.technical_source_url || board.specifications?.reference_url) && <a className="detailLink" href={board.specifications.technical_source_url || board.specifications.reference_url} target="_blank" rel="noreferrer">Technical source ↗</a>}
      </div>
      {(board.image_source_page || board.image_source_url) && <p className="provenance"><span>{board.image_source_provider ? `Image: ${board.image_source_provider}${board.image_license ? ` · ${board.image_license}` : ""}` : "Image source"}</span><a href={board.image_source_page || board.image_source_url} target="_blank" rel="noreferrer">Open source ↗</a></p>}
    </>}
      </div>
      {imageOpen && <ImageManagerModal
        title={`Image — ${board.display_name}`}
        endpoint={`/api/boards/${board.id}/image/`}
        responseKey="board"
        currentImage={board.image}
        onClose={() => setImageOpen(false)}
        onUpdated={updated => { onChanged(updated); setImageOpen(false); }}
      />}
      {viewerOpen && <ImageViewer src={board.image} alt={board.display_name} title={board.display_name} onClose={() => setViewerOpen(false)} />}
      {inventoryOpen && <AddInventoryModal
        boards={boards}
        components={components}
        projects={projects}
        config={config}
        initialBoard={board}
        lockCatalogueItem
        title={"Add " + board.display_name + " to inventory"}
        onClose={() => setInventoryOpen(false)}
        onCreated={async item => {
          setInventoryOpen(false);
          await onInventoryCreated?.(item);
        }}
      />}
    </aside>
  </>;
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
