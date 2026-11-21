import React, {useEffect, useState} from "react";
import {apiFetch} from "../api";
import "./homeAssistantPower.css";
import {Modal} from "./Common";

/** Deliberately separate from printer-status sync integrations: no scheduler. */
export default function HomeAssistantSettings() {
  const [saved, setSaved] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [endpoint, setEndpoint] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [showTokenHelp, setShowTokenHelp] = useState(false);
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
  return <article className="settingsHomeAssistantIntegration" aria-label="Home Assistant printer power settings">
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
    <div className="homeAssistantTokenLabel">
      <span>Long-lived access token</span>
      <button type="button" className="homeAssistantHelpLink"
        onClick={() => setShowTokenHelp(true)}>How do I get a token?</button>
    </div>
    <label className="homeAssistantTokenInput">
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
    {showTokenHelp && <Modal title="Home Assistant access token"
      onClose={() => setShowTokenHelp(false)}>
      <div className="homeAssistantHelpSteps">
        <p>Generate a long-lived access token in your Home Assistant account:</p>
        <ol>
          <li>Open Home Assistant and select your user profile in the sidebar.</li>
          <li>Open <strong>Security</strong>.</li>
          <li>Find <strong>Long-lived access tokens</strong> and select <strong>Create token</strong>.</li>
          <li>Name it <strong>MakerVault printer power</strong>, copy the token, and paste it into MakerVault.</li>
          <li>Save your settings, then select <strong>Test connection</strong>.</li>
        </ol>
        <p>The token is displayed only when created. Keep it private; do not paste it into the Home Assistant URL.</p>
        <a href="https://www.home-assistant.io/docs/authentication/"
          target="_blank" rel="noopener noreferrer">
          Full Home Assistant authentication guidance ↗
        </a>
        <div className="settingsActions">
          <button type="button" onClick={() => setShowTokenHelp(false)}>Done</button>
        </div>
      </div>
    </Modal>}
  </article>;
}
