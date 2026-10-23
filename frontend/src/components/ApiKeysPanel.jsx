import React, { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import "./ApiKeysPanel.css";

const SCOPES = [
  ["tags:read", "Read and identify tags"],
  ["tags:write", "Register and assign tags via the device API"],
  ["inventory:read", "Search permitted inventory records via the device API"],
  ["spools:weight", "Submit validated spool measurements via the device API"],
  ["devices:status", "Reserved for future device status reporting"],
];
const SCOPE_NAMES = { "tags:read": "Read and identify tags", "tags:write": "Register and assign tags", "inventory:read": "Read inventory records", "spools:weight": "Record spool weights", "devices:status": "Report device status" };

export default function ApiKeysPanel() {
  const [rows, setRows] = useState([]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState(["tags:read"]);
  const [days, setDays] = useState("365");
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState("");
  const [editScopes, setEditScopes] = useState([]);
  const [issued, setIssued] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const secretRef = useRef(null);

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
    setNotice("");
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

  const copyKey = async () => {
    setError("");
    setNotice("");
    if (!issued) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
      await navigator.clipboard.writeText(issued);
      setNotice("API key copied to clipboard.");
      return;
    } catch {
      // Clipboard API can be unavailable over local HTTP and some browsers.
      // Fall back to the selected read-only input and legacy copy command.
      const input = secretRef.current;
      if (!input) {
        setError("Clipboard unavailable. Please select and copy the key manually.");
        return;
      }
      input.focus();
      input.select();
      input.setSelectionRange(0, input.value.length);
      let copied = false;
      try {
        copied = Boolean(document.execCommand?.("copy"));
      } catch {
        copied = false;
      }
      if (copied) setNotice("API key copied to clipboard.");
      else setError("Automatic copying is blocked. The key is selected; use Ctrl+C (or your device's Copy option).");
    }
  };

  const revoke = async item => {
    if (!window.confirm(`Revoke API key "${item.name}"? Any connected device using it will lose access.`)) return;
    setError("");
    setNotice("");
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

  const startEdit = item => {
    setEditingId(item.id);
    setEditName(item.name);
    setEditScopes([...item.scopes]);
    setError("");
    setNotice("");
  };

  const saveEdit = async event => {
    event.preventDefault();
    if (!editingId || !editName.trim() || !editScopes.length) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/api/account/api-keys/${editingId}/`, {
        method: "PATCH",
        body: { name: editName.trim(), scopes: editScopes },
      });
      setEditingId(null);
      setNotice("API key settings updated. The secret remains unchanged.");
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async item => {
    if (!window.confirm(`Permanently delete revoked API key "${item.name}" from the list? This cannot be undone.`)) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await apiFetch(`/api/account/api-keys/${item.id}/`, { method: "DELETE" });
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return <div className="apiKeysPanel">
    <div className="apiKeysIntro">
      <h4>API Keys</h4>
      <p>Create scoped credentials for RFID terminals and other hardware integrations. Device API authentication is available on this build. Copy newly issued keys immediately; they are only shown once.</p>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="notice">{notice}</p>}
    {issued && <div className="apiKeysIssued" role="group" aria-label="New API key">
      <strong>Save this key now — it won't be shown again.</strong>
      <label htmlFor="newApiKeySecret">New API key</label>
      <input id="newApiKeySecret" ref={secretRef} type="text" value={issued} readOnly
        onFocus={e => e.currentTarget.select()} autoComplete="off" spellCheck={false} />
      <div className="apiKeysActions">
        <button type="button" onClick={copyKey}>Copy key</button>
        <button type="button" onClick={() => { setIssued(""); setNotice(""); }}>I've saved it</button>
      </div>
    </div>}
    <form className="apiKeysForm" onSubmit={create}>
      <div className="apiKeysField">
        <label htmlFor="apiKeyName">Key name</label>
        <input id="apiKeyName" required maxLength={120} value={name}
          onChange={e => setName(e.target.value)} placeholder="Workshop RFID terminal" />
      </div>
      <fieldset className="apiKeysScopes">
        <legend>Allowed scopes</legend>
        <div className="apiKeysScopeList">
          {SCOPES.map(([scope, label]) => <label key={scope} className="apiKeysScope">
            <input type="checkbox" checked={scopes.includes(scope)}
              onChange={e => setScopes(old => e.target.checked ? [...old, scope] : old.filter(x => x !== scope))} />
            <span>{label}</span>
          </label>)}
        </div>
      </fieldset>
      <div className="apiKeysField">
        <label htmlFor="apiKeyExpiry">Expires in</label>
        <select id="apiKeyExpiry" value={days} onChange={e => setDays(e.target.value)}>
          <option value="30">30 days</option><option value="90">90 days</option>
          <option value="365">1 year</option><option value="never">Never (use with caution)</option>
        </select>
      </div>
      <div className="apiKeysActions">
        <button type="submit" disabled={busy || !scopes.length || !name.trim()}>Create API key</button>
      </div>
    </form>
    <section className="apiKeysExisting" aria-label="Existing API keys">
      <h4>Existing keys</h4>
      {!rows.length && <p>No API keys created.</p>}
      <div className="apiKeysRows">
        {rows.map(item => <div key={item.id} className="apiKeysRow">
          <div className="apiKeysRowInfo">
            <div className="apiKeysRowHeading">
              <strong>{item.name}</strong>
              <span className={item.active ? "apiKeysStatus active" : "apiKeysStatus"}>{item.active ? "Active" : item.revoked_at ? "Revoked" : "Expired / inactive"}</span>
            </div>
            <small>Permissions: {item.scopes.map(scope => SCOPE_NAMES[scope] || scope).join(" · ")}</small>
            <small>Expires: {item.expires_at ? new Date(item.expires_at).toLocaleDateString() : "Never"}</small>
          </div>
          <div className="apiKeysRowActions">
            {item.active && <button type="button" disabled={busy} onClick={() => startEdit(item)}>Edit</button>}
            {!item.revoked_at && <button type="button" disabled={busy} onClick={() => revoke(item)}>Revoke</button>}
            {item.revoked_at && <button type="button" disabled={busy} onClick={() => remove(item)}>Delete</button>}
          </div>
          {editingId === item.id && <form className="apiKeysEdit" onSubmit={saveEdit}>
            <label>Key name <input value={editName} maxLength={120} required onChange={e => setEditName(e.target.value)} /></label>
            <fieldset className="apiKeysScopes"><legend>Permissions</legend><div className="apiKeysScopeList">{SCOPES.map(([scope, label]) => <label className="apiKeysScope" key={scope}><input type="checkbox" checked={editScopes.includes(scope)} onChange={e => setEditScopes(old => e.target.checked ? [...old, scope] : old.filter(x => x !== scope))} /><span>{label}</span></label>)}</div></fieldset>
            <div className="apiKeysActions"><button type="submit" disabled={busy || !editName.trim() || !editScopes.length}>Save changes</button><button type="button" onClick={() => setEditingId(null)}>Cancel</button></div>
          </form>}
        </div>)}
      </div>
      <p className="apiKeysFootnote">Revoke a key before permanently deleting its record. Deleted keys cannot be recovered.</p>
    </section>
  </div>;
}
