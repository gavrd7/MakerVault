import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock, Modal } from "./Common";
import AdminUsersPanel from "./AdminUsersPanel";
import CatalogueCoveragePanel from "./CatalogueCoveragePanel";
import BackupRestorePanel from "./BackupRestorePanel";
import HttpsCertificatePanel from "./HttpsCertificatePanel";

const EXPERIMENTAL_PRINTER_CAPABILITIES = {
  bambu_ams: {
    title: "Bambu Lab local + AMS / AMS Lite",
    detail: "Local MQTT/TLS monitoring is implemented, including AMS tray/material observations where the printer reports them.",
    adapter: "Bambu Lab local",
  },
  prusalink: {
    title: "PrusaLink local monitoring",
    detail: "Local printer/job telemetry is implemented with Digest or API-key authentication. Prusa MMU slot telemetry is not claimed unless the API exposes reliable slot data.",
    adapter: "PrusaLink",
  },
  anycubic_ace: {
    title: "Anycubic LAN + ACE / ACE Pro",
    detail: "Signed LAN-mode monitoring is implemented for the Kobra 3 / S1 generation, including ACE material observations where firmware exposes them.",
    adapter: "Anycubic LAN",
  },
  flashforge_station: {
    title: "FlashForge local + material station",
    detail: "Local port-8898 monitoring is implemented for newer compatible models, including material-station observations where firmware exposes them.",
    adapter: "FlashForge local",
  },
  elegoo: {
    title: "Elegoo Moonraker profile",
    detail: "Experimental monitoring is implemented for compatible Neptune 4 / OrangeStorm Moonraker models. This does not imply Centauri support or vendor-specific material-system telemetry.",
    adapter: "Elegoo · Moonraker",
  },
  qidi: {
    title: "QIDI Moonraker profile",
    detail: "Experimental monitoring is implemented for compatible Klipper/Moonraker models such as Plus4, Q1 Pro and X-3 families.",
    adapter: "QIDI · Moonraker",
  },
  sovol: {
    title: "Sovol Moonraker profile",
    detail: "Experimental monitoring is implemented for SV08-family and other Sovol printers that expose a compatible Moonraker API.",
    adapter: "Sovol · Moonraker",
  },
  snapmaker: {
    title: "Snapmaker U1 Moonraker profile",
    detail: "Experimental U1 monitoring is implemented, including standard numbered extruder telemetry. Older Snapmaker families are not included automatically.",
    adapter: "Snapmaker U1 · Moonraker",
  },
  voron: {
    title: "Voron / community Moonraker",
    detail: "Experimental monitoring is implemented for compatible community Klipper/Moonraker systems, including numbered extruders and active-tool reporting.",
    adapter: "Voron · Moonraker",
  },
};

function formatWhen(value) {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function AccountSettingsFrame({ src, title }) {
  const [height, setHeight] = useState(520);
  function frameLoaded(event) {
    try {
      const frame = event.currentTarget;
      const doc = frame.contentDocument;
      if (!doc || frame.contentWindow?.location.origin !== window.location.origin) return;
      const resize = () => setHeight(Math.max(340, Math.ceil(doc.documentElement.scrollHeight + 24)));
      resize();
      if (typeof ResizeObserver !== "undefined") {
        frame._accountResize?.disconnect();
        frame._accountResize = new ResizeObserver(resize);
        frame._accountResize.observe(doc.body);
      }
      // External identity-provider authorisation must occur in the top-level
      // browser rather than inside a frame.
      for (const link of doc.querySelectorAll('a[href*="/accounts/oidc/"], a[href*="/accounts/social/"]')) {
        link.setAttribute("target", "_top");
      }
      for (const form of doc.querySelectorAll('form[action*="/accounts/oidc/"], form[action*="/accounts/social/"]')) {
        form.setAttribute("target", "_top");
      }
    } catch {
      // Authentication redirects to third-party sites cannot be inspected.
    }
  }
  return <iframe className="settingsAccountFrame" title={title} src={src} style={{ height }} onLoad={frameLoaded} />;
}

export default function SettingsPage({ config, onBackupStarted }) {
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(null);
  const [integrations, setIntegrations] = useState([]);
  const [busy, setBusy] = useState(false);
  const [integrationBusy, setIntegrationBusy] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reviewState, setReviewState] = useState(null);
  const [reviewBusy, setReviewBusy] = useState("");
  const [activeTab, setActiveTab] = useState("account");
  const [accountRoute, setAccountRoute] = useState("/accounts/email/");
  const [securityRoute, setSecurityRoute] = useState("/accounts/security/oidc/");

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

  useEffect(() => { if (config?.can_manage_workspace_settings) load(); }, [config?.can_manage_workspace_settings]);

  if (config?.can_manage_workspace_settings && (!settings || !form)) return <LoadingBlock label="Loading settings…" />;

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
          check_printer_data: form.check_printer_data,
          check_filament_data: form.check_filament_data,
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

  function updateIntegrationConfigLocal(provider, key, value) {
    setIntegrations(rows => rows.map(row => row.provider === provider
      ? { ...row, config: { ...(row.config || {}), [key]: value } }
      : row));
  }

  async function saveIntegration(provider, patch = null) {
    const row = integrations.find(item => item.provider === provider);
    if (!row) return;
    const merged = { ...row, ...(patch || {}) };
    setIntegrationBusy(provider); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/printing-integrations/" + provider + "/", {
        method: "PATCH",
        body: {
          enabled: merged.enabled,
          endpoint_url: merged.endpoint_url,
          sync_direction: merged.provider === "simplyprint" ? "import" : merged.sync_direction,
          auto_sync: merged.auto_sync,
          sync_interval_minutes: Number(merged.sync_interval_minutes || 15),
          ...(merged.provider === "simplyprint" ? {
            company_id: merged.config?.company_id || "",
            history_page_size: Number(merged.config?.history_page_size || 50),
            api_key: merged.api_key_input || undefined,
          } : {}),
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
      const row = integrations.find(item => item.provider === provider);
      if (provider === "simplyprint" && row) {
        const saved = await apiFetch("/api/settings/printing-integrations/" + provider + "/", {
          method: "PATCH",
          body: {
            enabled: row.enabled,
            endpoint_url: row.endpoint_url || "https://api.simplyprint.io",
            sync_direction: "import",
            auto_sync: row.auto_sync,
            sync_interval_minutes: Number(row.sync_interval_minutes || 15),
            company_id: row.config?.company_id || "",
            history_page_size: Number(row.config?.history_page_size || 50),
            api_key: row.api_key_input || undefined,
          },
        });
        setIntegrations(rows => rows.map(item => item.provider === provider ? saved.item : item));
      }
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

  async function syncIntegration(provider) {
    setIntegrationBusy(provider); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/printing-integrations/" + provider + "/sync/", { method: "POST" });
      setIntegrations(rows => rows.map(item => item.provider === provider ? result.item : item));
      const details = result.result || {};
      if (provider === "spoolman") {
        setNotice(
          `Spoolman sync complete: ${details.remote_spools || 0} remote read, ${details.created || 0} added, ${details.updated || 0} linked records refreshed, ${details.pending_review || 0} awaiting review, ${details.locations_discovered || 0} new locations, ${details.exported || 0} exported.`
        );
      } else if (provider === "simplyprint") {
        setNotice(
          `SimplyPrint sync complete: ${details.remote_printers || 0} printers, ${details.remote_filaments || 0} remote filament records, ${details.loaded_slots || 0} loaded slots, ${details.jobs_created || 0} new print jobs and ${details.jobs_updated || 0} refreshed.`
        );
      } else if (provider === "creality_cfs") {
        setNotice(
          `Creality CFS sync complete: ${details.loaded_slots || 0} loaded slot${details.loaded_slots === 1 ? "" : "s"} discovered.`
        );
      } else {
        setNotice(result.item.name + " sync complete.");
      }
    } catch (err) {
      try {
        const refreshed = await apiFetch("/api/settings/printing-integrations/");
        setIntegrations(refreshed.rows || []);
      } catch {}
      setError(err.message);
    } finally {
      setIntegrationBusy("");
    }
  }

  async function resetIgnoredImports(provider) {
    setIntegrationBusy(provider); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/printing-integrations/" + provider + "/", {
        method: "PATCH",
        body: { reset_ignored_imports: true },
      });
      setIntegrations(rows => rows.map(item => item.provider === provider ? result.item : item));
      setNotice(result.item.name + " ignored imports will be reconsidered on the next sync.");
    } catch (err) {
      setError(err.message);
    } finally {
      setIntegrationBusy("");
    }
  }

  async function openIntegrationReviews(provider) {
    setError(""); setNotice("");
    try {
      const [reviews, spools, filaments] = await Promise.all([
        apiFetch("/api/settings/printing-integrations/" + provider + "/reviews/"),
        apiFetch("/api/printing/spools/"),
        apiFetch("/api/printing/filaments/"),
      ]);
      setReviewState({
        provider,
        rows: reviews.rows || [],
        spools: spools.rows || [],
        filaments: filaments.rows || [],
      });
    } catch (err) {
      setError(err.message);
    }
  }

  async function resolveIntegrationReview(externalId, body) {
    if (!reviewState) return;
    setReviewBusy(externalId); setError(""); setNotice("");
    try {
      const provider = reviewState.provider;
      const result = await apiFetch(
        "/api/settings/printing-integrations/" + provider + "/reviews/" + encodeURIComponent(externalId) + "/",
        { method: "POST", body }
      );
      setIntegrations(rows => rows.map(item => item.provider === provider ? result.item : item));
      const refreshed = await apiFetch("/api/settings/printing-integrations/" + provider + "/reviews/");
      setReviewState(current => current ? { ...current, rows: refreshed.rows || [] } : current);
      const action = result.result?.action || "resolved";
      const code = result.result?.spool_code ? " · " + result.result.spool_code : "";
      setNotice("Import review " + action + code + ".");
    } catch (err) {
      setError(err.message);
    } finally {
      setReviewBusy("");
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

  const enabledIntegrations = integrations.filter(item => item.enabled).length;

  return <div className="settingsStack">
    <section className="panel settingsHero">
      <div>
        <span className="settingsEyebrow">{config?.role || "User"} settings</span>
        <h2>MakerVault settings</h2>
        <p>Settings are grouped by the part of MakerVault they belong to, so unrelated controls no longer compete for the same page.</p>
      </div>
      <div className="settingsStatus">
        {activeTab === "account"
          ? <span className="status-pill status-on">Personal account</span>
          : activeTab === "security"
            ? <span className="status-pill status-on">Instance security</span>
          : activeTab === "library"
          ? <span className={settings?.enabled ? "status-pill status-on" : "status-pill"}>{settings?.enabled ? "Updates enabled" : "Updates disabled"}</span>
          : activeTab === "printing"
            ? <span className={enabledIntegrations ? "status-pill status-on" : "status-pill"}>{enabledIntegrations} integration{enabledIntegrations === 1 ? "" : "s"} enabled</span>
            : activeTab === "backups"
              ? <span className="status-pill status-on">Recovery protection</span>
              : activeTab === "https"
                ? <span className="status-pill status-on">Transport security</span>
                : <span className="status-pill status-on">Account administration</span>}
      </div>
    </section>

    <div className="settingsTabs" role="tablist" aria-label="Settings sections">
      <button type="button" role="tab" aria-selected={activeTab === "account"} className={activeTab === "account" ? "active" : ""} onClick={() => setActiveTab("account")}>
        <strong>User Account</strong><small>Email, password, MFA, sign-in methods and sessions</small>
      </button>
      {config?.is_superuser && <button type="button" role="tab" aria-selected={activeTab === "security"} className={activeTab === "security" ? "active" : ""} onClick={() => setActiveTab("security")}>
        <strong>Security</strong><small>Identity providers and server-wide authentication</small>
      </button>}
      {config?.can_manage_workspace_settings && <button
        type="button"
        role="tab"
        aria-selected={activeTab === "library"}
        className={activeTab === "library" ? "active" : ""}
        onClick={() => setActiveTab("library")}
      >
        <strong>Library updates</strong>
        <small>Catalogue data, images and maintenance schedule</small>
      </button>}
      {config?.can_manage_workspace_settings && <button
        type="button"
        role="tab"
        aria-selected={activeTab === "printing"}
        className={activeTab === "printing" ? "active" : ""}
        onClick={() => setActiveTab("printing")}
      >
        <strong>3D Printing</strong>
        <small>Spool, printer and multi-material integrations</small>
      </button>}

      {config?.is_superuser && <button
        type="button"
        role="tab"
        aria-selected={activeTab === "backups"}
        className={activeTab === "backups" ? "active" : ""}
        onClick={() => setActiveTab("backups")}
      >
        <strong>Backup &amp; restore</strong>
        <small>Create, verify, download and recover MakerVault</small>
      </button>}

      {config?.is_superuser && <button
        type="button"
        role="tab"
        aria-selected={activeTab === "https"}
        className={activeTab === "https" ? "active" : ""}
        onClick={() => setActiveTab("https")}
      >
        <strong>HTTPS &amp; certificates</strong>
        <small>Reverse proxy, local CA and native TLS</small>
      </button>}


      {config?.is_superuser && <button
        type="button"
        role="tab"
        aria-selected={activeTab === "users"}
        className={activeTab === "users" ? "active" : ""}
        onClick={() => setActiveTab("users")}
      >
        <strong>Users &amp; storage</strong>
        <small>Accounts, quotas and destructive data controls</small>
      </button>}
    </div>

    {error && <div className="error">{error}</div>}
    {notice && <div className="notice">{notice}<button onClick={() => setNotice("")}>×</button></div>}

    {activeTab === "account" && <section className="panel settingsPanel">
      <div className="panelHead"><div><h3>User Account</h3><p>Manage your email, password, two-factor authentication and connected accounts without leaving Settings.</p></div></div>
      <div className="settingsAccountLinks settingsAccountSelector" role="group" aria-label="User account options">
        {[
          ["Email addresses", "/accounts/email/"],
          ["Change password", "/accounts/password/change/"],
          ["Two-factor authentication", "/accounts/2fa/"],
          ["Connected accounts", "/accounts/3rdparty/"],
          ["Active sessions", "/accounts/sessions/"],
        ].map(([label, path]) => <button key={path} type="button" className={accountRoute === path ? "active" : ""} aria-pressed={accountRoute === path} onClick={() => setAccountRoute(path)}>{label}</button>)}
      </div>
      {accountRoute === "/accounts/3rdparty/" && <div className="settingsCallout"><strong>Connected accounts</strong><p>Any external identities linked to your MakerVault login will appear below. If none are linked, you can keep using your local password. Available connection options depend on configured identity providers.</p></div>}
      <AccountSettingsFrame key={accountRoute} src={accountRoute} title="Account preferences" />
    </section>}
    {activeTab === "security" && config?.is_superuser && <section className="panel settingsPanel">
      <div className="panelHead"><div><h3>Security</h3><p>Server-wide authentication and identity-provider administration.</p></div></div>
      <div className="settingsAccountLinks settingsAccountSelector" role="group" aria-label="Security options">
        <button type="button" className="active" onClick={() => setSecurityRoute("/accounts/security/oidc/")}>OIDC identity providers</button>
      </div>
      <AccountSettingsFrame key={securityRoute} src={securityRoute} title="OIDC identity providers" />
      <div className="settingsCallout"><p>Advanced Django administration is available separately for administrators.</p><a href="/admin/">Open Django administration</a></div>
    </section>}
    {activeTab === "library" && config?.can_manage_workspace_settings && <>
    <CatalogueCoveragePanel />
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
            <div><strong>3D printer catalogue</strong><small>Refresh supported printer models from OrcaSlicer without overwriting MakerVault's populated hardware specifications. Current catalogue: {settings.printer_catalogue_models || 0} models across {settings.printer_catalogue_manufacturers || 0} manufacturers · upstream ref {settings.server_printer_catalogue_ref || "main"}.</small></div>
            <input type="checkbox" checked={form.check_printer_data} onChange={e => set("check_printer_data", e.target.checked)} />
          </label>
          <label className="settingsToggle">
            <div><strong>Filament catalogue</strong><small>Refresh missing metadata and provenance for saved SpoolmanDB-backed filament products without overwriting your edits.</small></div>
            <input type="checkbox" checked={form.check_filament_data !== false} onChange={e => set("check_filament_data", e.target.checked)} />
          </label>
          <label className="settingsToggle">
            <div><strong>Catalogue images</strong><small>Retry missing board, component, printer and filament images on the saved maintenance cadence.</small></div>
            <input type="checkbox" checked={form.check_images} onChange={e => set("check_images", e.target.checked)} />
          </label>
        </div>

        <div className="settingsTimes">
          <div><span>Last triggered</span><strong>{formatWhen(settings.last_run_at)}</strong><small>{settings.last_triggered_by || "—"}</small></div>
          <div><span>Next scheduled run</span><strong>{settings.enabled ? formatWhen(settings.next_run_at) : "Disabled"}</strong><small>{config.timezone}</small></div>
        </div>

        {(!settings.server_board_enrichment_enabled || !settings.server_printer_catalogue_enabled || !settings.server_image_seeding_enabled) && <div className="settingsCallout">
          <strong>Server-level restriction</strong>
          <p>{!settings.server_board_enrichment_enabled ? "Technical enrichment is disabled by ENRICH_BOARD_CATALOGUE. " : ""}{!settings.server_printer_catalogue_enabled ? "OrcaSlicer printer catalogue sync is disabled by SYNC_ORCASLICER_PRINTER_CATALOGUE. " : ""}{!settings.server_image_seeding_enabled ? "Image seeding is disabled by SEED_CATALOGUE_IMAGES." : ""} GUI scheduling cannot override a server-level disable.</p>
        </div>}

        <div className="settingsActions">
          <button type="button" onClick={runNow} disabled={running}>{running ? "Queueing…" : "Run now"}</button>
          <button className="primary" disabled={busy}>{busy ? "Saving…" : "Save schedule"}</button>
        </div>
      </form>
    </section>

    </>}

    {activeTab === "printing" && config?.can_manage_workspace_settings && <>
    <section className="panel settingsPanel settingsPrintingPanel">
      <div className="panelHead">
        <div><h3>3D printing integrations</h3><p>Enable and configure the services used by the 3D Printing area. Connected services can be synchronised manually or on their own schedule.</p></div>
      </div>
      <div className="printingIntegrationGrid settingsIntegrationGrid">
        {integrations.map(item => {
          const statusTone = item.status === "connected" ? "good" : item.status === "error" || item.status === "disconnected" ? "danger" : ["planned", "experimental"].includes(item.status) ? "accent" : "neutral";
          const supported = item.can_sync;
          const experimentalCapability = EXPERIMENTAL_PRINTER_CAPABILITIES[item.provider];
          const isBusy = integrationBusy === item.provider;
          return <article key={item.provider}>
            <div className="settingsIntegrationHead"><strong>{item.name}</strong><Badge tone={statusTone}>{item.status_label}</Badge></div>

            {item.provider === "spoolman" && <>
              <span>Synchronise MakerVault spool inventory with your self-hosted Spoolman server.</span>
              <label className="settingsToggle compact"><div><strong>Enable integration</strong><small>Only enabled integrations appear on the 3D Printing status bar.</small></div><input type="checkbox" checked={item.enabled} onChange={e => saveIntegration(item.provider, { enabled: e.target.checked })} /></label>
              <label><span>Server URL</span><input value={item.endpoint_url || ""} onChange={e => updateIntegrationLocal(item.provider, "endpoint_url", e.target.value)} placeholder="http://spoolman.local:7912" /></label>
              <label><span>Sync direction</span><select value={item.sync_direction} onChange={e => updateIntegrationLocal(item.provider, "sync_direction", e.target.value)}><option value="import">External → MakerVault</option><option value="export">MakerVault → external</option><option value="bidirectional">Bidirectional</option></select></label>
              <small>{item.linked_spools || 0} Spoolman link{item.linked_spools === 1 ? "" : "s"} mapped in MakerVault.</small>
              <div className="settingsCallout integrationAuthorityCallout">
                <strong>MakerVault is authoritative</strong>
                <p>Existing MakerVault filament identity, placement, notes and status are not silently replaced by Spoolman. Missing Spoolman location names are added to the location catalogue; only genuinely new imports inherit their remote location.</p>
              </div>
              {item.pending_review_count > 0 && <button className="integrationReviewButton" type="button" onClick={() => openIntegrationReviews(item.provider)}>Review {item.pending_review_count} possible duplicate{item.pending_review_count === 1 ? "" : "s"}</button>}
              {item.ignored_import_count > 0 && <button type="button" onClick={() => resetIgnoredImports(item.provider)} disabled={isBusy}>Reconsider {item.ignored_import_count} ignored import{item.ignored_import_count === 1 ? "" : "s"}</button>}
            </>}

            {item.provider === "simplyprint" && <>
              <span>Read printer state, loaded filament and recent print history from your SimplyPrint account.</span>
              <label className="settingsToggle compact"><div><strong>Enable integration</strong><small>Read-only import. MakerVault remains authoritative for inventory and spool identity.</small></div><input type="checkbox" checked={item.enabled} onChange={e => saveIntegration(item.provider, { enabled: e.target.checked, sync_direction: "import" })} /></label>
              <label><span>Account / company ID</span><input value={item.config?.company_id || ""} onChange={e => updateIntegrationConfigLocal(item.provider, "company_id", e.target.value)} placeholder="12345" inputMode="numeric" /></label>
              <label><span>API key</span><input type="password" value={item.api_key_input || ""} onChange={e => updateIntegrationLocal(item.provider, "api_key_input", e.target.value)} placeholder={item.config?.api_key_configured ? "API key saved — enter only to replace" : "Paste SimplyPrint API key"} autoComplete="new-password" /></label>
              <label><span>Recent history per sync</span><div className="intervalInput"><input type="number" min="1" max="100" step="1" value={item.config?.history_page_size || 50} onChange={e => updateIntegrationConfigLocal(item.provider, "history_page_size", e.target.value)} /><span>jobs</span></div></label>
              <small>{item.linked_printers || 0} linked printer{item.linked_printers === 1 ? "" : "s"} · {item.linked_spools || 0} confirmed physical spool link{item.linked_spools === 1 ? "" : "s"} · {item.imported_print_jobs || 0} imported print job{item.imported_print_jobs === 1 ? "" : "s"}.</small>
              <div className="settingsCallout integrationAuthorityCallout">
                <strong>Read-only, MakerVault-primary</strong>
                <p>SimplyPrint printer status and print history are imported as context. Loaded filament appears as discovered slots, but MakerVault will not create or overwrite a physical spool until you explicitly link or add it.</p>
              </div>
              <small>Requires SimplyPrint API access and your account/company ID. The saved API key is never returned to the browser.</small>
            </>}

            {item.provider === "creality_cfs" && <>
              <span>Read CFS boxes and loaded filament slots directly from compatible Creality printers on your local network.</span>
              <label className="settingsToggle compact"><div><strong>Enable integration</strong><small>The CFS adapter is read-only.</small></div><input type="checkbox" checked={item.enabled} onChange={e => saveIntegration(item.provider, { enabled: e.target.checked, sync_direction: "import" })} /></label>
              <small>{item.compatible_printers || 0} compatible printer{item.compatible_printers === 1 ? "" : "s"} · {item.installed_printers || 0} with CFS installed · {item.configured_printers || 0} installed printer{item.configured_printers === 1 ? "" : "s"} with local host/IP.</small>
            </>}

            {!supported && experimentalCapability && <>
              <span>{experimentalCapability.detail}</span>
              <div className="settingsCallout integrationAuthorityCallout">
                <strong>Implemented · hardware validation required</strong>
                <p>Configure this per printer from <strong>3D Printing → Live monitor</strong> using the <strong>{experimentalCapability.adapter}</strong> source. MakerVault exposes the adapter now; the Experimental label means representative hardware/firmware validation is still outstanding.</p>
              </div>
            </>}

            {supported && item.enabled && <div className="integrationSchedule">
              <label className="settingsToggle compact"><div><strong>Scheduled sync</strong><small>Run this integration automatically in the background.</small></div><input type="checkbox" checked={item.auto_sync} onChange={e => updateIntegrationLocal(item.provider, "auto_sync", e.target.checked)} /></label>
              <label><span>Sync interval</span><div className="intervalInput"><input type="number" min="1" max="1440" step="1" value={item.sync_interval_minutes || 15} onChange={e => updateIntegrationLocal(item.provider, "sync_interval_minutes", e.target.value)} /><span>minutes</span></div></label>
              <div className="integrationTimes">
                <small>Last sync: {formatWhen(item.last_sync_at)}</small>
                <small>Next sync: {item.auto_sync ? formatWhen(item.next_sync_at) : "Manual only"}</small>
              </div>
            </div>}

            {item.last_error && <small className="integrationError">{item.last_error}</small>}

            {supported && <div className="settingsActions compact">
              {["spoolman", "simplyprint"].includes(item.provider) && <button onClick={() => testIntegration(item.provider)} disabled={isBusy || !item.enabled}>{isBusy ? "Working…" : "Test connection"}</button>}
              <button onClick={() => syncIntegration(item.provider)} disabled={isBusy || !item.enabled}>{isBusy ? "Synchronising…" : "Sync now"}</button>
              <button className="primary" onClick={() => saveIntegration(item.provider)} disabled={isBusy}>{isBusy ? "Saving…" : "Save"}</button>
            </div>}

            <small>Connection checked: {formatWhen(item.last_checked_at)}</small>
          </article>;
        })}
      </div>
    </section>

    </>}

    {activeTab === "backups" && config?.is_superuser && <BackupRestorePanel onBackupStarted={onBackupStarted} />}
    {activeTab === "https" && config?.is_superuser && <HttpsCertificatePanel />}
    {activeTab === "users" && <AdminUsersPanel config={config} />}

    {activeTab === "library" && <section className="panel settingsInfo">
      <h3>How scheduled checks behave</h3>
      <p>The scheduler re-checks supported online board sources, refreshes OrcaSlicer's printer-model manifests when enabled, and retries records still missing images on the saved cadence. OrcaSlicer expands catalogue breadth but does not overwrite populated MakerVault hardware specifications; existing local images are skipped and confidence/licence rules remain enforced.</p>
      <p>Restarting or rebuilding the MakerVault container does not reset the interval. The schedule is stored in the database and resumes from the saved next-run time.</p>
    </section>}
    {reviewState && <IntegrationReviewModal
      state={reviewState}
      busyId={reviewBusy}
      onClose={() => setReviewState(null)}
      onResolve={resolveIntegrationReview}
    />}
  </div>;
}


function IntegrationReviewModal({ state, busyId, onClose, onResolve }) {
  return <Modal
    title="Review integration imports"
    subtitle="MakerVault pauses ambiguous imports instead of creating or overwriting inventory automatically."
    onClose={onClose}
    wide
  >
    <div className="integrationReviewList">
      {!state.rows.length && <div className="printingEmptyInline">There are no imports waiting for review.</div>}
      {state.rows.map(review => <IntegrationReviewRow
        key={review.external_id}
        review={review}
        spools={state.spools}
        filaments={state.filaments}
        busy={busyId === review.external_id}
        onResolve={body => onResolve(review.external_id, body)}
      />)}
    </div>
  </Modal>;
}


function IntegrationReviewRow({ review, spools, filaments, busy, onResolve }) {
  const suggestedFilament = review.filament_candidates?.[0]?.id || "";
  const [filamentChoice, setFilamentChoice] = useState(suggestedFilament || "__detected__");
  const [spoolChoice, setSpoolChoice] = useState(review.spool_candidates?.[0]?.id || "");
  const remote = review.remote || {};

  return <article className="integrationReviewCard">
    <div className="integrationReviewHead">
      <div>
        <span className="settingsEyebrow">Spoolman #{review.external_id}</span>
        <h3>{[remote.vendor, remote.name].filter(Boolean).join(" · ") || remote.material || "Unknown spool"}</h3>
        <p>{[remote.material, remote.color_hex, remote.remaining_weight_g != null ? remote.remaining_weight_g + " g remaining" : "", remote.location].filter(Boolean).join(" · ")}</p>
      </div>
      <Badge tone="accent">{review.reason === "ambiguous_filament" ? "Filament needs review" : "Possible duplicate"}</Badge>
    </div>

    {!!review.spool_candidates?.length && <div className="integrationCandidateList">
      <strong>Likely MakerVault spool matches</strong>
      {review.spool_candidates.map(candidate => <div className="integrationCandidateRow" key={candidate.id}>
        <div><strong>{candidate.spool_id} · {candidate.filament}</strong><small>Match score {candidate.score}{candidate.location ? " · " + candidate.location : ""}</small></div>
        <button type="button" disabled={busy} onClick={() => onResolve({ action: "link", spool_id: candidate.id })}>Link this spool</button>
      </div>)}
    </div>}

    <div className="integrationReviewChoices">
      <label>Link a different MakerVault spool<select value={spoolChoice} onChange={e => setSpoolChoice(e.target.value)}>
        <option value="">Choose spool…</option>
        {spools.filter(spool => !(spool.external_links || []).some(link => link.provider === "spoolman")).map(spool => <option key={spool.id} value={spool.id}>{spool.spool_id} · {spool.filament}</option>)}
      </select></label>
      <button type="button" disabled={busy || !spoolChoice} onClick={() => onResolve({ action: "link", spool_id: spoolChoice })}>Link selected spool</button>
    </div>

    <div className="integrationReviewChoices">
      <label>Import as a new spool using<select value={filamentChoice} onChange={e => setFilamentChoice(e.target.value)}>
        <option value="__detected__">Create filament from detected Spoolman data</option>
        {filaments.map(filament => <option key={filament.id} value={filament.id}>{filament.display_name} · {filament.material}</option>)}
      </select></label>
      <button className="primary" type="button" disabled={busy} onClick={() => onResolve({
        action: "create",
        filament_id: filamentChoice === "__detected__" ? "" : filamentChoice,
      })}>Import as new spool</button>
    </div>

    <div className="integrationReviewFooter">
      <small>Ignoring keeps this Spoolman record out of future automatic import attempts. You can reconsider ignored imports from the Spoolman settings card.</small>
      <button type="button" disabled={busy} onClick={() => onResolve({ action: "ignore" })}>{busy ? "Working…" : "Ignore remote spool"}</button>
    </div>
  </article>;
}
