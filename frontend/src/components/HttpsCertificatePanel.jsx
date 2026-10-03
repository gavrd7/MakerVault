import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function CertSummary({ title, cert }) {
  if (!cert || !cert.subject) return <div className="account-empty"><strong>{title}</strong><p>Not available yet.</p></div>;
  return <div className="httpsCertSummary">
    <div className="panelHead"><div><h4>{title}</h4><p>{cert.subject}</p></div></div>
    <dl className="httpsCertMeta">
      <div><dt>Issuer</dt><dd>{cert.issuer || "—"}</dd></div>
      <div><dt>Expires</dt><dd>{formatDate(cert.not_after)}</dd></div>
      <div className="wide"><dt>Names / addresses</dt><dd>{(cert.sans || []).join(", ") || "—"}</dd></div>
      <div className="wide"><dt>SHA-256 fingerprint</dt><dd><code>{cert.sha256_fingerprint || "—"}</code></dd></div>
    </dl>
  </div>;
}

export default function HttpsCertificatePanel() {
  const [state, setState] = useState(null);
  const [hosts, setHosts] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setError("");
    try {
      const result = await apiFetch("/api/settings/https/");
      setState(result.https);
      if (!hosts && result.https?.current_host) setHosts(result.https.current_host);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => { load(); }, []);

  const hostList = useMemo(() => hosts.split(",").map(item => item.trim()).filter(Boolean), [hosts]);

  async function generateLocal() {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await apiFetch("/api/settings/https/generate-local/", {
        method: "POST",
        body: { hosts: hostList },
      });
      setState(result.https);
      setNotice("Local HTTPS certificate generated. The native HTTPS listener will start automatically when its certificate becomes available.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!state) return <section className="panel settingsPanel"><p>Loading HTTPS configuration…</p>{error && <div className="error">{error}</div>}</section>;

  return <section className="panel settingsPanel">
    <div className="panelHead">
      <div>
        <span className="settingsEyebrow">Transport security</span>
        <h3>HTTPS &amp; certificates</h3>
        <p>Choose how browsers reach MakerVault securely. Reverse-proxy HTTPS remains the recommended public/domain setup; local HTTPS is available directly on a separate port.</p>
      </div>
      <span className={state.server_certificate_available ? "status-pill status-on" : "status-pill"}>
        {state.server_certificate_available ? "Certificate ready" : "No native certificate"}
      </span>
    </div>

    {error && <div className="error">{error}</div>}
    {notice && <div className="notice">{notice}<button type="button" onClick={() => setNotice("")}>×</button></div>}

    <div className="httpsModeGrid">
      <article className="httpsModeCard">
        <span className="account-eyebrow">Recommended</span>
        <h4>Reverse proxy</h4>
        <p>Terminate HTTPS in Nginx, Caddy, Traefik or your existing proxy and forward to MakerVault's normal HTTP port. This is the best fit for public DNS names and automatic Let's Encrypt renewal.</p>
        <small>MakerVault does not need its native certificate listener for this mode.</small>
      </article>

      <article className="httpsModeCard">
        <span className="account-eyebrow">Public certificate</span>
        <h4>ACME / Let's Encrypt</h4>
        <p>{state.public_acme?.reason}</p>
        <small>Public issuance needs a reachable public challenge on port 80/443 or DNS-provider automation. MakerVault deliberately does not give its web process host/Docker control to force this.</small>
      </article>

      <article className="httpsModeCard selected">
        <span className="account-eyebrow">Local / LAN</span>
        <h4>MakerVault Local CA</h4>
        <p>Create a local certificate authority and a server certificate for this MakerVault host. Install the downloaded CA certificate on trusted clients once; MakerVault can then reissue server certificates without re-trusting each leaf certificate.</p>
        {state.current_host_private && <span className="status-pill status-on">Best match for this private address</span>}
      </article>
    </div>

    <div className="settingsSubgrid httpsGenerateGrid">
      <label>
        <span>Certificate names / addresses</span>
        <input value={hosts} onChange={event => setHosts(event.target.value)} placeholder="192.168.1.125,makervault.local" />
        <small>Comma-separated IPv4 addresses or DNS names. localhost and 127.0.0.1 are added automatically.</small>
      </label>
      <div className="httpsCurrentAddress">
        <span>Current browser host</span>
        <strong>{state.current_host || "Unknown"}</strong>
        <small>Native HTTPS port: {state.https_port || 8443}</small>
      </div>
    </div>

    <div className="settingsCallout">
      <strong>Before generating</strong>
      <p>The local CA private key stays inside MakerVault TLS storage and is included in managed v3+ backups. Only the public CA certificate and server certificate can be downloaded from the GUI. Browsers must trust the CA certificate before they will show the local HTTPS connection as trusted.</p>
    </div>

    <div className="settingsActions">
      <button className="primary" type="button" onClick={generateLocal} disabled={busy || hostList.length === 0}>
        {busy ? "Generating…" : state.local_ca_available ? "Reissue local certificate" : "Generate local HTTPS certificate"}
      </button>
      {state.local_ca_available && <a className="account-button" href="/api/settings/https/download-ca/">Download CA certificate</a>}
      {state.server_certificate_available && <a className="account-button" href="/api/settings/https/download-server-cert/">Download server certificate</a>}
      {state.native_url && state.server_certificate_available && <a className="account-button" href={state.native_url} target="_blank" rel="noreferrer">Open native HTTPS</a>}
    </div>

    <div className="httpsCertGrid">
      <CertSummary title="Server certificate" cert={state.server_certificate} />
      <CertSummary title="MakerVault Local CA" cert={state.local_ca} />
    </div>

    <div className="settingsCallout">
      <strong>Self-signed / local trust is intentional</strong>
      <p>A local CA provides encrypted HTTPS but is not publicly trusted. Import <strong>MakerVault Local CA</strong> into the trusted root store on each device that should trust this MakerVault instance. Do not distribute the CA private key.</p>
    </div>
  </section>;
}
