import React, { useEffect, useMemo, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
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
    {(kind === "nfc") && <button type="button" onClick={scanNfc} disabled={nfcBusy}>{nfcBusy ? "Waiting for NFC…" : "Scan with phone NFC"}</button>}
    <input
      ref={inputRef}
      value={value}
      onChange={e => onCapture(e.target.value)}
      onKeyDown={e => { if (!compact && e.key === "Enter") e.preventDefault(); }}
      placeholder={kind === "qr" ? "QR identity code…" : "Scan with USB/OTG reader or enter UID…"}
      autoComplete="off"
      autoCapitalize="characters"
      spellCheck={false}
    />
    {(kind === "nfc" || kind === "rfid") && <small>
      USB/OTG keyboard readers can scan directly into this field. {kind === "nfc" && (capability.supported ? "This browser also supports direct NFC capture." : capability.reason)}
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
  const [resolveKind, setResolveKind] = useState("rfid");
  const [resolveCode, setResolveCode] = useState("");
  const [resolveBusy, setResolveBusy] = useState(false);

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
        item.label, item.code, item.kind_label, item.status_label,
        item.target?.label, item.target?.subtitle, item.target?.type_label,
      ].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(term);
    });
  }, [data, query, status, kind]);

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
        {config?.permissions?.add_maker_tag && <button className="primary" onClick={() => setAddOpen(true)}>＋ Maker Tag</button>}
        <button onClick={load}>Refresh</button>
      </div>
    </section>

    {error && <div className="error">{error}</div>}

    <section className="panel tagResolvePanel">
      <div>
        <strong>Resolve a physical tag</strong>
        <small>Useful for NFC/RFID readers that paste or report a UID.</small>
      </div>
      <form onSubmit={resolveIdentity}>
        <select value={resolveKind} onChange={e => setResolveKind(e.target.value)}>
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

      <div className="tagList">
        {rows.map(tag => <article className={"tagRow tagRow-" + tag.status} key={tag.id}>
          <div className="tagIdentityMark">{tag.kind === "qr" ? "QR" : tag.kind === "nfc" ? "NFC" : "RFID"}</div>
          <div className="tagRowMain">
            <div className="tagRowTitle">
              <strong>{tag.label || tag.code}</strong>
              <Badge tone={kindTone(tag.kind)}>{tag.kind_label}</Badge>
              {tag.status === "retired" && <Badge>Retired</Badge>}
            </div>
            <code>{tag.code}</code>
            <small>{tag.target?.type_label || tag.target_type} · {targetLabel(tag)}</small>
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

function MakerTagForm({ title, data, tag = null, onClose, onSaved }) {
  const [form, setForm] = useState({
    kind: tag?.kind || "qr",
    code: tag?.code || "",
    label: tag?.label || "",
    target_type: tag?.target_type || "inventory",
    target_id: tag?.target_id || "",
    notes: tag?.notes || "",
    status: tag?.status || "active",
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
      const body = { ...form };
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
        <strong>{form.kind === "nfc" ? "NFC capture options" : "RFID capture options"}</strong>
        <p>{form.kind === "nfc"
          ? "On supported Android browsers over HTTPS, Scan with phone NFC can capture a readable tag identity. iPhone/iPad browsers do not currently expose Web NFC; use an NDEF tag containing the MakerVault scan URL, a USB/OTG keyboard reader, or enter the UID manually."
          : "Most USB and OTG RFID readers behave like keyboards. Put the cursor in Identity code and scan; MakerVault receives the reader output without a driver-specific integration."}</p>
      </div>}

      {form.kind === "rfid" && form.target_type === "spool" && <div className="settingsCallout full">
        <strong>Spool RFID compatibility</strong>
        <p>MakerVault reuses the spool's existing RFID identity. If that spool already has an RFID UID, this tag must use the same value.</p>
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
    const svg = qrWrap.current?.querySelector("svg")?.outerHTML || "";
    const popup = window.open("", "_blank", "width=520,height=620");
    if (!popup) {
      setNotice("The browser blocked the print window.");
      return;
    }
    const safeLabel = (tag.label || tag.code).replace(/[<>&"]/g, value => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[value]));
    const safeCode = tag.code.replace(/[<>&"]/g, value => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[value]));
    popup.document.write(`<!doctype html><html><head><title>Maker Tag</title><style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0}.label{border:1px solid #aaa;border-radius:16px;padding:24px;text-align:center;max-width:340px}.label h1{font-size:22px;margin:12px 0 4px}.label code{font-size:13px;word-break:break-all}.label small{display:block;margin-top:10px;color:#555}@media print{button{display:none}.label{border-color:#000}}</style></head><body><div class="label">${svg}<h1>${safeLabel}</h1><code>${safeCode}</code><small>MakerVault · ${tag.target?.type_label || tag.target_type}</small></div><script>window.onload=()=>window.print()<\/script></body></html>`);
    popup.document.close();
  }

  return <Modal title={tag.label || tag.code} subtitle="Maker Tag identity and assignment history." onClose={onClose} wide>
    {notice && <div className={notice.toLowerCase().includes("blocked") ? "formError" : "notice"}>{notice}</div>}
    <div className="tagDetailGrid">
      <div className="tagDetailIdentity">
        <Badge tone={kindTone(tag.kind)}>{tag.kind_label}</Badge>
        <h3>{tag.code}</h3>
        <p>{tag.target?.type_label || tag.target_type}</p>
        <strong>{targetLabel(tag)}</strong>
        {tag.notes && <small>{tag.notes}</small>}
      </div>

      {tag.kind === "qr" ? <div className="tagQrCard" ref={qrWrap}>
        <QRCodeSVG value={scanUrl} size={190} level="M" marginSize={2} />
        <code>{scanUrl}</code>
        <div className="tagQrActions">
          <button onClick={() => copy(scanUrl, "Scan link")}>Copy scan link</button>
          <button onClick={printLabel}>Print label</button>
        </div>
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
  </Modal>;
}
