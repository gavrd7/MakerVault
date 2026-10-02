import React, { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { startFrameLoop, waitForIce, prepareCrealityOffer, cameraRequest } from "./cameraPlayback";

const LABELS = { snapshot: "Live images", mjpeg: "MJPEG live images", creality_webrtc: "Creality WebRTC · experimental" };

export default function PrinterCamera({ printerId, connection, canEdit, activeCamera, setActiveCamera, onChanged, setupOnly = false, autoStart = false }) {
  const root = `/api/printing/printers/${printerId}/connections/${connection.id}/cameras/`;
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState("");
  const [settings, setSettings] = useState(setupOnly);
  const started = useRef(false);
  const [candidates, setCandidates] = useState([]);
  const [provider, setProvider] = useState(null);
  const [presets, setPresets] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({ name: "Camera", url: "", mode: "snapshot", rotation: 0, flip_horizontal: false, flip_vertical: false });
  const camera = rows.find(item => item.id === selected);
  const playing = connection.enabled && camera && activeCamera === `${connection.id}:${camera.id}`;
  async function load() {
    try {
      const result = await apiFetch(root);
      setRows(result.rows);
      setProvider(result.provider); setPresets(result.presets || []);
      setSelected(current => result.rows.some(item => item.id === current) ? current : result.rows[0]?.id || "");
    } catch (err) { setError(err.message); }
  }
  useEffect(() => { load(); }, [connection.id]);
  useEffect(() => { if (!connection.enabled && activeCamera?.startsWith(connection.id + ":")) setActiveCamera(""); }, [connection.enabled]);
  useEffect(() => {
    if (autoStart && !started.current && camera && connection.enabled) {
      started.current = true; setActiveCamera(`${connection.id}:${camera.id}`);
    }
  }, [autoStart, camera?.id, connection.enabled]);
  async function discover() {
    setBusy(true); setError(""); setNotice(""); setWarnings([]);
    try {
      const result = await apiFetch(root + "discover/", { method: "POST", body: {} });
      setCandidates(result.candidates); setWarnings(result.warnings || []);
      if (!result.candidates.length) setNotice("No supported camera URLs were found. You can enter one below.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      await apiFetch(root, { method: "POST", body: form });
      await load(); await onChanged(); setNotice("Camera source saved. Open the printer camera preview to watch."); setSettings(setupOnly);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function usePreview() {
    if (!camera) return;
    setBusy(true); setError("");
    try {
      await apiFetch(root, { method: "PATCH", body: { id: camera.id } });
      await onChanged(); setNotice("Preview camera updated on the dashboard and 3D Printing page.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!camera || !window.confirm(`Remove camera source “${camera.name}”?`)) return;
    setBusy(true); setError(""); setActiveCamera("");
    try { await apiFetch(root, { method: "DELETE", body: { id: camera.id } }); await load(); await onChanged(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <section className="printerCamera">
    <div className="printerCameraToolbar">
      <strong>Camera</strong>
      {!!rows.length && <label className="printerCameraSelect"><span className="printerCameraLabel">Camera source</span><select value={selected} onChange={e => { setActiveCamera(""); setSelected(e.target.value); }}>{rows.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
      {!setupOnly && camera && <button type="button" disabled={!connection.enabled} onClick={() => setActiveCamera(playing ? "" : `${connection.id}:${camera.id}`)}>{playing ? "Stop camera" : "Watch camera"}</button>}
      {canEdit && !setupOnly && <button type="button" onClick={() => setSettings(!settings)}>{settings ? "Close setup" : "Camera setup"}</button>}
    </div>
    {!rows.length && <small>{connection.camera?.reported ? "The printer reports a camera. Configure a source to view it." : "Configure a camera source to view this printer."}</small>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="integrationError" role="alert">{error}</p>}
    {settings && canEdit && <form className="formGrid printerCameraForm" onSubmit={save}>
      <div className="full"><small>{provider?.guidance} If this printer exposes Moonraker or OctoPrint, you can also add that integration and configure its camera.</small></div>
      {warnings.map(message => <p className="full" role="status" key={message}>{message}</p>)}
      <div className="full settingsActions">{!!presets.length && <button type="button" disabled={busy} onClick={() => { setCandidates(presets); setWarnings([]); setNotice("K1 presets loaded. Choose the route that works in your printer installation."); }}>K1 / Helper Script presets</button>}<button type="button" disabled={busy || !connection.enabled} onClick={discover}>{busy ? "Working…" : "Find camera sources"}</button>{camera && <button type="button" disabled={busy} onClick={usePreview}>Use selected camera for previews</button>}{camera && <button type="button" disabled={busy} onClick={remove}>Remove selected source</button>}</div>
      {!!candidates.length && <label className="full">Discovered sources / presets<select value="" onChange={e => { const item = candidates[Number(e.target.value)]; if (item) setForm(item); }}><option value="" disabled>Choose a source to configure</option>{candidates.map((item, index) => <option key={item.id} value={index}>{item.name} · {LABELS[item.mode]}</option>)}</select><small>Presets are candidates; saving does not confirm playback.</small></label>}
      <label>Name<input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
      <label>Feed type<select value={form.mode} onChange={e => setForm({ ...form, mode: e.target.value })}><option value="snapshot">JPEG / PNG snapshot</option><option value="mjpeg">MJPEG (refreshed images)</option>{connection.adapter === "creality_local" && <option value="creality_webrtc">Creality WebRTC (experimental)</option>}</select></label>
      <label className="full">Camera URL<input required type="url" value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="http://printer-address:8080/?action=snapshot" /><small>Use the same host as this printer source. Include the camera port and path. Embedded usernames and passwords are unsupported.</small></label>
      <label>Rotation<select value={form.rotation} onChange={e => setForm({ ...form, rotation: Number(e.target.value) })}>{[0, 90, 180, 270].map(value => <option key={value} value={value}>{value}°</option>)}</select></label>
      <div className="printerCameraFlips"><label><input type="checkbox" checked={form.flip_horizontal} onChange={e => setForm({ ...form, flip_horizontal: e.target.checked })} /> Flip horizontally</label><label><input type="checkbox" checked={form.flip_vertical} onChange={e => setForm({ ...form, flip_vertical: e.target.checked })} /> Flip vertically</label></div>
      <div className="full settingsActions"><button className="primary" disabled={busy}>Save camera source</button></div>
    </form>}
    {!setupOnly && playing && <CameraPlayback key={camera.id} camera={camera} url={root + camera.id + "/media/"} />}
  </section>;
}

export function CameraPlayback({ camera, url, compact = false }) {
  const [expanded, setExpanded] = useState(false);
  const container = useRef(null);
  const video = useRef(null);
  const [image, setImage] = useState("");
  const [status, setStatus] = useState("Connecting…");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    let peer;
    let videoTimeout;
    let stopFrames;
    const controller = new AbortController();
    setImage(""); setError(""); setStatus("Connecting…");
    const closePeer = () => {
      if (peer) {
        peer.ontrack = null; peer.onconnectionstatechange = null;
        peer.getReceivers().forEach(receiver => receiver.track?.stop());
        peer.close();
      }
      if (video.current) video.current.srcObject = null;
    };
    const failed = message => { if (!cancelled) { setError(message); setStatus("Disconnected"); closePeer(); } };
    if (camera.mode !== "creality_webrtc") {
      stopFrames = startFrameLoop({
        request: signal => cameraRequest(async () => {
          const response = await fetch(url, { credentials: "same-origin", cache: "no-store", signal });
          if (!response.ok) { const result = await response.json().catch(() => ({})); throw new Error(result.error || "Camera unavailable. Check the source URL and printer connection."); }
          if (!/^image\/(jpeg|png)/.test(response.headers.get("Content-Type") || "")) throw new Error("Camera response was not an image. Sign in again if your session expired.");
          return response.blob();
        }, signal),
        onFrame: blob => {
          const next = URL.createObjectURL(blob);
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = next; setImage(next); setError(""); setStatus("Live images · approximately 1 frame/s");
        },
        onError: (err, retrying) => { setError(err.message); setImage(""); setStatus(retrying ? "Reconnecting…" : "Disconnected · select Reconnect to retry"); },
      });
    } else {
      (async () => {
        try {
          if (!globalThis.RTCPeerConnection) throw new Error("This browser does not support WebRTC camera playback.");
          peer = new RTCPeerConnection({ iceServers: [] });
          const transceiver = peer.addTransceiver("video", { direction: "recvonly" });
          const codecs = RTCRtpReceiver.getCapabilities("video")?.codecs.filter(codec => codec.mimeType.toLowerCase() === "video/h264") || [];
          if (!codecs.length) throw new Error("This browser has no H.264 WebRTC decoder.");
          if (transceiver.setCodecPreferences) transceiver.setCodecPreferences(codecs.slice(0, 1));
          peer.ontrack = event => {
            if (cancelled || event.track.kind !== "video" || !video.current) return;
            video.current.srcObject = event.streams[0] || new MediaStream([event.track]);
            video.current.play().catch(() => failed("Playback was blocked. Use the video play control or reconnect."));
          };
          peer.onconnectionstatechange = () => {
            if (cancelled) return;
            if (peer.connectionState === "connected") setStatus("Connected · waiting for video");
            if (["failed", "disconnected"].includes(peer.connectionState)) failed("Camera connection lost. Check LAN/VPN access, then reconnect.");
          };
          await peer.setLocalDescription(await peer.createOffer());
          await waitForIce(peer, controller.signal);
          if (cancelled) return;
          const answer = await cameraRequest(() => apiFetch(url, { method: "POST", signal: controller.signal, body: { sdp: prepareCrealityOffer(peer.localDescription.sdp) } }), controller.signal);
          if (cancelled) return;
          await peer.setRemoteDescription(answer);
          videoTimeout = setTimeout(() => { if (!cancelled && (video.current?.readyState || 0) < 2) failed("No camera video arrived. Your browser must reach the printer over LAN/VPN; HTTPS access to MakerVault alone does not relay WebRTC video."); }, 20000);
        } catch (err) { if (err.name !== "AbortError") failed(err.message); }
      })();
    }
    return () => { cancelled = true; controller.abort(); clearTimeout(videoTimeout); stopFrames?.(); closePeer(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [camera.id, url, attempt]);
  useEffect(() => {
    if (!expanded) return;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const escape = event => { if (event.key === "Escape") setExpanded(false); };
    document.addEventListener("keydown", escape);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener("keydown", escape); };
  }, [expanded]);
  const fullscreen = () => {
    if (expanded) { setExpanded(false); return; }
    const target = container.current;
    if (target?.requestFullscreen) target.requestFullscreen().catch(() => setExpanded(true));
    else if (video.current?.webkitEnterFullscreen) { try { video.current.webkitEnterFullscreen(); } catch { setExpanded(true); } }
    else setExpanded(true);
  };
  const fit = Number(camera.rotation || 0) % 180 ? 9 / 16 : 1;
  const transform = `rotate(${camera.rotation || 0}deg) scale(${(camera.flip_horizontal ? -1 : 1) * fit}, ${(camera.flip_vertical ? -1 : 1) * fit})`;
  return <div className={"printerCameraPlayback" + (compact ? " cameraGlance" : "") + (expanded ? " cameraExpanded" : "")} ref={container}>
    <div className="printerCameraToolbar">
      {!compact && <small role="status">{status}</small>}
      {(!compact || error) && <button type="button" onClick={() => setAttempt(value => value + 1)}>Reconnect</button>}
      <button type="button" className="cameraFullscreen" aria-label={expanded ? "Close fullscreen camera" : "Open fullscreen camera"} onClick={fullscreen}>{expanded ? "Close" : "Fullscreen"}</button>
    </div>
    <div className="printerCameraViewport">
      {camera.mode === "creality_webrtc" ? <video ref={video} style={{ transform }} autoPlay muted playsInline controls={!compact} onPlaying={() => setStatus("Live video · experimental")} /> : image ? <img src={image} alt={camera.name + " live camera view"} style={{ transform }} /> : <span role="status">{status}</span>}
    </div>
    {error && <p className="integrationError" role="alert">{error}</p>}
    {!compact && <small>{LABELS[camera.mode]}{camera.mode === "creality_webrtc" ? " · Browser needs LAN/VPN access to the printer." : " · Images are relayed securely through your MakerVault session."}</small>}
  </div>;
}
