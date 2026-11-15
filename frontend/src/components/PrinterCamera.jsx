import React, { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { connectCameraWebRTC } from "./cameraWebRTC";
import { apiFetch } from "../api";
import { startFrameLoop, cameraRequest, cameraHlsUrl, shouldFallbackToNativeHls, videoFrameHealth, videoFrameDiagnostic, isIOSWebKit } from "./cameraPlayback";

function endpointLabel(url) {
  try {
    const parsed = new URL(url);
    const action = parsed.searchParams.get("action");
    return `${parsed.host}${parsed.pathname}${action ? `?action=${action}` : ""}`;
  } catch {
    return "Configured endpoint";
  }
}

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
  const [removeArmedId, setRemoveArmedId] = useState("");
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
      await load(); await onChanged(); setNotice("Camera source saved or updated. Open the printer camera preview to watch."); setSettings(setupOnly);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function usePreview(cameraId = camera?.id) {
    if (!cameraId) return;
    setBusy(true); setError("");
    try {
      await apiFetch(root, { method: "PATCH", body: { id: cameraId } });
      setSelected(cameraId);
      await onChanged(); setNotice("Preview camera updated on the dashboard and 3D Printing page.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function remove(cameraId = camera?.id) {
    const item = rows.find(row => row.id === cameraId);
    if (!item) return;
    if (removeArmedId !== cameraId) {
      setRemoveArmedId(cameraId);
      setNotice(`Click Confirm remove to delete “${item.name}” (${endpointLabel(item.url)}).`);
      return;
    }
    setBusy(true); setError(""); setNotice("");
    if (activeCamera === `${connection.id}:${cameraId}`) setActiveCamera("");
    try {
      const result = await apiFetch(root + cameraId + "/remove/", { method: "POST", body: {} });
      setRows(result.rows || []);
      setRemoveArmedId("");
      if (selected === cameraId) setSelected((result.rows || [])[0]?.id || "");
      await onChanged();
      setNotice(`Camera source “${item.name}” removed.`);
    }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <section className="printerCamera">
    <div className="printerCameraToolbar">
      <strong>Camera</strong>
      {!!rows.length && <label className="printerCameraSelect"><span className="printerCameraLabel">Camera source</span><select value={selected} onChange={e => { setActiveCamera(""); setSelected(e.target.value); }}>{rows.map(item => <option key={item.id} value={item.id}>{item.name} · {LABELS[item.mode] || item.mode} · {endpointLabel(item.url)}</option>)}</select></label>}
      {!setupOnly && camera && <button type="button" disabled={!connection.enabled} onClick={() => setActiveCamera(playing ? "" : `${connection.id}:${camera.id}`)}>{playing ? "Stop camera" : "Watch camera"}</button>}
      {canEdit && !setupOnly && <button type="button" onClick={() => setSettings(!settings)}>{settings ? "Close setup" : "Camera setup"}</button>}
    </div>
    {!rows.length && <small>{connection.camera?.reported ? "The printer reports a camera. Configure a source to view it." : "Configure a camera source to view this printer."}</small>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="integrationError" role="alert">{error}</p>}
    {settings && canEdit && <form className="formGrid printerCameraForm" onSubmit={save}>
      <div className="full printerCameraGuidance"><small>{provider?.guidance || "Choose a camera source below, or enter its URL manually."}</small></div>
      {warnings.map(message => <p className="full" role="status" key={message}>{message}</p>)}
      <div className="full settingsActions printerCameraDiscoveryActions">{!!presets.length && <button type="button" disabled={busy} onClick={() => { setCandidates(presets); setWarnings([]); setNotice("Camera presets loaded. For a clean K1 installation, try Creality native WebRTC first; older MJPEG routes may require additional software."); }}>Camera presets</button>}<button type="button" disabled={busy || !connection.enabled} onClick={discover}>{busy ? "Working…" : "Find camera sources"}</button></div>
      {!!rows.length && <div className="full cameraSavedSources">
        <strong>Saved camera sources</strong>
        {rows.map(item => <div className="cameraSourceRow" key={item.id}>
          <div className="cameraSourceIdentity">
            <div><strong>{item.name}</strong>{connection.camera?.preview?.id === item.id && <span className="badge badge-good">Preview</span>}</div>
            <small>{LABELS[item.mode] || item.mode}</small>
            <code>{endpointLabel(item.url)}</code>
          </div>
          <div className="cameraSourceActions">
            <button type="button" disabled={busy} onClick={() => usePreview(item.id)}>Use for previews</button>
            <button
              type="button"
              className="dangerButton"
              disabled={busy}
              onClick={() => remove(item.id)}
            >{removeArmedId === item.id ? "Confirm remove" : "Remove"}</button>
            {removeArmedId === item.id && <button type="button" disabled={busy} onClick={() => { setRemoveArmedId(""); setNotice(""); }}>Cancel</button>}
          </div>
        </div>)}
      </div>}
      {!!candidates.length && <label className="full">Discovered sources / presets<select value="" onChange={e => { const item = candidates[Number(e.target.value)]; if (item) setForm(item); }}><option value="" disabled>Choose a source to configure</option>{candidates.map((item, index) => <option key={item.id} value={index}>{item.name} · {LABELS[item.mode]} · {endpointLabel(item.url)}</option>)}</select><small>Presets are candidates; saving does not confirm playback.</small></label>}
      <label>Name<input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
      <label>Feed type<select value={form.mode} onChange={e => setForm({ ...form, mode: e.target.value })}><option value="snapshot">JPEG / PNG snapshot</option><option value="mjpeg">MJPEG (refreshed images)</option>{connection.adapter === "creality_local" && <option value="creality_webrtc">Creality WebRTC (experimental)</option>}</select></label>
      <label className="full">Camera URL<input required type="url" value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="http://printer-address:8080/?action=snapshot" /><small>Use the same host as this printer source. Include the camera port and path. Embedded usernames and passwords are unsupported.</small></label>
      <label>Rotation<select value={form.rotation} onChange={e => setForm({ ...form, rotation: Number(e.target.value) })}>{[0, 90, 180, 270].map(value => <option key={value} value={value}>{value}°</option>)}</select></label>
      <div className="printerCameraFlips"><label><input type="checkbox" checked={form.flip_horizontal} onChange={e => setForm({ ...form, flip_horizontal: e.target.checked })} /> Flip horizontally</label><label><input type="checkbox" checked={form.flip_vertical} onChange={e => setForm({ ...form, flip_vertical: e.target.checked })} /> Flip vertically</label></div>
      <div className="full settingsActions printerCameraSaveActions"><button className="primary" disabled={busy}>Save camera source</button></div>
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
  const [transport, setTransport] = useState("webrtc");
  const [playbackBlocked, setPlaybackBlocked] = useState(false);
  const [playbackDiagnostic, setPlaybackDiagnostic] = useState("");
  const [capturedFrame, setCapturedFrame] = useState("");
  const [captureInfo, setCaptureInfo] = useState("");
  const nativeRecovery = useRef(false);
  const frameSeen = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    let stopFrames;
    let hls;
    let frameWatch;
    let frameCallbackId;
    let frameCallbackTarget;
    let reportedMissingFrames = false;
    nativeRecovery.current = false;
    frameSeen.current = false;
    const cancelFrameCallback = () => {
      if (frameCallbackId != null && frameCallbackTarget?.cancelVideoFrameCallback) {
        frameCallbackTarget.cancelVideoFrameCallback(frameCallbackId);
      }
      frameCallbackId = undefined;
      frameCallbackTarget = undefined;
    };
    const observeVideo = target => {
      clearInterval(frameWatch);
      cancelFrameCallback();
      frameSeen.current = false;
      reportedMissingFrames = false;
      const startedAt = Date.now();
      const mode = nativeRecovery.current ? "native HLS" : "hls.js";
      if (typeof target.requestVideoFrameCallback === "function") {
        frameCallbackTarget = target;
        frameCallbackId = target.requestVideoFrameCallback(() => {
          if (cancelled) return;
          frameSeen.current = true;
          setPlaybackDiagnostic(nativeRecovery.current ? "Native HLS: decoded video frame confirmed" : "");
          setError("");
          setStatus("Live video · relayed through MakerVault");
        });
      }
      frameWatch = setInterval(() => {
        if (cancelled || frameSeen.current) { clearInterval(frameWatch); return; }
        const health = videoFrameHealth(target);
        // Frame callback confirms an actual presentation where available.
        if (typeof target.requestVideoFrameCallback !== "function" && health.hasFrame) {
          frameSeen.current = true;
          setPlaybackDiagnostic(nativeRecovery.current ? "Native HLS: decoded frames confirmed" : "");
          setError("");
          setStatus("Live video · relayed through MakerVault");
          clearInterval(frameWatch);
        } else if (!reportedMissingFrames && Date.now() - startedAt >= 8000 && !playbackBlocked) {
          reportedMissingFrames = true;
          setStatus("Video started but no decoded frame confirmed");
          setPlaybackDiagnostic(videoFrameDiagnostic(health, mode) + " No presented video frame confirmed.");
        }
      }, 1000);
    };
    const controller = new AbortController();
    setImage(""); setError(""); setStatus("Connecting…"); setPlaybackBlocked(false); setPlaybackDiagnostic(""); setCapturedFrame(""); setCaptureInfo("");

    const failed = message => {
      if (cancelled) return;
      setError(message);
      setStatus("Disconnected · select Reconnect to retry");
      if (video.current) {
        video.current.pause();
        video.current.removeAttribute("src");
        video.current.load();
      }
    };

    const attemptAutoplay = target => {
      target.play().catch(reason => {
        if (cancelled || reason?.name === "AbortError") return;
        if (reason?.name === "NotAllowedError") {
          // Do not detach an intact HLS stream on a browser autoplay denial.
          setPlaybackBlocked(true);
          setStatus("Tap Start video to allow playback.");
          return;
        }
        failed("Camera playback failed. Select Reconnect to retry.");
      });
    };

    if (camera.mode === "creality_webrtc" && transport === "webrtc") {
      const target = video.current;
      let receiver;
      let connectionWatch;
      let frameWatch;
      let frameCallbackId;
      let frameReceived = false;
      const receivedFrame = () => {
        if (cancelled) return;
        frameReceived = true;
        clearTimeout(connectionWatch);
        setStatus("Live · WebRTC");
        setError("");
        setPlaybackDiagnostic("");
      };
      const fallback = message => {
        if (cancelled) return;
        setPlaybackDiagnostic(message);
        setTransport("hls");
      };
      if (!target) {
        fallback("WebRTC video element unavailable; using compatibility playback.");
      } else {
        setStatus("Connecting low-latency WebRTC…");
        if (typeof target.requestVideoFrameCallback === "function") {
          frameCallbackId = target.requestVideoFrameCallback(receivedFrame);
        }
        frameWatch = setInterval(() => {
          if (cancelled || frameReceived || typeof target.requestVideoFrameCallback === "function") return;
          const health = videoFrameHealth(target);
          if (health.hasFrame) receivedFrame();
        }, 700);
        connectCameraWebRTC({
          mediaUrl: url,
          video: target,
          signal: controller.signal,
          exchange: (path, sdp, signal) => apiFetch(path, { method: "POST", body: { sdp }, signal }),
          onState: state => {
            if (cancelled) return;
            if (state === "connected") {
              setStatus(frameReceived ? "Live · WebRTC" : "WebRTC connected · waiting for first video frame");
            } else if (state === "failed" || state === "playback-error") {
              fallback("WebRTC connection failed; trying compatibility playback.");
            }
          },
        }).then(result => {
          if (cancelled) { result.close(); return; }
          receiver = result;
        }).catch(error => {
          if (cancelled || error?.name === "AbortError") return;
          fallback("WebRTC unavailable; trying compatibility playback.");
        });
        // Do not wait indefinitely for unreachable Docker/ICE candidates.
        connectionWatch = setTimeout(() => {
          if (!frameReceived) fallback("WebRTC video did not deliver a frame; using compatibility playback.");
        }, 15000);
      }
      return () => {
        cancelled = true;
        controller.abort();
        clearTimeout(connectionWatch);
        clearInterval(frameWatch);
        if (frameCallbackId != null && target?.cancelVideoFrameCallback) target.cancelVideoFrameCallback(frameCallbackId);
        receiver?.close();
      };
    }

    if (camera.mode !== "creality_webrtc") {
      stopFrames = startFrameLoop({
        request: signal => cameraRequest(async () => {
          const response = await fetch(url, { credentials: "same-origin", cache: "no-store", signal });
          if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            throw new Error(result.error || "Camera unavailable. Check the source URL and printer connection.");
          }
          if (!/^image\/(jpeg|png)/.test(response.headers.get("Content-Type") || "")) {
            throw new Error("Camera response was not an image. Sign in again if your session expired.");
          }
          return response.blob();
        }, signal),
        onFrame: blob => {
          const next = URL.createObjectURL(blob);
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = next;
          setImage(next);
          setError("");
          setStatus("Live images · approximately 1 frame/s");
        },
        onError: (err, retrying) => {
          setError(err.message);
          setImage("");
          setStatus(retrying ? "Reconnecting…" : "Disconnected · select Reconnect to retry");
        },
      });
    } else {
      const target = video.current;
      // Use native MPEG-TS HLS on iOS WebKit. go2rtc's fragmented MP4 init
      // can contain placeholder 128x96 SPS metadata for this Creality source.
      // Preserve the established fMP4/hls.js path on desktop and Android.
      const iosWebKit = isIOSWebKit(navigator.userAgent, navigator.platform, navigator.maxTouchPoints);
      const source = cameraHlsUrl(url) + (iosWebKit ? "?format=ts" : "");
      if (!target) {
        failed("Camera video element is unavailable.");
      } else {
        const playingHandler = () => observeVideo(target);
        target.addEventListener("playing", playingHandler);
        // Removed during effect cleanup; retains one watcher per player.
        controller.signal.addEventListener("abort", () => target.removeEventListener("playing", playingHandler), { once: true });
      }
      if (target && iosWebKit && target.canPlayType("application/vnd.apple.mpegurl")) {
        setStatus("Connecting using native iOS HLS…");
        target.src = source;
        attemptAutoplay(target);
      } else if (target && Hls.isSupported()) {
        hls = new Hls({
          enableWorker: true,
          lowLatencyMode: false,
          maxBufferLength: 12,
          backBufferLength: 6,
        });
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          if (cancelled) return;
          setStatus("Connected · waiting for video");
          attemptAutoplay(target);
        });
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (cancelled || !data?.fatal) return;
          // Do not label every fatal HLS playback error as a disconnected
          // printer. Expose the safe hls.js classification without URLs,
          // credentials, media payloads, or other response content.
          const type = String(data.type || "unknown").slice(0, 64);
          const detail = String(data.details || "unknown").slice(0, 96);
          const code = Number(data.response?.code);
          const status = Number.isInteger(code) && code >= 100 && code <= 599 ? " · HTTP " + code : "";
          const diagnostic = "HLS: " + type + " / " + detail + status;
          if (!nativeRecovery.current && shouldFallbackToNativeHls(data, Boolean(target.canPlayType("application/vnd.apple.mpegurl")))) {
            // Safari can invalidate the MediaSource managed by hls.js when a
            // preview is detached. Release its attachment before switching to
            // the browser's native HLS pipeline; do not change the relay URL.
            nativeRecovery.current = true;
            setPlaybackDiagnostic(diagnostic + " · trying native HLS");
            setStatus("Recovering video with native HLS…");
            clearInterval(frameWatch);
            cancelFrameCallback();
            hls?.destroy();
            hls = null;
            target.pause();
            target.removeAttribute("src");
            target.load();
            target.src = source;
            attemptAutoplay(target);
            return;
          }
          setPlaybackDiagnostic(diagnostic);
          failed("Camera video playback failed. Select Reconnect to retry.");
        });
        hls.loadSource(source);
        hls.attachMedia(target);
      } else if (target?.canPlayType("application/vnd.apple.mpegurl")) {
        target.src = source;
        attemptAutoplay(target);
      } else if (target) {
        failed("This browser cannot play the MakerVault camera relay.");
      }
    }

    return () => {
      cancelled = true;
      controller.abort();
      stopFrames?.();
      clearInterval(frameWatch);
      cancelFrameCallback();
      hls?.destroy();
      if (video.current) {
        video.current.pause();
        video.current.removeAttribute("src");
        video.current.load();
      }
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [camera.id, url, attempt, transport]);

  useEffect(() => {
    if (!expanded) return;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const escape = event => { if (event.key === "Escape") setExpanded(false); };
    document.addEventListener("keydown", escape);
    return () => {
      document.body.style.overflow = oldOverflow;
      document.removeEventListener("keydown", escape);
    };
  }, [expanded]);

  const fullscreen = () => {
    if (expanded) { setExpanded(false); return; }
    const target = container.current;
    if (target?.requestFullscreen) target.requestFullscreen().catch(() => setExpanded(true));
    else if (video.current?.webkitEnterFullscreen) {
      try { video.current.webkitEnterFullscreen(); } catch { setExpanded(true); }
    } else setExpanded(true);
  };

  const inspectFrame = () => {
    const target = video.current;
    if (!target || !target.videoWidth || !target.videoHeight) {
      setCaptureInfo("No video dimensions are available to capture.");
      return;
    }
    try {
      const canvas = document.createElement("canvas");
      canvas.width = target.videoWidth;
      canvas.height = target.videoHeight;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("Canvas unavailable");
      context.drawImage(target, 0, 0, canvas.width, canvas.height);
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let total = 0, bright = 0, samples = 0;
      for (let i = 0; i < pixels.length; i += 16) {
        const luma = Math.round(0.2126 * pixels[i] + 0.7152 * pixels[i + 1] + 0.0722 * pixels[i + 2]);
        total += luma;
        if (luma > 24) bright++;
        samples++;
      }
      setCapturedFrame(canvas.toDataURL("image/png"));
      setCaptureInfo(`Captured ${canvas.width}×${canvas.height} video frame · average brightness ${(total / samples).toFixed(1)}/255 · non-dark pixels ${(100 * bright / samples).toFixed(1)}%.`);
    } catch (err) {
      setCapturedFrame("");
      setCaptureInfo(`Video frame capture unavailable (${err?.name || "error"}).`);
    }
  };

  const fit = Number(camera.rotation || 0) % 180 ? 9 / 16 : 1;
  const transform = `rotate(${camera.rotation || 0}deg) scale(${(camera.flip_horizontal ? -1 : 1) * fit}, ${(camera.flip_vertical ? -1 : 1) * fit})`;

  return <div className={"printerCameraPlayback" + (compact ? " cameraGlance" : "") + (expanded ? " cameraExpanded" : "")} ref={container}>
    <div className="printerCameraToolbar">
      {!compact && error && <small role="status">{status}</small>}
      {playbackBlocked && camera.mode === "creality_webrtc" && <button type="button" onClick={() => { const target = video.current; if (!target) return; target.play().then(() => { setPlaybackBlocked(false); setError(""); }).catch(reason => { if (reason?.name !== "NotAllowedError") setError("Video could not start. Select Reconnect."); }); }}>Start video</button>}
      {error && <button type="button" onClick={() => { setTransport("webrtc"); setAttempt(value => value + 1); }}>Retry video</button>}
      {camera.mode === "creality_webrtc" && error && <button type="button" onClick={inspectFrame}>Inspect frame</button>}
      {camera.mode !== "creality_webrtc" && <button type="button" className="cameraFullscreen" aria-label={expanded ? "Close fullscreen camera" : "Open fullscreen camera"} onClick={fullscreen}>{expanded ? "Close" : "Fullscreen"}</button>}
    </div>
    <div className="printerCameraViewport">
      {camera.mode === "creality_webrtc"
        ? <video ref={video} style={{ transform }} autoPlay muted playsInline controls={!compact}
            onError={event => {
              const code = Number(event.currentTarget.error?.code || 0);
              if (code) {
                setPlaybackDiagnostic(previous => (nativeRecovery.current ? "Native HLS video element error " + code + " after mediaSourceRequiresReset" : previous || "Video element error " + code + " (1=aborted, 2=network, 3=decode, 4=unsupported)"));
                if (nativeRecovery.current) {
                  setError("Native HLS recovery failed. Select Reconnect to retry.");
                  setStatus("Disconnected · select Reconnect to retry");
                }
              }
            }}
            onPlaying={() => { setPlaybackBlocked(false); setError(""); setStatus(transport === "webrtc" ? "WebRTC playing · checking first frame…" : "Video playing · checking decoded frames…"); }} />
        : image
          ? <img src={image} alt={camera.name + " live camera view"} style={{ transform }} />
          : <span role="status">{status}</span>}
    </div>
    {error && <p className="integrationError" role="alert">{error}</p>}
    {captureInfo && <small role="status" style={{ display: "block", padding: "4px 10px", overflowWrap: "anywhere" }}>{captureInfo}</small>}
    {capturedFrame && <img src={capturedFrame} alt="Captured video frame for camera diagnosis" style={{ display: "block", width: "min(100%, 320px)", margin: "8px auto" }} />}
    {playbackDiagnostic && <small role="status" style={{ display: "block", padding: "4px 10px", overflowWrap: "anywhere" }}>{playbackDiagnostic}</small>}
    {playbackBlocked && <small role="status">Safari requires you to start video playback manually.</small>}
  </div>;
}
