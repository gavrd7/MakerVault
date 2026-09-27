import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock } from "./Common";

function grams(value) {
  if (value == null) return "—";
  return `${Number(value).toFixed(0)} g`;
}

function formatDate(value) {
  if (!value) return "Never";
  try { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
  catch { return value; }
}

export default function PrintingPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      setData(await apiFetch("/api/printing/"));
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { load(); }, []);

  if (!data && !error) return <LoadingBlock label="Loading 3D printing workspace…" />;

  const summary = data?.summary || {};

  return <div className="printingStack">
    <section className="panel printingHero">
      <div>
        <span className="settingsEyebrow">v0.6.0 foundation</span>
        <h2>3D Printing &amp; Model Library</h2>
        <p>Native MakerVault models, printers and spool inventory stay authoritative. External services and printer filament systems plug into this data rather than replacing it.</p>
      </div>
      <button onClick={load}>Refresh</button>
    </section>

    {error && <div className="error">{error}</div>}

    <div className="printingMetrics">
      <article><span>Models</span><strong>{summary.models || 0}</strong></article>
      <article><span>Printers</span><strong>{summary.printers || 0}</strong></article>
      <article><span>Spools</span><strong>{summary.spools || 0}</strong></article>
      <article><span>Loaded slots</span><strong>{summary.loaded_slots || 0}</strong></article>
      <article><span>External links</span><strong>{summary.externally_linked_spools || 0}</strong></article>
      <article><span>Print jobs</span><strong>{summary.print_jobs || 0}</strong></article>
    </div>

    <section className="panel printingSection">
      <div className="panelHead"><div><h3>Printers &amp; loaded filament</h3><p>Filament slots are provider-neutral so CFS, AMS and later systems can use the same model.</p></div></div>
      <div className="printingCards">
        {(data?.printers || []).map(printer => <article className="printingCard" key={printer.id}>
          <div className="printingCardHead"><div><strong>{printer.name}</strong><small>{[printer.manufacturer, printer.model].filter(Boolean).join(" · ")}</small></div><Badge>{printer.slots.length} slots</Badge></div>
          <div className="printingSlotGrid">
            {printer.slots.filter(slot => slot.is_loaded).map(slot => <div className="printingSlot" key={slot.id}>
              <span className="printingSwatch" style={slot.color_hex ? { background: slot.color_hex } : undefined} />
              <div><strong>{slot.material || "Unknown material"}</strong><small>{slot.system_label} · unit {slot.unit_index + 1}, slot {slot.slot_index + 1}</small><small>{slot.spool_code || "Unmatched spool"} · {grams(slot.remaining_weight_g)}</small></div>
            </div>)}
            {!printer.slots.some(slot => slot.is_loaded) && <div className="printingEmptyInline">No loaded filament slots have been discovered yet.</div>}
          </div>
        </article>)}
        {!data?.printers?.length && <div className="projectEmpty"><strong>No printers yet.</strong><span>Printer creation is the next UI slice; the native schema is already active.</span></div>}
      </div>
    </section>

    <section className="printingColumns">
      <div className="panel printingSection">
        <div className="panelHead"><div><h3>Spool inventory</h3><p>Native spool records with optional external mappings.</p></div></div>
        <div className="printingList">
          {(data?.spools || []).map(spool => <article className="printingListRow" key={spool.id}>
            <span className="printingSwatch" style={spool.color_hex ? { background: spool.color_hex } : undefined} />
            <div><strong>{spool.spool_id} · {spool.filament}</strong><small>{spool.material} · {grams(spool.remaining_weight_g)} remaining</small></div>
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
  </div>;
}
