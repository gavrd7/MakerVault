import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock } from "./Common";

function formatWhen(value) {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function SettingsPage({ config }) {
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(null);
  const [integrations, setIntegrations] = useState([]);
  const [busy, setBusy] = useState(false);
  const [integrationBusy, setIntegrationBusy] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setError("");
    try {
      const [maintenance, printing] = await Promise.all([
        apiFetch("/api/settings/catalogue-maintenance/"),
        apiFetch("/api/settings/printing-integrations/"),
      ]);
      setSettings(maintenance.settings);
      setForm(maintenance.settings);
      setIntegrations(printing.rows || []);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { load(); }, []);

  if (!config?.is_staff) {
    return <section className="empty"><div className="emptyIcon">◇</div><h2>Administrator settings</h2><p>Catalogue maintenance scheduling is available to administrators only.</p></section>;
  }
  if (!settings || !form) return <LoadingBlock label="Loading settings…" />;

  const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

  async function save(event) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/catalogue-maintenance/", {
        method: "PATCH",
        body: {
          enabled: form.enabled,
          interval_hours: Number(form.interval_hours),
          check_board_data: form.check_board_data,
          check_images: form.check_images,
        },
      });
      setSettings(result.settings);
      setForm(result.settings);
      setNotice("Catalogue maintenance schedule saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function updateIntegrationLocal(provider, key, value) {
    setIntegrations(rows => rows.map(row => row.provider === provider ? { ...row, [key]: value } : row));
  }

  async function saveIntegration(provider, patch = null) {
    const row = integrations.find(item => item.provider === provider);
    if (!row && !patch) return;
    setIntegrationBusy(provider); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/printing-integrations/" + provider + "/", {
        method: "PATCH",
        body: patch || {
          enabled: row.enabled,
          endpoint_url: row.endpoint_url,
          sync_direction: row.sync_direction,
        },
      });
      setIntegrations(rows => rows.map(item => item.provider === provider ? result.item : item));
      setNotice(result.item.name + " settings saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setIntegrationBusy("");
    }
  }

  async function testIntegration(provider) {
    setIntegrationBusy(provider); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/printing-integrations/" + provider + "/test/", { method: "POST" });
      setIntegrations(rows => rows.map(item => item.provider === provider ? result.item : item));
      setNotice(result.item.name + ": " + result.item.status_label + ".");
    } catch (err) {
      if (err.status === 502) {
        try {
          const refreshed = await apiFetch("/api/settings/printing-integrations/");
          setIntegrations(refreshed.rows || []);
        } catch {}
      }
      setError(err.message);
    } finally {
      setIntegrationBusy("");
    }
  }

  async function runNow() {
    setRunning(true); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/catalogue-maintenance/run/", { method: "POST" });
      setSettings(result.settings);
      setForm(result.settings);
      const jobs = result.queued || [];
      setNotice(jobs.length ? `Queued: ${jobs.join(", ")}.` : "No maintenance jobs were enabled to run.");
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  return <div className="settingsStack">
    <section className="panel settingsHero">
      <div>
        <span className="settingsEyebrow">Administration</span>
        <h2>MakerVault settings</h2>
        <p>Manage scheduled catalogue maintenance and optional external integrations from one place.</p>
      </div>
      <div className="settingsStatus">
        <span className={settings.enabled ? "status-pill status-on" : "status-pill"}>{settings.enabled ? "Enabled" : "Disabled"}</span>
      </div>
    </section>

    {error && <div className="error">{error}</div>}
    {notice && <div className="notice">{notice}<button onClick={() => setNotice("")}>×</button></div>}

    <section className="panel settingsPanel">
      <div className="panelHead">
        <div><h3>Catalogue maintenance schedule</h3><p>The default interval is 24 hours. The next-run timestamp is stored in PostgreSQL.</p></div>
      </div>
      <form className="settingsForm" onSubmit={save}>
        <label className="settingsToggle">
          <div><strong>Automatic catalogue maintenance</strong><small>Enable scheduled background checks.</small></div>
          <input type="checkbox" checked={form.enabled} onChange={e => set("enabled", e.target.checked)} />
        </label>

        <label>
          <span>Check interval</span>
          <div className="intervalInput"><input type="number" min="1" max="720" step="1" value={form.interval_hours} onChange={e => set("interval_hours", e.target.value)} /><span>hours</span></div>
          <small>1–720 hours. 24 hours = daily; 168 hours = weekly.</small>
        </label>

        <div className="settingsSubgrid">
          <label className="settingsToggle">
            <div><strong>Technical board data</strong><small>Check unresolved board specifications and supported online sources.</small></div>
            <input type="checkbox" checked={form.check_board_data} onChange={e => set("check_board_data", e.target.checked)} />
          </label>
          <label className="settingsToggle">
            <div><strong>Catalogue images</strong><small>Retry missing catalogue images on the saved maintenance cadence.</small></div>
            <input type="checkbox" checked={form.check_images} onChange={e => set("check_images", e.target.checked)} />
          </label>
        </div>

        <div className="settingsTimes">
          <div><span>Last triggered</span><strong>{formatWhen(settings.last_run_at)}</strong><small>{settings.last_triggered_by || "—"}</small></div>
          <div><span>Next scheduled run</span><strong>{settings.enabled ? formatWhen(settings.next_run_at) : "Disabled"}</strong><small>{config.timezone}</small></div>
        </div>

        {(!settings.server_board_enrichment_enabled || !settings.server_image_seeding_enabled) && <div className="settingsCallout">
          <strong>Server-level restriction</strong>
          <p>{!settings.server_board_enrichment_enabled ? "Technical enrichment is disabled by ENRICH_BOARD_CATALOGUE. " : ""}{!settings.server_image_seeding_enabled ? "Image seeding is disabled by SEED_CATALOGUE_IMAGES." : ""} GUI scheduling cannot override a server-level disable.</p>
        </div>}

        <div className="settingsActions">
          <button type="button" onClick={runNow} disabled={running}>{running ? "Queueing…" : "Run now"}</button>
          <button className="primary" disabled={busy}>{busy ? "Saving…" : "Save schedule"}</button>
        </div>
      </form>
    </section>

    <section className="panel settingsPanel">
      <div className="panelHead">
        <div><h3>3D printing integrations</h3><p>Optional external services and multi-material systems plug into MakerVault without becoming required dependencies.</p></div>
      </div>
      <div className="printingIntegrationGrid settingsIntegrationGrid">
        {integrations.map(item => {
          const statusTone = item.status === "connected" || item.status === "ready" ? "good" : item.status === "error" ? "danger" : item.status === "planned" ? "accent" : "neutral";
          return <article key={item.provider}>
            <div className="settingsIntegrationHead"><strong>{item.name}</strong><Badge tone={statusTone}>{item.status_label}</Badge></div>
            {item.provider === "spoolman" && <>
              <span>Synchronise native MakerVault spools with an optional self-hosted Spoolman server.</span>
              <label className="settingsToggle compact"><div><strong>Enable</strong><small>MakerVault remains usable when disabled.</small></div><input type="checkbox" checked={item.enabled} onChange={e => saveIntegration(item.provider, { enabled: e.target.checked, endpoint_url: item.endpoint_url, sync_direction: item.sync_direction })} /></label>
              <label><span>Server URL</span><input value={item.endpoint_url || ""} onChange={e => updateIntegrationLocal(item.provider, "endpoint_url", e.target.value)} placeholder="http://spoolman.local:7912" /></label>
              <label><span>Sync direction</span><select value={item.sync_direction} onChange={e => updateIntegrationLocal(item.provider, "sync_direction", e.target.value)}><option value="import">External → MakerVault</option><option value="export">MakerVault → external</option><option value="bidirectional">Bidirectional</option></select></label>
              <small>{item.linked_spools || 0} spool link{item.linked_spools === 1 ? "" : "s"} currently mapped.</small>
              {item.last_error && <small className="integrationError">{item.last_error}</small>}
              <div className="settingsActions compact"><button onClick={() => testIntegration(item.provider)} disabled={integrationBusy === item.provider}>Test connection</button><button className="primary" onClick={() => saveIntegration(item.provider)} disabled={integrationBusy === item.provider}>Save</button></div>
            </>}
            {item.provider === "creality_cfs" && <>
              <span>Read loaded CFS slots from compatible Creality printers registered in MakerVault.</span>
              <label className="settingsToggle compact"><div><strong>Enable</strong><small>Read-only discovery first.</small></div><input type="checkbox" checked={item.enabled} onChange={e => saveIntegration(item.provider, { enabled: e.target.checked, sync_direction: "import" })} /></label>
              <small>{item.compatible_printers || 0} compatible printer{item.compatible_printers === 1 ? "" : "s"} · {item.configured_printers || 0} with local host/IP.</small>
              {item.last_error && <small className="integrationError">{item.last_error}</small>}
              <div className="settingsActions compact"><button onClick={() => testIntegration(item.provider)} disabled={integrationBusy === item.provider}>Refresh status</button></div>
            </>}
            {item.provider === "simplyprint" && <><span>Optional filament inventory synchronisation where SimplyPrint API access is available.</span><small>Adapter planned; no dependency on SimplyPrint.</small></>}
            {item.provider === "bambu_ams" && <><span>Future Bambu Lab AMS / AMS Lite adapter using the same provider-neutral slot model.</span><small>Future adapter.</small></>}
            {item.provider === "elegoo" && <><span>Future Elegoo multi-material adapter where a reliable interface is available.</span><small>Future adapter.</small></>}
            {item.provider === "qidi" && <><span>Future QIDI Box adapter where a reliable interface is available.</span><small>Future adapter.</small></>}
            {item.provider === "snapmaker" && <><span>Future Snapmaker multi-material/toolchanger adapter where a reliable interface is available.</span><small>Future adapter.</small></>}
            <small>Last checked: {formatWhen(item.last_checked_at)}</small>
          </article>;
        })}
      </div>
    </section>

    <section className="panel settingsInfo">
      <h3>How scheduled checks behave</h3>
      <p>The scheduler does not blindly redownload the whole catalogue every day. It re-checks supported online board sources and retries records still missing images on the saved cadence. Existing local images are skipped, confidence/licence rules remain enforced, and populated/user-edited specification values are not overwritten.</p>
      <p>Restarting or rebuilding the MakerVault container does not reset the interval. The schedule is stored in the database and resumes from the saved next-run time.</p>
    </section>
  </div>;
}
