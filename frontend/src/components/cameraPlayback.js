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
