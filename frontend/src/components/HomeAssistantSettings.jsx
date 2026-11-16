import React, {useEffect, useState} from "react";
import {apiFetch} from "../api";

/** Deliberately separate from printer-status sync integrations: no scheduler. */
export default function HomeAssistantSettings() {
  const [saved, setSaved] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [endpoint, setEndpoint] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    apiFetch("/api/settings/home-assistant/").then(({item}) => {
      if (!live) return;
      setSaved(item);setEnabled(item.enabled);setEndpoint(item.endpoint_url || "");
    }).catch(err => {if (live) setError(err.message);});
    return () => {live = false;};
  }, []);
  async function save() {
    setBusy(true);setError("");setNotice("");
    try {
      const result = await apiFetch("/api/settings/home-assistant/", {
        method:"PATCH", body:{enabled,endpoint_url:endpoint, ...(token ? {token} : {})},
      });
      setSaved(result.item);setToken("");
      setNotice("Home Assistant printer power settings saved.");
    } catch (err) {setError(err.message);} finally {setBusy(false);}
  }
  async function check() {
    setBusy(true);setError("");setNotice("");
    try {
      const result = await apiFetch("/api/settings/home-assistant/test/", {method:"POST",body:{}});
      if (result.connected) setNotice("Home Assistant REST API is connected.");
    } catch (err) {setError(err.message);} finally {setBusy(false);}
  }
  return <section className="settingsHomeAssistantIntegration" aria-label="Home Assistant printer power settings">
    <div className="settingsIntegrationHead"><strong>Home Assistant · printer power</strong>
      {saved?.enabled && <span className="status-pill status-on">Enabled</span>}
    </div>
    <p>Optional manual smart-plug power buttons only. No automatic shutdown, schedules or printer monitoring.</p>
    <label className="settingsToggle compact"><div><strong>Enable printer power control</strong>
      <small>Only printers assigned to a switch will show a power button.</small></div>
      <input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)}/>
    </label>
    <label>Home Assistant URL
      <input type="url" placeholder="http://homeassistant.local:8123" value={endpoint}
        onChange={event => setEndpoint(event.target.value)} autoComplete="url"/>
    </label>
    <label>Long-lived access token
      <input type="password" value={token} onChange={event => setToken(event.target.value)}
        placeholder={saved?.token_configured ? "Token saved — enter only to replace" : "Paste Home Assistant token"}
        autoComplete="new-password"/>
    </label>
    <small>The token is encrypted on the MakerVault server and is never returned in API responses. Power off always requires confirmation.</small>
    <div className="settingsActions compact">
      <button type="button" className="primary" disabled={busy} onClick={save}>{busy ? "Working…" : "Save Home Assistant"}</button>
      <button type="button" disabled={busy || !saved?.enabled} onClick={check}>Test connection</button>
    </div>
    {error && <div className="formError" role="alert">{error}</div>}
    {notice && <div className="notice" role="status">{notice}</div>}
  </section>;
}
