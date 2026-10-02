import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock } from "./Common";

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = bytes;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
}

function formatWhen(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function statusTone(item) {
  if (item.status === "complete" && item.verified) return "good";
  if (item.status === "failed") return "danger";
  if (item.status === "running") return "accent";
  return "neutral";
}

export default function BackupRestorePanel({ onBackupStarted }) {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [validation, setValidation] = useState(null);
  const [restoreTarget, setRestoreTarget] = useState(null);
  const [watchedBackupId, setWatchedBackupId] = useState("");

  async function load({ quiet = false } = {}) {
    if (!quiet) setError("");
    try {
      const result = await apiFetch("/api/settings/backups/");
      setState(result);
      setWatchedBackupId(current => current || (result.rows || []).find(item => item.status === "running")?.id || "");
    } catch (err) {
      if (!quiet) setError(err.message);
    }
  }

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!state?.running) return undefined;
    const timer = window.setInterval(() => load({ quiet: true }), 2000);
    return () => window.clearInterval(timer);
  }, [state?.running]);

  const complete = useMemo(
    () => (state?.rows || []).filter(item => item.status === "complete"),
    [state]
  );

  useEffect(() => {
    if (!watchedBackupId || !state) return;
    const item = (state.rows || []).find(row => row.id === watchedBackupId);
    if (!item) return;

    if (item.status === "complete" && item.verified) {
      setError("");
      setNotice(
        `Backup complete ✓ Recovery bundle created and verified successfully. ${formatBytes(item.size_bytes)} · ${formatWhen(item.finished_at || item.created_at)}`
      );
      setWatchedBackupId("");
      return;
    }

    if (["failed", "interrupted"].includes(item.status)) {
      setNotice("");
      setError(`Backup failed: ${item.error || "MakerVault could not create a verified recovery bundle."}`);
      setWatchedBackupId("");
    }
  }, [state, watchedBackupId]);

  async function createBackup() {
    setBusy("create"); setError(""); setNotice(""); setValidation(null); setRestoreTarget(null);
    try {
      const result = await apiFetch("/api/settings/backups/create/", { method: "POST" });
      const backupId = result.backup?.backup_id || "";
      setWatchedBackupId(backupId);
      if (backupId) onBackupStarted?.(backupId);
      setNotice("Backup started. MakerVault is temporarily read-only while the recovery bundle is captured.");
      await load({ quiet: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function validate(item) {
    setBusy("validate-" + item.id); setError(""); setNotice(""); setValidation(null); setRestoreTarget(null);
    try {
      const result = await apiFetch(`/api/settings/backups/${encodeURIComponent(item.id)}/validate/`, { method: "POST" });
      setValidation(result.validation);
      setRestoreTarget(result.item);
      setNotice("Backup validation passed. Database, media, key archive and checksums are readable.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function remove(item) {
    if (!window.confirm(`Delete backup ${item.id}? This cannot be undone.`)) return;
    setBusy("delete-" + item.id); setError(""); setNotice("");
    try {
      await apiFetch(`/api/settings/backups/${encodeURIComponent(item.id)}/`, { method: "DELETE" });
      if (restoreTarget?.id === item.id) {
        setRestoreTarget(null);
        setValidation(null);
      }
      setNotice("Backup deleted.");
      await load({ quiet: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function copyCommand(command) {
    try {
      await navigator.clipboard.writeText(command);
      setNotice("Restore command copied.");
    } catch {
      setNotice("Select and copy the restore command below.");
    }
  }

  if (!state) return <LoadingBlock label="Loading backups…" />;

  return <div className="backupStack">
    {error && <div className="error">{error}</div>}
    {notice && <div className="notice">{notice}<button onClick={() => setNotice("")}>×</button></div>}

    <section className="panel settingsPanel backupHeroPanel">
      <div className="panelHead backupPanelHead">
        <div>
          <h3>Backup &amp; restore</h3>
          <p>Create one recovery bundle containing the PostgreSQL database, media, encryption keys and deployment configuration. Backup creation runs in MakerVault's existing worker; no extra persistent container or Docker socket is required.</p>
        </div>
        <button
          className="primary"
          type="button"
          onClick={createBackup}
          disabled={busy === "create" || state.running || state.supported === false}
        >
          {state.running ? "Backup in progress…" : busy === "create" ? "Starting…" : "Create backup"}
        </button>
      </div>

      {state.supported === false && <div className="settingsCallout restoreWarning">
        <strong>Managed backup is unavailable for this deployment</strong>
        <p>{state.unsupported_reason} Existing managed bundles can still be downloaded and validated.</p>
      </div>}

      <div className="backupSummaryGrid">
        <div><span>Stored backups</span><strong>{complete.length}</strong><small>{formatBytes(state.total_bytes)} total</small></div>
        <div><span>Latest backup</span><strong>{complete[0] ? formatWhen(complete[0].finished_at || complete[0].created_at) : "Not yet"}</strong><small>{complete[0]?.verified ? "Verified" : "No completed backup"}</small></div>
        <div><span>Current state</span><strong>{state.running ? "Read-only backup window" : "Ready"}</strong><small>{state.running ? "Viewing still works; writes resume automatically." : "Normal MakerVault operation"}</small></div>
      </div>

      <div className="settingsCallout backupSecurityCallout">
        <strong>Keep backups private</strong>
        <p>Each bundle contains your database, private files, deployment secrets and the key required to decrypt encrypted uploads. Download or copy it only to storage you trust.</p>
      </div>
    </section>

    <section className="panel settingsPanel">
      <div className="panelHead">
        <div><h3>Recovery bundles</h3><p>Completed bundles are retained until you delete them. Validation re-checks the bundle before a restore.</p></div>
      </div>

      {(state.rows || []).length === 0
        ? <div className="backupEmpty"><strong>No backups yet</strong><span>Create your first backup above.</span></div>
        : <div className="backupList">
          {(state.rows || []).map(item => <article className="backupRow" key={item.id}>
            <div className="backupRowMain">
              <div className="backupRowTitle">
                <strong>{item.label || "MakerVault backup"}</strong>
                <Badge tone={statusTone(item)}>
                  {item.status === "complete" && item.verified ? "Verified" : item.status}
                </Badge>
              </div>
              <span>{formatWhen(item.finished_at || item.created_at)} · {formatBytes(item.size_bytes)}</span>
              <small>{item.id}</small>
              {item.error && <small className="backupError">{item.error}</small>}
            </div>
            <div className="backupActions">
              {item.download_available && <a className="buttonLike" href={`/api/settings/backups/${encodeURIComponent(item.id)}/download/`}>Download</a>}
              {item.status === "complete" && <button type="button" onClick={() => validate(item)} disabled={busy === "validate-" + item.id}>{busy === "validate-" + item.id ? "Validating…" : "Validate / restore"}</button>}
              {item.status !== "running" && <button type="button" className="dangerButton" onClick={() => remove(item)} disabled={busy === "delete-" + item.id}>{busy === "delete-" + item.id ? "Deleting…" : "Delete"}</button>}
            </div>
          </article>)}
        </div>}
    </section>

    <section className="panel settingsPanel">
      <div className="panelHead">
        <div><h3>Restore</h3><p>MakerVault validates the selected backup here. The final restore is intentionally handed to one guarded server command so the running web app never receives Docker control.</p></div>
      </div>

      {!restoreTarget
        ? <div className="backupEmpty"><strong>Select a completed backup</strong><span>Use <b>Validate / restore</b> above. MakerVault will verify it before showing the restore action.</span></div>
        : <div className="restoreReady">
          <div className="restoreReadyHead">
            <div>
              <Badge tone="good">Validation passed</Badge>
              <h4>{restoreTarget.id}</h4>
              <p>Format {validation?.format_version || restoreTarget.format_version || "—"} · {formatBytes(validation?.size_bytes || restoreTarget.size_bytes)} · created {formatWhen(validation?.created_utc || restoreTarget.created_at)}</p>
            </div>
          </div>
          <div className="settingsCallout restoreWarning">
            <strong>This replaces the current MakerVault data</strong>
            <p>The helper stops MakerVault, creates a fresh pre-restore safety backup, restores the selected database/media/key set, then starts MakerVault again. It refuses an invalid bundle before making destructive changes.</p>
          </div>
          <div className="restoreCommand">
            <code>{restoreTarget.restore_command}</code>
            <button type="button" onClick={() => copyCommand(restoreTarget.restore_command)}>Copy command</button>
          </div>
          <small>Run this once from your MakerVault checkout on the server. You will be asked to type the backup ID before the restore proceeds.</small>
        </div>}
    </section>
  </div>;
}
