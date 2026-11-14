import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { startFrameLoop, cameraHlsUrl, shouldFallbackToNativeHls, isAutoplayBlocked } from "../src/components/cameraPlayback.js";

test("closing frame viewer aborts in-flight fetch and ignores late frame", async () => {
  let resolve;
  let signal;
  let calls = 0;
  const stop = startFrameLoop({ request: value => { signal = value; return new Promise(done => { resolve = done; }); }, onFrame: () => { calls++; }, onError: () => { calls++; }, interval: 1 });
  stop();
  assert.equal(signal.aborted, true);
  resolve("late frame");
  await new Promise(done => setTimeout(done, 10));
  assert.equal(calls, 0);
});

test("frame reconnect stops after three failures", { timeout: 1000 }, async () => {
  let calls = 0;
  const errors = [];
  let done;
  const finished = new Promise(resolve => { done = resolve; });
  const stop = startFrameLoop({ request: async () => { calls++; throw new Error("offline"); }, onFrame: () => {}, onError: (_err, retrying) => { errors.push(retrying); if (!retrying) done(); }, interval: 1 });
  await finished;
  stop();
  assert.equal(calls, 3);
  assert.deepEqual(errors, [true, true, false]);
});

test("Creality relay uses a same-origin HLS endpoint", () => {
  assert.equal(
    cameraHlsUrl("/api/printing/printers/p/connections/c/cameras/k2/media/"),
    "/api/printing/printers/p/connections/c/cameras/k2/hls/master.m3u8",
  );
});

test('multiple visible feeds serialise media work and cancelled queued work never starts', async () => {
  const { cameraRequest } = await import('../src/components/cameraPlayback.js');
  const events = [];
  let release;
  const first = cameraRequest(async () => { events.push('first'); await new Promise(resolve => { release = resolve; }); events.push('done'); });
  await new Promise(resolve => setTimeout(resolve, 0));
  const controller = new AbortController();
  const skipped = cameraRequest(() => events.push('cancelled task ran'), controller.signal);
  const rejection = assert.rejects(skipped, { name: 'AbortError' });
  const second = cameraRequest(() => events.push('second'));
  controller.abort();
  assert.deepEqual(events, ['first']);
  release();
  await Promise.all([first, rejection, second]);
  assert.deepEqual(events, ['first', 'done', 'second']);
});

test('preview chooses most recently configured enabled camera across integrations', async () => {
  const { defaultCamera } = await import('../src/components/cameraPlayback.js');
  const rows = [
    { id: 'older', enabled: true, camera: { configured_at: '2026-10-01T10:00:00', preview: { id: 'a' } } },
    { id: 'newer', enabled: true, camera: { configured_at: '2026-10-02T10:00:00', preview: { id: 'b' } } },
    { id: 'disabled', enabled: false, camera: { configured_at: '2026-10-03T10:00:00', preview: { id: 'c' } } },
  ];
  assert.deepEqual(defaultCamera(rows), { connectionId: 'newer', camera: { id: 'b' } });
  assert.equal(rows[0].id, 'older');
  assert.equal(defaultCamera([]), null);
});


test("video autoplay rejection keeps the stream attached and exposes native play", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  const gesture = source.slice(source.indexOf("const needsGesture ="), source.indexOf("const failed ="));
  assert.match(gesture, /setPlaybackBlocked\(true\)/);
  assert.doesNotMatch(gesture, /removeAttribute|\.load\(\)|failed\(/);
  assert.match(source, /target\.play\(\)\.catch\(needsGesture\)/);
  assert.doesNotMatch(source, /Playback was blocked\. Use the video play control or reconnect/);
  assert.match(source, /autoPlay muted playsInline controls onPlaying/);
  assert.match(source, /camera\.mode !== "creality_webrtc" && <button[^\n]*cameraFullscreen/);
});
test("hls.js is preferred and Safari MediaSource reset falls back to native HLS", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  assert.ok(source.indexOf("} else if (Hls.isSupported())") < source.indexOf('} else if (target.canPlayType("application/vnd.apple.mpegurl"))'));
  assert.match(source, /shouldFallbackToNativeHls\(data/);
  assert.match(source, /hls\?\.destroy\(\)/);
  assert.match(source, /playbackMode = "native"/);
  assert.match(source, /data\.type === Hls\.ErrorTypes\.NETWORK_ERROR && relayRetries\.current < 2/);
  assert.match(source, /clearTimeout\(retryTimer\)/);
  assert.match(source, /relayRetries\.current = 0; setPlaybackBlocked\(false\)/);
});

test("only MediaSource reset on a browser with native HLS triggers fallback", () => {
  assert.equal(shouldFallbackToNativeHls({ details: "mediaSourceRequiresReset", fatal: false }, true), true);
  assert.equal(shouldFallbackToNativeHls({ details: "mediaSourceRequiresReset" }, false), false);
  assert.equal(shouldFallbackToNativeHls({ details: "bufferStalledError", fatal: true }, true), false);
  assert.equal(shouldFallbackToNativeHls(null, true), false);
});

test("only a genuine autoplay policy rejection prompts for a user gesture", () => {
  assert.equal(isAutoplayBlocked({ name: "NotAllowedError" }), true);
  assert.equal(isAutoplayBlocked({ name: "AbortError" }), false);
  assert.equal(isAutoplayBlocked({ name: "NotSupportedError" }), false);
  assert.equal(isAutoplayBlocked(undefined), false);
});
