// Browser-independent WebRTC receiver for camera sources backed by go2rtc.
// No printer-specific signalling or camera URLs enter the browser.
export function cameraWebRTCOfferUrl(mediaUrl = "") {
  return String(mediaUrl).replace(/media\/$/, "webrtc/offer/");
}

export function waitForIceGathering(peer, timeoutMs = 4500) {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => finish(), timeoutMs);
    function finish() {
      clearTimeout(timer);
      peer.removeEventListener("icegatheringstatechange", changed);
      resolve(); // Bounded wait; best available SDP still gets attempted.
    }
    function changed() {
      if (peer.iceGatheringState === "complete") finish();
    }
    peer.addEventListener("icegatheringstatechange", changed);
  });
}

export async function connectCameraWebRTC({ mediaUrl, video, signal, onState, exchange }) {
  if (typeof RTCPeerConnection === "undefined" || !window.isSecureContext) {
    throw new Error("WebRTC requires a supported browser and HTTPS or a trusted local origin.");
  }
  const peer = new RTCPeerConnection({ iceServers: [], bundlePolicy: "max-bundle" });
  let attached = false;
  const close = () => {
    peer.ontrack = null;
    peer.onconnectionstatechange = null;
    peer.close();
    if (video.srcObject) video.srcObject = null;
  };
  const aborted = () => close();
  signal?.addEventListener("abort", aborted, { once: true });
  try {
    peer.ontrack = event => {
      if (signal?.aborted) return;
      const stream = event.streams?.[0] || new MediaStream([event.track]);
      video.srcObject = stream;
      attached = true;
      video.play().catch(error => {
        if (error.name !== "NotAllowedError" && error.name !== "AbortError") onState?.("playback-error");
      });
    };
    peer.onconnectionstatechange = () => onState?.(peer.connectionState);
    peer.addTransceiver("video", { direction: "recvonly" });
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    await waitForIceGathering(peer);
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    const answer = await exchange(cameraWebRTCOfferUrl(mediaUrl), peer.localDescription.sdp, signal);
    if (!answer?.sdp || answer.type !== "answer") throw new Error("The camera did not return a WebRTC answer.");
    await peer.setRemoteDescription({ type: "answer", sdp: answer.sdp });
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    onState?.(peer.connectionState);
    return { peer, close, hasVideoTrack: () => attached };
  } catch (error) {
    close();
    throw error;
  } finally {
    // Also removed during the effect's cleanup when this receiver is closed.
    if (!signal?.aborted) signal?.removeEventListener("abort", aborted);
  }
}
