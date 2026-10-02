export function waitForIce(peer, signal, timeoutMs = 8000) {
  if (signal.aborted) return Promise.reject(new DOMException("Cancelled", "AbortError"));
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const finish = error => {
      clearTimeout(timer);
      peer.removeEventListener("icegatheringstatechange", changed);
      signal.removeEventListener("abort", aborted);
      error ? reject(error) : resolve();
    };
    const changed = () => { if (peer.iceGatheringState === "complete") finish(); };
    const aborted = () => finish(new DOMException("Cancelled", "AbortError"));
    const timer = setTimeout(() => finish(), timeoutMs);
    peer.addEventListener("icegatheringstatechange", changed);
    signal.addEventListener("abort", aborted, { once: true });
  });
}

export function prepareCrealityOffer(sdp) {
  // Older firmware expects numeric ICE addresses; peer-reflexive ICE learns the LAN route.
  return sdp.split("\r\n").map(line => {
    if (!line.startsWith("a=candidate:")) return line;
    const fields = line.split(" ");
    if (fields[4]?.endsWith(".local")) fields[4] = "192.0.2.1";
    return fields.join(" ");
  }).join("\r\n");
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

// Serialise requests per printer connection. An offline/retrying printer must
// not starve a healthy camera on another printer in the same tab.
const cameraQueues = new Map();
export function cameraRequest(task, signal, queueKey = "default") {
  const key = String(queueKey || "default");
  const previous = cameraQueues.get(key) || Promise.resolve();
  const result = previous.then(() => {
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    return task();
  });
  const tail = result.catch(() => {});
  cameraQueues.set(key, tail);
  tail.then(() => {
    if (cameraQueues.get(key) === tail) cameraQueues.delete(key);
  });
  return result;
}

export function defaultCamera(connections = []) {
  const available = connections.filter(item => item.enabled && item.camera?.preview);
  available.sort((a, b) => String(b.camera.configured_at || "").localeCompare(String(a.camera.configured_at || "")));
  const connection = available[0];
  return connection ? { connectionId: connection.id, camera: connection.camera.preview } : null;
}
