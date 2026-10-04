import test from "node:test";
import assert from "node:assert/strict";
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
