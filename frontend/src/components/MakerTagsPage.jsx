import React, { useEffect, useMemo, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { createPortal } from "react-dom";
import { apiFetch } from "../api";
import { Badge, LoadingBlock, Modal } from "./Common";

function targetLabel(tag) {
  if (!tag?.target) return "Target unavailable";
  return tag.target.label + (tag.target.subtitle ? " · " + tag.target.subtitle : "");
}

function kindTone(kind) {
  if (kind === "qr") return "accent";
  if (kind === "rfid") return "good";
  return "neutral";
}

function nfcCapability() {
  if (typeof window === "undefined") return { supported: false, reason: "" };
  if (!window.isSecureContext) return { supported: false, reason: "Phone NFC capture requires HTTPS (or localhost)." };
  if (!("NDEFReader" in window)) return { supported: false, reason: "Direct browser NFC capture is not available in this browser. Use the phone's normal NFC handling for MakerVault URL tags, a USB/OTG reader, or enter the UID manually." };
  return { supported: true, reason: "" };
}

function ndefRecordText(record) {
  try {
    if (!record?.data) return "";
    const decoder = new TextDecoder(record.encoding || "utf-8");
    return decoder.decode(record.data).replace(/^\u0002en/i, "").trim();
  } catch {
    return "";
  }
}

function TagCaptureControls({ kind, value, onCapture, autoFocus = false, compact = false }) {
  const inputRef = useRef(null);
  const phoneNfcMode = kind === "nfc" || kind === "auto";
  const [nfcBusy, setNfcBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const capability = nfcCapability();

  useEffect(() => {
    if (!autoFocus) return;
    const timer = window.setTimeout(() => inputRef.current?.focus(), 80);
    return () => window.clearTimeout(timer);
  }, [autoFocus, kind]);

  async function scanNfc() {
    if (!capability.supported) {
      setNotice(capability.reason);
      return;
    }
    setNfcBusy(true); setNotice("Hold an NFC tag near the phone…");
    try {
      const reader = new window.NDEFReader();
      await reader.scan();
      const result = await new Promise((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error("No NFC tag was detected. Try again.")), 30000);
        reader.addEventListener("readingerror", () => {
          window.clearTimeout(timeout);
          reject(new Error("The NFC tag was detected but could not be read."));
        }, { once: true });
        reader.addEventListener("reading", event => {
          window.clearTimeout(timeout);
          const serial = String(event.serialNumber || "").trim();
          const records = Array.from(event.message?.records || []);
          const text = records.map(ndefRecordText).find(Boolean) || "";
          resolve(serial || text);
        }, { once: true });
      });
      if (!result) throw new Error("The tag did not expose a UID or readable NDEF identity.");
      onCapture(result);
      setNotice("NFC tag captured.");
    } catch (err) {
      setNotice(err?.message || "NFC capture failed.");
    } finally {
      setNfcBusy(false);
    }
  }

  return <div className={"tagCaptureControls" + (compact ? " compact" : "")}>
    {phoneNfcMode && <button type="button" onClick={scanNfc} disabled={nfcBusy}>{nfcBusy ? "Waiting for NFC…" : "Scan with phone NFC"}</button>}
    <input
      ref={inputRef}
      value={value}
      onChange={e => onCapture(e.target.value)}
      onKeyDown={e => { if (!compact && e.key === "Enter") e.preventDefault(); }}
      placeholder={kind === "qr" ? "QR identity code…" : "Scan/paste reader identity, UID or EPC…"}
      autoComplete="off"
      autoCapitalize="none"
      spellCheck={false}
    />
    {(kind === "nfc" || kind === "rfid" || kind === "auto") && <small>
      MakerVault accepts the stable identity emitted by the reader rather than requiring a particular chip family. USB/OTG keyboard readers can scan directly into this field. {phoneNfcMode && (capability.supported ? "This browser also supports direct NDEF-compatible NFC capture." : capability.reason)}
    </small>}
    {notice && <small className="tagCaptureNotice">{notice}</small>}
  </div>;
}

export default function MakerTagsPage({ config, resolveToken = "", onResolveConsumed = () => {}, onChanged = () => {}, onOpenTarget = () => {} }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("active");
  const [kind, setKind] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [editTag, setEditTag] = useState(null);
  const [resolveKind, setResolveKind] = useState("auto");
  const [resolveCode, setResolveCode] = useState("");
  const [resolveBusy, setResolveBusy] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [selectedTagIds, setSelectedTagIds] = useState([]);

  async function load() {
    setError("");
    try {
      const result = await apiFetch("/api/tags/");
      setData(result);
      return result;
    } catch (err) {
      setError(err.message);
      return null;
    }
  }

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!resolveToken) return;
    let cancelled = false;
    apiFetch("/api/tags/resolve/" + resolveToken + "/")
      .then(result => {
        if (!cancelled) setDetail(result.item);
      })
      .catch(err => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) onResolveConsumed();
      });
    return () => { cancelled = true; };
  }, [resolveToken]);

  const rows = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (data?.rows || []).filter(item => {
      if (status && item.status !== status) return false;
      if (kind && item.kind !== kind) return false;
      if (!term) return true;
      const haystack = [
        item.label, item.code, item.kind_label, item.status_label, item.technology_label,
        item.target?.label, item.target?.subtitle, item.target?.type_label,
      ].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(term);
    });
  }, [data, query, status, kind]);

  const printableRows = rows.filter(tag => tag.kind === "qr" && tag.status === "active");
  const selectedPrintableRows = printableRows.filter(tag => selectedTagIds.includes(String(tag.id)));

  async function changed(item) {
    setAddOpen(false);
    setEditTag(null);
    if (item) setDetail(item);
    await load();
    await onChanged();
  }

  async function resolveIdentity(event) {
    event.preventDefault();
    if (!resolveCode.trim()) return;
    setResolveBusy(true); setError("");
    try {
      const params = new URLSearchParams({ kind: resolveKind, code: resolveCode.trim() });
      const result = await apiFetch("/api/tags/resolve/?" + params.toString());
      setDetail(result.item);
      setResolveCode("");
    } catch (err) {
      setError(err.message);
    } finally {
      setResolveBusy(false);
    }
  }

  if (!data && !error) return <LoadingBlock label="Loading Maker Tags…" />;

  return <div className="tagStack">
    <section className="panel tagHero">
      <div>
        <span className="settingsEyebrow">Physical identity</span>
        <h2>Maker Tags</h2>
        <p>Attach QR, NFC and RFID identities to physical MakerVault records. Tags stay owner-scoped and can be reassigned or retired without losing their history.</p>
      </div>
      <div className="printingHeroActions">
        {config?.permissions?.add_maker_tag && <button className="primary" onClick={() => setAddOpen(true)}>Add Maker Tag</button>}
        <button onClick={load}>Refresh</button>
        <button disabled={!printableRows.length} onClick={() => setBatchOpen(true)}>Print labels</button>
      </div>
    </section>

    {error && <div className="error">{error}</div>}

    <section className="panel tagResolvePanel">
      <div>
        <strong>Resolve a physical tag</strong>
        <small>Scan or paste any stable code supplied by a compatible phone or PC reader. Auto-detect searches NFC, RFID and QR identities.</small>
      </div>
      <form onSubmit={resolveIdentity}>
        <select value={resolveKind} onChange={e => setResolveKind(e.target.value)}>
          <option value="auto">Auto-detect reader identity</option>
          <option value="rfid">RFID</option>
          <option value="nfc">NFC</option>
          <option value="qr">QR identity code</option>
        </select>
        <TagCaptureControls kind={resolveKind} value={resolveCode} onCapture={setResolveCode} autoFocus compact />
        <button className="primary" disabled={!resolveCode.trim() || resolveBusy}>{resolveBusy ? "Resolving…" : "Resolve"}</button>
      </form>
    </section>

    <section className="panel tagLibrary">
      <div className="tagToolbar">
        <div>
          <strong>{data?.rows?.length || 0} Maker Tag{data?.rows?.length === 1 ? "" : "s"}</strong>
          <small>{rows.length} shown</small>
        </div>
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search tags, targets or identities…" />
        <select value={kind} onChange={e => setKind(e.target.value)}>
          <option value="">All tag types</option>
          {(data?.kinds || []).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
        <select value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">All states</option>
          <option value="active">Active</option>
          <option value="retired">Retired</option>
        </select>
      </div>

      <div className="tagBatchSelectionBar">
        <span>{selectedPrintableRows.length} selected · {printableRows.length} printable in current filters</span>
        <button type="button" disabled={!printableRows.length} onClick={() => setSelectedTagIds(old => [...new Set([...old, ...printableRows.map(item => String(item.id))])])}>Select all matching QR tags</button>
        <button type="button" disabled={!selectedTagIds.length} onClick={() => setSelectedTagIds([])}>Clear selection</button>
        <button type="button" disabled={!selectedPrintableRows.length} onClick={() => setBatchOpen(true)}>Print selected</button>
      </div>
      <div className="tagList">
        {rows.map(tag => <article className={"tagRow tagRow-" + tag.status} key={tag.id}>
          {tag.kind === "qr" && tag.status === "active" && <label className="tagBatchCheck"><input type="checkbox" aria-label={"Select " + (tag.label || tag.code)} checked={selectedTagIds.includes(String(tag.id))} onChange={event => setSelectedTagIds(old => event.target.checked ? [...new Set([...old, String(tag.id)])] : old.filter(id => id !== String(tag.id)))} /></label>}
          <div className="tagIdentityMark">{tag.kind === "qr" ? "QR" : tag.kind === "nfc" ? "NFC" : "RFID"}</div>
          <div className="tagRowMain">
            <div className="tagRowTitle">
              <strong>{tag.label || tag.code}</strong>
              <Badge tone={kindTone(tag.kind)}>{tag.kind_label}</Badge>
              {tag.status === "retired" && <Badge>Retired</Badge>}
            </div>
            <code>{tag.code}</code>
            <small>{tag.target?.type_label || tag.target_type} · {targetLabel(tag)}{tag.technology ? " · " + tag.technology_label : ""}</small>
          </div>
          <div className="tagRowActions">
            <button onClick={async () => {
              try {
                const result = await apiFetch("/api/tags/" + tag.id + "/");
                setDetail(result.item);
              } catch (err) { setError(err.message); }
            }}>View</button>
            {config?.permissions?.change_maker_tag && <button onClick={() => setEditTag(tag)}>Edit</button>}
          </div>
        </article>)}
        {!rows.length && <div className="projectEmpty"><strong>No matching Maker Tags.</strong><span>Create a tag or change the current filters.</span></div>}
      </div>
    </section>

    {batchOpen && <MakerTagBatchPrint tags={selectedPrintableRows} allMatching={printableRows} onClose={() => setBatchOpen(false)} />}
    {addOpen && <MakerTagForm
      title="Create Maker Tag"
      data={data}
      onClose={() => setAddOpen(false)}
      onSaved={changed}
    />}

    {editTag && <MakerTagForm
      title={"Edit Maker Tag · " + (editTag.label || editTag.code)}
      data={data}
      tag={editTag}
      onClose={() => setEditTag(null)}
      onSaved={changed}
    />}

    {detail && <MakerTagDetail
      tag={detail}
      canEdit={Boolean(config?.permissions?.change_maker_tag)}
      onClose={() => setDetail(null)}
      onEdit={() => { setEditTag(detail); setDetail(null); }}
      onChanged={changed}
      onOpenTarget={() => onOpenTarget(detail)}
    />}
  </div>;
}


function MakerTagBatchPrint({ tags, allMatching, onClose }) {
  const [scope, setScope] = useState(tags.length ? "selected" : "all");
  const [format, setFormat] = useState("standard");
  const [custom, setCustom] = useState({ width: 40, height: 30, qr: 20 });
  const [fields, setFields] = useState({ title: true, code: true, target: true });
  const presets = {
    compact: { width: 50, height: 30, qr: 19 },
    standard: { width: 70, height: 50, qr: 25 },
    large: { width: 100, height: 70, qr: 38 },
  };
  const chosen = format === "custom" ? custom : presets[format];
  const size = { width: Math.min(190, Math.max(12, Number(chosen.width) || 40)), height: Math.min(260, Math.max(12, Number(chosen.height) || 30)), qr: Math.min(120, Math.max(10, Number(chosen.qr) || 20)) };
  const qr = Math.min(size.qr, size.width - 4, size.height - 4);
  const batch = scope === "all" ? allMatching : tags;
  const columns = Math.max(1, Math.floor(190 / (size.width + 3)));
  const rowsPerSheet = Math.max(1, Math.floor(277 / (size.height + 3)));
  const perSheet = columns * rowsPerSheet;
  const pages = Array.from({ length: Math.ceil(batch.length / perSheet) }, (_, i) => batch.slice(i * perSheet, (i + 1) * perSheet));
  return <>
    <Modal title="Print Maker Tag labels" subtitle="Print active QR tags using a shared sheet layout." wide onClose={onClose}>
      <div className="tagBatchSettings">
        <label>Tags to print<select value={scope} onChange={e => setScope(e.target.value)}>
          <option value="selected" disabled={!tags.length}>Selected ({tags.length})</option>
          <option value="all">All matching active QR tags ({allMatching.length})</option>
        </select></label>
        <label>Label format<select value={format} onChange={e => setFormat(e.target.value)}>
          <option value="compact">Compact · 50 × 30 mm</option>
          <option value="standard">Standard · 70 × 50 mm</option>
          <option value="large">Large · 100 × 70 mm</option>
          <option value="custom">Custom</option>
        </select></label>
        {format === "custom" && <div className="tagLabelCustomSizes">
          {[["width","Label width"],["height","Label height"],["qr","QR size"]].map(([key, name]) => <label key={key}>{name} (mm)<input type="number" min={key === "qr" ? 10 : 12} max={key === "height" ? 260 : key === "qr" ? 120 : 190} value={custom[key]} onChange={e => setCustom(old => ({ ...old, [key]: e.target.value }))} /></label>)}
        </div>}
        <div className="tagLabelTextOptions">
          {[["title","Show title"],["code","Show tag code"],["target","Show target type"]].map(([key, name]) => <label key={key}><input type="checkbox" checked={fields[key]} onChange={e => setFields(old => ({ ...old, [key]: e.target.checked }))} /> {name}</label>)}
        </div>
        <p>{batch.length} labels · {pages.length} A4 sheet{pages.length === 1 ? "" : "s"} · {columns} across × {rowsPerSheet} down.</p>
        {qr < 20 && <small>Very small QR codes may be hard to scan. Test one first.</small>}
        <div className="tagBatchPreview">
          {batch.slice(0, 6).map(tag => <MakerTagPrintable key={tag.id} tag={tag} size={size} qr={qr} fields={fields} preview />)}
        </div>
        <div className="formActions">
          <button type="button" className="primary" disabled={!batch.length} onClick={() => window.print()}>Print {batch.length} labels</button>
          <button type="button" onClick={onClose}>Close</button>
        </div>
      </div>
    </Modal>
    {typeof document !== "undefined" && createPortal(
      <div className="makerTagBatchPrintDocument" aria-hidden="true">
        {pages.map((group, i) => <div className="makerTagBatchSheet" key={i}>
          {group.map(tag => <MakerTagPrintable key={tag.id} tag={tag} size={size} qr={qr} fields={fields} />)}
        </div>)}
      </div>, document.body
    )}
  </>;
}

function MakerTagPrintable({ tag, size, qr, fields, preview = false }) {
  const scanUrl = typeof window !== "undefined" ? window.location.origin + tag.scan_path : tag.scan_path;
  return <div className={"makerTagPrintLabel" + (preview ? " makerTagBatchSample" : "")} style={{ width: size.width + "mm", height: size.height + "mm" }}>
    <div className="tagBrandedQr" style={{ width: qr + "mm", height: qr + "mm" }}>
      <QRCodeSVG value={scanUrl} size={190} level="H" marginSize={3} />
      <span className="tagBrandedQrBadge"><img src="/static/core/makervault-logo.jpg" alt="" /></span>
    </div>
    {(fields.title || fields.code || fields.target) && <div className="makerTagPrintText">
      {fields.title && <strong>{tag.label || tag.code}</strong>}
      {fields.code && <code>{tag.code}</code>}
      {fields.target && <small>MakerVault · {tag.target?.type_label || tag.target_type}</small>}
    </div>}
  </div>;
}

function MakerTagForm({ title, data, tag = null, onClose, onSaved }) {
  const [form, setForm] = useState({
    kind: tag?.kind || "qr",
    code: tag?.code || "",
    label: tag?.label || "",
    target_type: tag?.target_type || "inventory",
    target_id: tag?.target_id || "",
    notes: tag?.notes || "",
    status: tag?.status || "active",
    technology: tag?.technology || tag?.metadata?.technology || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  const groups = data?.targets || [];
  const currentGroup = groups.find(group => group.type === form.target_type);
  const targetRows = currentGroup?.rows || [];

  useEffect(() => {
    if (form.target_id && targetRows.some(row => row.id === form.target_id)) return;
    setForm(current => ({ ...current, target_id: targetRows[0]?.id || "" }));
  }, [form.target_type, targetRows.length]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const { technology, ...fields } = form;
      const body = {
        ...fields,
        metadata: {
          ...(tag?.metadata || {}),
          technology: (form.kind === "nfc" || form.kind === "rfid") ? technology : "",
        },
      };
      if (form.kind === "qr" && !tag) body.code = form.code.trim();
      const result = await apiFetch(tag ? "/api/tags/" + tag.id + "/" : "/api/tags/", {
        method: tag ? "PATCH" : "POST",
        body,
      });
      onSaved(result.item);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={title} subtitle="One physical identity can be reassigned over time while MakerVault keeps an audit trail." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label>Tag type<select value={form.kind} onChange={e => set("kind", e.target.value)}>
        {(data?.kinds || []).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select></label>
      <label>Identity code
        {form.kind === "qr"
          ? <input value={form.code} onChange={e => set("code", e.target.value)} placeholder="Leave blank to generate" />
          : <TagCaptureControls kind={form.kind} value={form.code} onCapture={value => set("code", value)} autoFocus={!tag} />}
      </label>
      {(form.kind === "nfc" || form.kind === "rfid") && <label className="full">Tag / reader technology (optional)<select value={form.technology} onChange={e => set("technology", e.target.value)}>
        {(data?.technologies || []).map(item => <option key={item.value || "auto"} value={item.value}>{item.label}</option>)}
      </select></label>}
      <label className="full">Label<input value={form.label} onChange={e => set("label", e.target.value)} placeholder="e.g. Loft server ESP32, Black ABS spool" /></label>

      <label>Target type<select value={form.target_type} onChange={e => set("target_type", e.target.value)}>
        {groups.map(group => <option key={group.type} value={group.type}>{group.label}</option>)}
      </select></label>
      <label>Target<select required value={form.target_id} onChange={e => set("target_id", e.target.value)}>
        {!targetRows.length && <option value="">No available records</option>}
        {targetRows.map(row => <option key={row.id} value={row.id}>{row.label}{row.subtitle ? " · " + row.subtitle : ""}</option>)}
      </select></label>

      {tag && <label>Status<select value={form.status} onChange={e => set("status", e.target.value)}><option value="active">Active</option><option value="retired">Retired</option></select></label>}
      <label className={tag ? "" : "full"}>Notes<textarea rows="4" value={form.notes} onChange={e => set("notes", e.target.value)} placeholder="Optional physical label/location notes…" /></label>

      {(form.kind === "nfc" || form.kind === "rfid") && <div className="settingsCallout full">
        <strong>Broad reader compatibility</strong>
        <p>MakerVault stores the stable value your reader supplies and does not require one specific NFC/RFID chip family. Android browsers with Web NFC can capture supported NDEF-compatible tags directly. iPhone/iPad can open a MakerVault NDEF URL with the normal system NFC reader, while USB/Bluetooth/OTG readers on phones or PCs can paste UID, EPC or vendor reader codes into the identity field.</p>
        <p>Hardware still determines what can actually be scanned: an iPhone cannot expose every low-frequency/UHF tag or arbitrary raw UID to a web page, but those tags can still be used through a compatible external reader.</p>
      </div>}

      {form.kind === "rfid" && form.target_type === "spool" && <div className="settingsCallout full">
        <strong>Spool RFID compatibility</strong>
        <p>Conventional hexadecimal RFID UIDs are mirrored to the spool's legacy RFID field for CFS/current integrations. Other reader identities remain valid Maker Tags without being forced into that legacy UID field.</p>
      </div>}

      <div className="formActions full">
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy || !form.target_id}>{busy ? "Saving…" : tag ? "Save changes" : "Create tag"}</button>
      </div>
    </form>
  </Modal>;
}

function MakerTagDetail({ tag, canEdit, onClose, onEdit, onChanged, onOpenTarget }) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const qrWrap = useRef(null);
  const [customSize, setCustomSize] = useState({ width: 40, height: 30, qr: 20 });
  const [textOptions, setTextOptions] = useState({ title: true, code: true, target: true });
  const [labelFormat, setLabelFormat] = useState("standard");
  const labelFormats = {
    standard: { name: "Standard label · 70 × 50 mm", width: 70, height: 50, qr: 25 },
    compact: { name: "Compact label · 50 × 30 mm", width: 50, height: 30, qr: 19 },
    large: { name: "Large label · 100 × 70 mm", width: 100, height: 70, qr: 38 },
  };
  const selectedFormat = labelFormat === "custom" ? { name: "Custom", ...customSize } : labelFormats[labelFormat];
  const safeFormat = { width: Math.min(190, Math.max(12, Number(selectedFormat.width) || 40)), height: Math.min(260, Math.max(12, Number(selectedFormat.height) || 30)), qr: Math.min(120, Math.max(10, Number(selectedFormat.qr) || 20)) };
  const qrSize = Math.min(safeFormat.qr, safeFormat.width - 4, safeFormat.height - 4);
  const scanUrl = typeof window !== "undefined" ? window.location.origin + tag.scan_path : tag.scan_path;

  async function setStatus(status) {
    setBusy(true); setNotice("");
    try {
      const result = await apiFetch("/api/tags/" + tag.id + "/", {
        method: "PATCH",
        body: { status },
      });
      onChanged(result.item);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function copy(value, label) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice(label + " copied.");
    } catch {
      setNotice("Copy was blocked by the browser. Select the value manually.");
    }
  }

  async function writeNfcLink() {
    const capability = nfcCapability();
    if (!capability.supported) {
      setNotice(capability.reason);
      return;
    }
    setBusy(true); setNotice("Hold a writable NFC tag near the phone…");
    try {
      const writer = new window.NDEFReader();
      await writer.write({ records: [{ recordType: "url", data: scanUrl }] });
      setNotice("MakerVault scan link written to the NFC tag. Phones can now tap it to open this record.");
    } catch (err) {
      setNotice(err?.message || "The NFC tag could not be written.");
    } finally {
      setBusy(false);
    }
  }

  function printLabel() {
    setNotice("");
    window.print();
  }

  return <><Modal title={tag.label || tag.code} subtitle="Maker Tag identity and assignment history." onClose={onClose} wide>

    {notice && <div className={notice.toLowerCase().includes("blocked") ? "formError" : "notice"}>{notice}</div>}
    <div className="tagDetailGrid">
      <div className="tagDetailIdentity">
        <Badge tone={kindTone(tag.kind)}>{tag.kind_label}</Badge>
        <h3>{tag.code}</h3>
        <p>{tag.target?.type_label || tag.target_type}</p>
        <strong>{targetLabel(tag)}</strong>
        {(tag.kind === "nfc" || tag.kind === "rfid") && <small>Reader technology: {tag.technology_label || "Auto / unspecified"}</small>}
        {tag.notes && <small>{tag.notes}</small>}
      </div>

      {tag.kind === "qr" ? <div className="tagQrCard" ref={qrWrap}>
        <div className="tagBrandedQr"><QRCodeSVG value={scanUrl} size={190} level="H" marginSize={3} /><span className="tagBrandedQrBadge" aria-hidden="true"><img src="/static/core/makervault-logo.jpg" alt="" /></span></div>
        <code>{scanUrl}</code>
        <div className="tagQrActions">
          <button onClick={() => copy(scanUrl, "Scan link")}>Copy scan link</button>
        </div>
        <label className="tagLabelFormat">Label format
          <select value={labelFormat} onChange={event => setLabelFormat(event.target.value)}>
            {Object.entries(labelFormats).map(([value, option]) => <option key={value} value={value}>{option.name}</option>)}
            <option value="custom">Custom dimensions</option>
          </select>
        </label>
        {labelFormat === "custom" && <div className="tagLabelCustomSizes">
          {[["width","Label width"],["height","Label height"],["qr","QR size"]].map(([key, title]) => <label key={key}>{title} (mm)
            <input type="number" min={key === "qr" ? 10 : 12} max={key === "height" ? 260 : key === "qr" ? 120 : 190} value={customSize[key]} onChange={event => setCustomSize(old => ({...old, [key]: event.target.value}))} />
          </label>)}
        </div>}
        <div className="tagLabelTextOptions">
          <label><input type="checkbox" checked={textOptions.title} onChange={event => setTextOptions(old => ({ ...old, title: event.target.checked }))} /> Show title</label>
          <label><input type="checkbox" checked={textOptions.code} onChange={event => setTextOptions(old => ({ ...old, code: event.target.checked }))} /> Show tag code</label>
          <label><input type="checkbox" checked={textOptions.target} onChange={event => setTextOptions(old => ({ ...old, target: event.target.checked }))} /> Show target type</label>
        </div>
        {qrSize < 20 && <small role="status">Small QR codes with long scan URLs may be difficult to scan. Test before printing a batch.</small>}
                <div className="tagLabelPreviewWrap">
          <div className="tagLabelPreview" style={{ width: safeFormat.width * 3.2, height: safeFormat.height * 3.2 }}>
            <div className="tagLabelPreviewCode" style={{ width: qrSize * 3.2, height: qrSize * 3.2 }}>
              <div className="tagBrandedQr"><QRCodeSVG value={scanUrl} size={190} level="H" marginSize={3} /><span className="tagBrandedQrBadge" aria-hidden="true"><img src="/static/core/makervault-logo.jpg" alt="" /></span></div>
            </div>
            <div className="tagLabelPreviewText">
              {textOptions.title && <strong>{tag.label || tag.code}</strong>}{textOptions.code && <code>{tag.code}</code>}{textOptions.target && <small>MakerVault · {tag.target?.type_label || tag.target_type}</small>}
            </div>
          </div>
        </div>
        <small>Label preview at approximate screen scale; the print output uses exact millimetre dimensions. Test one label on plain paper first.</small>
        <button onClick={printLabel}>Print this label</button>
      </div> : <div className="tagQrCard">
        <div className="tagTapIcon">{tag.kind === "nfc" ? "NFC" : "RFID"}</div>
        <code>{tag.code}</code>
        <button onClick={() => copy(tag.code, "Tag identity")}>Copy identity</button>
        {tag.kind === "nfc" && <>
          <code>{scanUrl}</code>
          <button onClick={() => copy(scanUrl, "MakerVault scan link")}>Copy MakerVault scan link</button>
          {"NDEFReader" in window && <button disabled={busy} onClick={writeNfcLink}>{busy ? "Waiting for tag…" : "Write MakerVault link to NFC"}</button>}
          <small>Writing the MakerVault URL as NDEF lets compatible phones—including iPhone—tap the tag and open MakerVault without browser access to the tag UID.</small>
        </>}
      </div>}
    </div>

    <div className="tagDetailMeta">
      <div><span>Status</span><strong>{tag.status_label}</strong></div>
      <div><span>Created</span><strong>{new Date(tag.created_at).toLocaleString()}</strong></div>
      <div><span>Last updated</span><strong>{new Date(tag.updated_at).toLocaleString()}</strong></div>
    </div>

    <section className="tagHistory">
      <div className="projectSectionHead"><h3>History</h3><span>{tag.events?.length || 0}</span></div>
      {(tag.events || []).map(event => <div className="tagHistoryRow" key={event.id}>
        <div><strong>{event.event_label}</strong><small>{event.summary}</small></div>
        <span>{new Date(event.created_at).toLocaleString()}</span>
      </div>)}
      {!tag.events?.length && <p className="muted">No tag history recorded yet.</p>}
    </section>

    <div className="formActions">
      {tag.target && <button className="primary" onClick={onOpenTarget}>Open target</button>}
      {canEdit && <button onClick={onEdit}>Edit / reassign</button>}
      {canEdit && (tag.status === "active"
        ? <button className="dangerButton" disabled={busy} onClick={() => setStatus("retired")}>Retire tag</button>
        : <button className="primary" disabled={busy} onClick={() => setStatus("active")}>Reactivate tag</button>)}
    </div>
  </Modal>

    {tag.kind === "qr" && typeof document !== "undefined" && createPortal(
      <div className="makerTagPrintPage" aria-hidden="true">
        <div className="makerTagPrintLabel" style={{ width: safeFormat.width + "mm", height: safeFormat.height + "mm" }}>
          <div className="tagBrandedQr" style={{ width: qrSize + "mm", height: qrSize + "mm" }}>
            <QRCodeSVG value={scanUrl} size={190} level="H" marginSize={3} />
            <span className="tagBrandedQrBadge"><img src="/static/core/makervault-logo.jpg" alt="" /></span>
          </div>
          {(textOptions.title || textOptions.code || textOptions.target) && <div className="makerTagPrintText">
            {textOptions.title && <strong>{tag.label || tag.code}</strong>}
            {textOptions.code && <code>{tag.code}</code>}
            {textOptions.target && <small>MakerVault · {tag.target?.type_label || tag.target_type}</small>}
          </div>}
        </div>
      </div>, document.body
    )}
  </>;
}
