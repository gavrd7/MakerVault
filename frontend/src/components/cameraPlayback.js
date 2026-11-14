export function cameraHlsUrl(mediaUrl = "") {
  return String(mediaUrl).replace(/media\/$/, "hls/master.m3u8");
}

export function startFrameLoop({ request, onFrame, onError, interval = 1000 }) {
  const controller = new AbortController();
  let stopped = false;
  let timer;
  let failures = 0;
  const tick = async () => {
    try {
      const frame = await request(controller.signal);
      if (stopped) return;
      failures = 0;
      onFrame(frame);
      timer = setTimeout(tick, interval);
    } catch (error) {
      if (stopped || error.name === "AbortError") return;
      failures += 1;
      onError(error, failures < 3);
      if (failures < 3) timer = setTimeout(tick, interval * 3);
    }
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); controller.abort(); };
}

// Serialise frame/signalling requests across visible feeds in this tab. The
// server keeps its per-user request guard; parallel previews must not fight it.
let cameraQueue = Promise.resolve();
export function cameraRequest(task, signal) {
  const result = cameraQueue.then(() => {
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    return task();
  });
  cameraQueue = result.catch(() => {});
  return result;
}

export function defaultCamera(connections = []) {
  const available = connections.filter(item => item.enabled && item.camera?.preview);
  available.sort((a, b) => String(b.camera.configured_at || "").localeCompare(String(a.camera.configured_at || "")));
  const connection = available[0];
  return connection ? { connectionId: connection.id, camera: connection.camera.preview } : null;
}

// hls.js 1.7 can lose its MediaSource on iOS Safari when a camera
// preview is detached or resumed. Native HLS is the recovery path, not
// the initial path: some Creality relays require hls.js to start reliably.
export function shouldFallbackToNativeHls(error, nativeHlsAvailable) {
  return Boolean(nativeHlsAvailable && error?.details === "mediaSourceRequiresReset");
}

export function isAutoplayBlocked(error) {
  return error?.name === "NotAllowedError";
}

/**
 * Distinguish a playing media element from one that has actually decoded a
 * frame. Safari may fire "playing" for an HLS playlist with no visible video.
 * requestVideoFrameCallback is the strongest signal when the browser has it.
 */
export function videoFrameHealth(video, renderedFrames = 0) {
  if (!video) return { hasFrame: false, width: 0, height: 0, readyState: 0, time: 0, buffered: 0, decoded: 0 };
  const width = Number(video.videoWidth) || 0;
  const height = Number(video.videoHeight) || 0;
  const readyState = Number(video.readyState) || 0;
  const time = Number(video.currentTime) || 0;
  let buffered = 0;
  try {
    if (video.buffered?.length) buffered = Math.max(0, Number(video.buffered.end(video.buffered.length - 1)) - time);
  } catch { /* media buffer may change while being read */ }
  let decoded = Number(renderedFrames) || 0;
  try {
    decoded = Math.max(decoded, Number(video.getVideoPlaybackQuality?.().totalVideoFrames) || 0);
  } catch { /* unsupported on some Safari versions */ }
  decoded = Math.max(decoded, Number(video.webkitDecodedFrameCount) || 0);
  const frameCallbackSupported = typeof video.requestVideoFrameCallback === "function";
  return {
    hasFrame: frameCallbackSupported ? renderedFrames > 0 : decoded > 0 || (width > 0 && height > 0 && readyState >= 2),
    width, height, readyState, time, buffered, decoded,
  };
}

export function videoFrameDiagnostic(health, mode) {
  return `Mode: ${mode || "unknown"}; decoded: ${health.decoded}; size: ${health.width}×${health.height}; ready: ${health.readyState}; time: ${health.time.toFixed(1)}s; buffer: ${health.buffered.toFixed(1)}s.`;
}
