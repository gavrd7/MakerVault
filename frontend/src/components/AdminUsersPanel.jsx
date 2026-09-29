import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock, Modal } from "./Common";

const GIB = 1024 ** 3;

function formatBytes(value) {
  const bytes = Math.max(Number(value || 0), 0);
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const amount = bytes / (1024 ** index);
  return `${amount.toFixed(index >= 3 ? 2 : index === 2 ? 1 : 0)} ${units[index]}`;
}

function formatWhen(value) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function quotaLabel(user) {
  if (user.quota_mode === "unlimited") return "Unlimited";
  if (user.quota_mode === "override") return `${formatBytes(user.storage?.quota_bytes)} override`;
  return user.storage?.unlimited ? "Instance default · Unlimited" : `Instance default · ${formatBytes(user.storage?.quota_bytes)}`;
}

export default function AdminUsersPanel({ config }) {
  const [users, setUsers] = useState(null);
  const [policy, setPolicy] = useState(null);
  const [defaultQuotaGiB, setDefaultQuotaGiB] = useState("10");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [danger, setDanger] = useState(null);

  async function load() {
    setError("");
    const [userResult, policyResult] = await Promise.all([
      apiFetch("/api/settings/users/"),
      apiFetch("/api/settings/storage-policy/"),
    ]);
    setUsers(userResult.rows || []);
    setPolicy(policyResult.policy);
    setDefaultQuotaGiB(String(Number(policyResult.policy.default_quota_bytes || 0) / GIB));
  }

  useEffect(() => {
    load().catch(err => setError(err.message));
  }, []);

  const totals = useMemo(() => {
    const rows = users || [];
    return {
      active: rows.filter(row => row.is_active).length,
      disabled: rows.filter(row => !row.is_active).length,
      used: rows.reduce((sum, row) => sum + Number(row.storage?.used_bytes || 0), 0),
    };
  }, [users]);

  async function savePolicy(event) {
    event.preventDefault();
    setBusy("policy"); setError(""); setNotice("");
    try {
      const bytes = Math.max(Math.round(Number(defaultQuotaGiB || 0) * GIB), 0);
      const result = await apiFetch("/api/settings/storage-policy/", {
        method: "PATCH",
        body: {
          mode: policy.mode,
          default_quota_bytes: bytes,
        },
      });
      setPolicy(result.policy);
      setNotice("Instance storage policy saved.");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  function updateUserLocal(id, patch) {
    setUsers(rows => rows.map(row => row.id === id ? { ...row, ...patch } : row));
  }

  async function saveQuota(user) {
    setBusy(`quota-${user.id}`); setError(""); setNotice("");
    try {
      const body = { quota_mode: user.quota_mode };
      if (user.quota_mode === "override") {
        body.quota_bytes = Math.max(Math.round(Number(user.quota_gib || 0) * GIB), 0);
      }
      const result = await apiFetch(`/api/settings/users/${user.id}/`, { method: "PATCH", body });
      setUsers(rows => rows.map(row => row.id === user.id ? result.item : row));
      setNotice(`${user.username}'s storage policy was saved.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function toggleActive(user) {
    setBusy(`active-${user.id}`); setError(""); setNotice("");
    try {
      const result = await apiFetch(`/api/settings/users/${user.id}/`, {
        method: "PATCH",
        body: { is_active: !user.is_active },
      });
      setUsers(rows => rows.map(row => row.id === user.id ? result.item : row));
      setNotice(`${user.username} is now ${result.item.is_active ? "active" : "disabled"}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function runDangerAction() {
    if (!danger || danger.confirm !== danger.user.username) return;
    const { user, action } = danger;
    setBusy(`${action}-${user.id}`); setError(""); setNotice("");
    try {
      if (action === "purge") {
        const result = await apiFetch(`/api/settings/users/${user.id}/purge/`, {
          method: "POST",
          body: { confirm: danger.confirm },
        });
        setUsers(rows => rows.map(row => row.id === user.id ? result.item : row));
        setNotice(`${user.username}'s MakerVault private data was purged. The account was preserved.`);
      } else {
        await apiFetch(`/api/settings/users/${user.id}/delete/`, {
          method: "DELETE",
          body: { confirm: danger.confirm },
        });
        setUsers(rows => rows.filter(row => row.id !== user.id));
        setNotice(`${user.username}'s account and MakerVault private data were deleted.`);
      }
      setDanger(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!config?.is_superuser) {
    return <section className="empty"><div className="emptyIcon">◇</div><h2>Superuser access required</h2><p>Account and storage administration is restricted to MakerVault superusers.</p></section>;
  }
  if (!users || !policy) return <LoadingBlock label="Loading users and storage…" />;

  return <>
    {error && <div className="error">{error}</div>}
    {notice && <div className="notice">{notice}<button onClick={() => setNotice("")}>×</button></div>}

    <section className="panel settingsPanel adminStoragePolicy">
      <div className="panelHead">
        <div>
          <h3>Instance storage policy</h3>
          <p>New and default-policy accounts inherit this limit. Individual users can override it or be set to Unlimited.</p>
        </div>
        <div className="adminUserBadges">
          <Badge tone={policy.encryption?.configured ? "good" : "danger"}>{policy.encryption?.configured ? "Encrypted storage ready" : "Encryption key missing"}</Badge>
          <Badge tone="accent">{formatBytes(totals.used)} across {users.length} account{users.length === 1 ? "" : "s"}</Badge>
        </div>
      </div>
      {!policy.encryption?.configured && <div className="settingsCallout"><strong>Private storage key is not available</strong><p>New private uploads cannot be encrypted until the key file or environment key is restored. Do not replace a lost key if encrypted data already exists.</p></div>}
      <form className="settingsForm" onSubmit={savePolicy}>
        <label><span>Default policy</span><select value={policy.mode} onChange={e => setPolicy(current => ({ ...current, mode: e.target.value }))}><option value="limited">Limited</option><option value="unlimited">Unlimited</option></select></label>
        {policy.mode === "limited" && <label><span>Default quota</span><div className="intervalInput"><input type="number" min="0" step="0.25" value={defaultQuotaGiB} onChange={e => setDefaultQuotaGiB(e.target.value)} /><span>GiB</span></div><small>Applied to users whose quota mode is Instance default.</small></label>}
        <div className="settingsTimes">
          <div><span>Active accounts</span><strong>{totals.active}</strong><small>{totals.disabled} disabled</small></div>
          <div><span>Logical private storage</span><strong>{formatBytes(totals.used)}</strong><small>Across all MakerVault users</small></div>
        </div>
        <div className="settingsActions"><button className="primary" disabled={busy === "policy"}>{busy === "policy" ? "Saving…" : "Save storage policy"}</button></div>
      </form>
    </section>

    <section className="panel settingsPanel">
      <div className="panelHead">
        <div>
          <h3>Users</h3>
          <p>Manage account status and aggregate storage without browsing another user's private projects or files.</p>
        </div>
      </div>
      <div className="adminUserGrid">
        {users.map(user => {
          const isSelf = user.id === config.user_id;
          const quotaBusy = busy === `quota-${user.id}`;
          return <article className="adminUserCard" key={user.id}>
            <div className="adminUserHead">
              <div>
                <span className="settingsEyebrow">{user.email || "No email address"}</span>
                <h3>{user.username}{isSelf ? " · You" : ""}</h3>
                <p>Joined {formatWhen(user.date_joined)} · Last login {formatWhen(user.last_login)}</p>
              </div>
              <div className="adminUserBadges">
                <Badge tone={user.is_active ? "good" : "danger"}>{user.is_active ? "Active" : "Disabled"}</Badge>
                {user.is_superuser && <Badge tone="accent">Superuser</Badge>}
                {!user.is_superuser && user.is_staff && <Badge tone="neutral">Staff</Badge>}
              </div>
            </div>

            <div className="adminStorageHeadline">
              <div><strong>{formatBytes(user.storage?.used_bytes)}</strong><span>{quotaLabel(user)}</span></div>
              {!user.storage?.unlimited && <strong>{user.storage?.percent_used ?? 0}%</strong>}
            </div>
            {!user.storage?.unlimited && <div className="storageMeter"><span className="storageMeterFill" style={{ width: `${Math.min(Number(user.storage?.percent_used || 0), 100)}%` }} /></div>}

            <div className="adminStorageBreakdown">
              <span>Models / 3MF <strong>{formatBytes(user.storage?.categories?.models)}</strong></span>
              <span>Project files <strong>{formatBytes(user.storage?.categories?.project_files)}</strong></span>
              <span>Images <strong>{formatBytes(user.storage?.categories?.images)}</strong></span>
              <span>Other <strong>{formatBytes(user.storage?.categories?.other_files)}</strong></span>
            </div>

            <div className="adminRecordCounts">
              <span>{user.counts.projects} projects</span><span>{user.counts.inventory} inventory</span><span>{user.counts.files} files</span>
              <span>{user.counts.models} models</span><span>{user.counts.printers} printers</span><span>{user.counts.spools} spools</span><span>{user.counts.print_jobs} print jobs</span>
            </div>

            <div className="adminQuotaControls">
              <label><span>Quota policy</span><select value={user.quota_mode} onChange={e => updateUserLocal(user.id, {
                quota_mode: e.target.value,
                quota_gib: e.target.value === "override"
                  ? String(Number(user.quota_override_bytes ?? user.storage?.quota_bytes ?? policy.default_quota_bytes ?? 0) / GIB)
                  : user.quota_gib,
              })}><option value="default">Instance default</option><option value="override">Custom limit</option><option value="unlimited">Unlimited</option></select></label>
              {user.quota_mode === "override" && <label><span>Custom quota</span><div className="intervalInput"><input type="number" min="0" step="0.25" value={user.quota_gib ?? String(Number(user.quota_override_bytes || 0) / GIB)} onChange={e => updateUserLocal(user.id, { quota_gib: e.target.value })} /><span>GiB</span></div></label>}
              <button type="button" className="primary" disabled={quotaBusy} onClick={() => saveQuota(user)}>{quotaBusy ? "Saving…" : "Save quota"}</button>
            </div>

            <div className="adminAccountActions">
              <button type="button" disabled={isSelf || busy === `active-${user.id}`} onClick={() => toggleActive(user)}>{user.is_active ? "Disable account" : "Reactivate account"}</button>
              <div className="adminDangerActions">
                <button type="button" className="dangerButton" disabled={isSelf} onClick={() => setDanger({ action: "purge", user, confirm: "" })}>Purge private data</button>
                <button type="button" className="dangerButton" disabled={isSelf} onClick={() => setDanger({ action: "delete", user, confirm: "" })}>Delete account</button>
              </div>
            </div>
            {isSelf && <small className="adminSelfNote">Self-disable, self-purge and self-delete are blocked to prevent accidental lockout or data loss.</small>}
          </article>;
        })}
      </div>
    </section>

    {danger && <Modal
      title={danger.action === "purge" ? "Purge private MakerVault data" : "Delete MakerVault account"}
      subtitle={danger.action === "purge"
        ? "This permanently removes the user's projects, inventory, uploaded files, printing records and integrations while preserving the login account."
        : "This permanently removes the login account and its MakerVault private data."}
      onClose={() => setDanger(null)}
    >
      <div className="dangerConfirm">
        <div className="settingsCallout"><strong>This cannot be undone</strong><p>Shared catalogues are not affected. MakerVault does not show you the user's private filenames or project contents before deletion.</p></div>
        <label><span>Type <strong>{danger.user.username}</strong> to confirm</span><input autoFocus value={danger.confirm} onChange={e => setDanger(current => ({ ...current, confirm: e.target.value }))} /></label>
        <div className="settingsActions">
          <button type="button" onClick={() => setDanger(null)}>Cancel</button>
          <button type="button" className="dangerButton" disabled={danger.confirm !== danger.user.username || !!busy} onClick={runDangerAction}>{busy ? "Working…" : danger.action === "purge" ? "Permanently purge data" : "Permanently delete account"}</button>
        </div>
      </div>
    </Modal>}
  </>;
}
