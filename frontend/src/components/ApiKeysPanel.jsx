import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";

const SCOPES = [
  ["tags:read", "Read and identify tags"],
  ["tags:write", "Register and assign tags (future device API)"],
  ["inventory:read", "Read inventory records (future device API)"],
  ["spools:weight", "Submit spool weights (reserved)"],
  ["devices:status", "Report device status (reserved)"],
];

export default function ApiKeysPanel() {
  const [rows, setRows] = useState([]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState(["tags:read"]);
  const [days, setDays] = useState("365");
  const [issued, setIssued] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const result = await apiFetch("/api/account/api-keys/");
    setRows(result.rows || []);
  };
  useEffect(() => {
    refresh().catch(err => setError(err.message));
  }, []);

  const create = async event => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = await apiFetch("/api/account/api-keys/", {
        method: "POST",
        body: { name, scopes, expires_in_days: days === "never" ? null : Number(days) },
      });
      setIssued(result.token);
      setName("");
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async item => {
    if (!window.confirm(`Revoke API key "${item.name}"? Connected devices using it will lose access immediately.`)) return;
    setError("");
    setBusy(true);
    try {
      await apiFetch(`/api/account/api-keys/${item.id}/revoke/`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return <div className="settingsCallout">
    <h4>API Keys</h4>
    <p>Create scoped credentials for future RFID terminals, weighing stations and external integrations. Device API authentication is not yet enabled.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {issued && <div className="notice" role="status">
      <strong>Copy your key now — it will not be shown again.</strong>
      <p><code style={{ overflowWrap: "anywhere" }}>{issued}</code></p>
      <button type="button" onClick={() => navigator.clipboard.writeText(issued).catch(() => setError("Clipboard access failed; copy the key manually."))}>Copy key</button>
      <button type="button" onClick={() => setIssued("")}>I've saved it</button>
    </div>}
    <form onSubmit={create}>
      <label>Key name <input required maxLength={120} value={name} onChange={e => setName(e.target.value)} placeholder="Workshop RFID terminal" /></label>
      <fieldset><legend>Allowed scopes</legend>
        {SCOPES.map(([scope, label]) => <label key={scope} style={{ display: "block" }}>
          <input type="checkbox" checked={scopes.includes(scope)} onChange={e => setScopes(old => e.target.checked ? [...old, scope] : old.filter(x => x !== scope))} />
          {label}
        </label>)}
      </fieldset>
      <label>Expires in <select value={days} onChange={e => setDays(e.target.value)}>
        <option value="30">30 days</option><option value="90">90 days</option>
        <option value="365">1 year</option><option value="never">Never (use with caution)</option>
      </select></label>
      <button type="submit" disabled={busy || !scopes.length || !name.trim()}>Create API key</button>
    </form>
    <h4>Existing keys</h4>
    {!rows.length && <p>No API keys created.</p>}
    {rows.map(item => <div key={item.id} style={{ marginBlock: "12px", borderTop: "1px solid var(--border, #777)", paddingTop: "8px" }}>
      <strong>{item.name}</strong> · {item.active ? "Active" : "Inactive / revoked"}
      <div><small>{item.prefix}… · {item.scopes.join(", ")} · Expires: {item.expires_at ? new Date(item.expires_at).toLocaleDateString() : "Never"}</small></div>
      {item.active && <button type="button" disabled={busy} onClick={() => revoke(item)}>Revoke</button>}
    </div>)}
  </div>;
}
