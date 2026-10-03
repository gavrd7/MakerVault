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

function TrustInstructions() {
  return <div className="httpsTrustHelp">
    <div className="httpsTrustHelpIntro">
      <strong>Trust the MakerVault Local CA on this device</strong>
      <p>The downloaded CA certificate is public and safe to install on devices you control. Never copy or export the Local CA private key from the MakerVault server.</p>
    </div>
    <div className="httpsTrustPlatforms">
      <details>
        <summary>iPhone / iPad</summary>
        <ol>
          <li>Download <strong>MakerVault Local CA</strong> from this page and open the downloaded certificate.</li>
          <li>Install the downloaded configuration profile when iOS/iPadOS prompts you.</li>
          <li>Open <strong>Settings → General → About → Certificate Trust Settings</strong>.</li>
          <li>Enable full trust for <strong>MakerVault Local CA</strong>, then return to the HTTPS address and reload it.</li>
        </ol>
      </details>
      <details>
        <summary>Windows</summary>
        <ol>
          <li>Download the CA certificate and open it.</li>
          <li>Choose <strong>Install Certificate</strong> and place it in <strong>Trusted Root Certification Authorities</strong> for the intended user or computer.</li>
          <li>Close and reopen the browser, then open MakerVault's HTTPS address again.</li>
        </ol>
      </details>
      <details>
        <summary>macOS</summary>
        <ol>
          <li>Download the CA certificate and add it to Keychain Access.</li>
          <li>Open the imported <strong>MakerVault Local CA</strong> certificate and set its trust to <strong>Always Trust</strong>.</li>
          <li>Authenticate the change when macOS asks, then reopen the browser.</li>
        </ol>
      </details>
      <details>
        <summary>Android</summary>
        <ol>
          <li>Download the CA certificate to the device.</li>
          <li>Use Android's security/credentials settings to install a <strong>CA certificate</strong>. Menu wording varies by manufacturer and Android version.</li>
          <li>Return to the browser and reload MakerVault's HTTPS address.</li>
        </ol>
      </details>
      <details>
        <summary>Linux</summary>
        <ol>
          <li>Download the CA certificate.</li>
          <li>On Debian/Ubuntu-family systems, copy it to <code>/usr/local/share/ca-certificates/MakerVault-Local-CA.crt</code> and run <code>sudo update-ca-certificates</code>.</li>
          <li>Restart the browser. If a browser uses its own certificate store, import the CA there as a trusted authority too.</li>
        </ol>
      </details>
    </div>
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
      setNotice("Local HTTPS certificate generated. Next, download and trust the MakerVault Local CA on this device before opening native HTTPS.");
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
      <p>The Local CA private key stays inside MakerVault key storage and is included in managed v3+ backups. Only public certificates can be downloaded from the GUI. Generating a certificate enables encrypted HTTPS; trusting the Local CA on each client removes the browser's untrusted-certificate warning.</p>
    </div>

    <div className="httpsSetupFlow" aria-label="Local HTTPS setup steps">
      <article className={state.server_certificate_available ? "httpsSetupStep complete" : "httpsSetupStep current"}>
        <span className="httpsStepNumber">1</span>
        <div>
          <h4>Generate</h4>
          <p>Create or reissue a server certificate for the addresses you use to reach MakerVault.</p>
          <button className="primary" type="button" onClick={generateLocal} disabled={busy || hostList.length === 0}>
            {busy ? "Generating…" : state.local_ca_available ? "Reissue local certificate" : "Generate local HTTPS certificate"}
          </button>
        </div>
      </article>

      <article className={state.local_ca_available ? "httpsSetupStep current" : "httpsSetupStep"}>
        <span className="httpsStepNumber">2</span>
        <div>
          <h4>Download the Local CA</h4>
          <p>This is the public trust certificate for devices that should recognise your MakerVault HTTPS identity.</p>
          {state.local_ca_available
            ? <a className="account-button" href="/api/settings/https/download-ca/">Download MakerVault Local CA</a>
            : <small>Generate the local certificate first.</small>}
        </div>
      </article>

      <article className={state.local_ca_available ? "httpsSetupStep current" : "httpsSetupStep"}>
        <span className="httpsStepNumber">3</span>
        <div>
          <h4>Trust it on this device</h4>
          <p>Install the downloaded CA into this device's trusted root store. This is the step that removes the browser warning.</p>
        </div>
      </article>

      <article className={state.server_certificate_available ? "httpsSetupStep current" : "httpsSetupStep"}>
        <span className="httpsStepNumber">4</span>
        <div>
          <h4>Open HTTPS</h4>
          <p>After trusting the CA, open MakerVault on its native HTTPS port and confirm the browser shows a trusted connection.</p>
          {state.native_url && state.server_certificate_available
            ? <a className="account-button" href={state.native_url} target="_blank" rel="noreferrer">Open native HTTPS</a>
            : <small>The HTTPS link appears after a server certificate is available.</small>}
        </div>
      </article>
    </div>

    {state.local_ca_available && <TrustInstructions />}

    <div className="settingsActions httpsSecondaryActions">
      {state.server_certificate_available && <a className="account-button" href="/api/settings/https/download-server-cert/">Download server certificate</a>}
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
