import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { LoadingBlock } from "./Common";

function formatWhen(value) {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function SettingsPage({ config }) {
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setError("");
    try {
      const result = await apiFetch("/api/settings/catalogue-maintenance/");
      setSettings(result.settings);
      setForm(result.settings);
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
        <span className="settingsEyebrow">Automatic maintenance</span>
        <h2>Catalogue maintenance</h2>
        <p>Periodically check for missing/new board specifications and catalogue images without rerunning work on every container restart.</p>
      </div>
      <div className="settingsStatus">
        <span className={settings.enabled ? "status-pill status-on" : "status-pill"}>{settings.enabled ? "Enabled" : "Disabled"}</span>
      </div>
    </section>

    {error && <div className="error">{error}</div>}
    {notice && <div className="notice">{notice}<button onClick={() => setNotice("")}>×</button></div>}

    <section className="panel settingsPanel">
      <div className="panelHead">
        <div><h3>Schedule</h3><p>The default interval is 24 hours. The next-run timestamp is stored in PostgreSQL.</p></div>
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

    <section className="panel settingsInfo">
      <h3>How scheduled checks behave</h3>
      <p>The scheduler does not blindly redownload the whole catalogue every day. It re-checks supported online board sources and retries records still missing images on the saved cadence. Existing local images are skipped, confidence/licence rules remain enforced, and populated/user-edited specification values are not overwritten.</p>
      <p>Restarting or rebuilding the MakerVault container does not reset the interval. The schedule is stored in the database and resumes from the saved next-run time.</p>
    </section>
  </div>;
}
