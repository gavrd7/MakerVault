import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { startFrameLoop, cameraHlsUrl } from "../src/components/cameraPlayback.js";

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

test("printer camera retains the pre-refactor HLS playback flow in the redesigned cards", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  assert.match(source, /hls\.loadSource\(source\)/);
  assert.match(source, /hls\.attachMedia\(target\)/);
  assert.match(source, /hls\.on\(Hls\.Events\.MANIFEST_PARSED/);
  assert.match(source, /autoPlay muted playsInline controls=\{!compact\}/);
  assert.doesNotMatch(source, /switchToNative|scheduleWatchdog/);
  assert.match(source, /camera\.mode !== "creality_webrtc" && <button[^\n]*cameraFullscreen/);
});

test("Safari autoplay rejection keeps existing HLS source and exposes a tap-to-play button", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  const handler = source.slice(source.indexOf("const attemptAutoplay ="), source.indexOf('if (camera.mode !== "creality_webrtc") {', source.indexOf("const attemptAutoplay =")));
  assert.match(handler, /reason\?\.name === "NotAllowedError"/);
  assert.match(handler, /setPlaybackBlocked\(true\)/);
  assert.doesNotMatch(handler, /failed\("Playback was blocked|removeAttribute|\.load\(\)/);
  assert.match(source, /playbackBlocked && camera\.mode === "creality_webrtc"/);
  assert.match(source, />Start video<\/button>/);
  assert.match(source, /target\.play\(\)\.then/);
});

test("fatal HLS errors expose their classification without revealing relay URLs", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  assert.match(source, /data\.type \|\| "unknown"/);
  assert.match(source, /data\.details \|\| "unknown"/);
  assert.match(source, /HLS: /);
  assert.match(source, /setPlaybackDiagnostic\(/);
  assert.match(source, /onError=\{event =>/);
  assert.doesNotMatch(source, /Camera relay disconnected\. Check the printer connection/);
});

test("Safari MediaSource reset is eligible for native HLS recovery only when available", async () => {
  const { shouldFallbackToNativeHls } = await import("../src/components/cameraPlayback.js");
  assert.equal(shouldFallbackToNativeHls({ details: "mediaSourceRequiresReset" }, true), true);
  assert.equal(shouldFallbackToNativeHls({ details: "mediaSourceRequiresReset" }, false), false);
  assert.equal(shouldFallbackToNativeHls({ details: "bufferAppendError" }, true), false);
});

test("fatal Safari MediaSource reset releases hls.js before native playback", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  const recovery = source.slice(source.indexOf("if (!nativeRecovery.current && shouldFallbackToNativeHls"), source.indexOf('setPlaybackDiagnostic(diagnostic);', source.indexOf("if (!nativeRecovery.current && shouldFallbackToNativeHls")));
  assert.match(recovery, /hls\?\.destroy\(\)/);
  assert.match(recovery, /hls = null/);
  assert.match(recovery, /target\.src = source/);
  assert.match(recovery, /attemptAutoplay\(target\)/);
  assert.ok(recovery.indexOf("hls?.destroy()") < recovery.indexOf("target.src = source"));
  assert.match(source, /Native HLS recovery failed/);
});

test("camera playback does not report recovered until a video frame is presented", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  assert.doesNotMatch(source, /Recovered using native HLS/);
  assert.match(source, /requestVideoFrameCallback/);
  assert.match(source, /Video playing · checking decoded frames/);
  assert.match(source, /No presented video frame confirmed/);
  assert.match(source, /videoFrameDiagnostic\(health, mode\)/);
  assert.match(source, /target\.addEventListener\("playing", playingHandler\)/);
  assert.match(source, /target\.removeEventListener\("playing", playingHandler\)/);
});

test("camera preview prewarms before scrolling into view and stays mounted afterwards", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCameras.jsx"), "utf8");
  assert.match(source, /rootMargin: "1200px 0px"/);
  assert.match(source, /if \(entries\[0\]\?\.isIntersecting\) setVisible\(true\)/);
  assert.doesNotMatch(source, /setVisible\(entries\[0\]\?\.isIntersecting \|\| false\)/);
});

test("camera supports local frame capture to separate rendering failures from black source pixels", () => {
  const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../src/components/PrinterCamera.jsx"), "utf8");
  const playback = source.slice(source.indexOf("export function CameraPlayback"));
  assert.match(playback, /context\.drawImage\(target/);
  assert.match(playback, /context\.getImageData\(/);
  assert.match(playback, /onClick=\{inspectFrame\}/);
  assert.match(playback, /capturedFrame && <img/);
  assert.match(playback, /average brightness/);
});
