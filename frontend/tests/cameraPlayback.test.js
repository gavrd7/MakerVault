import test from "node:test";
import assert from "node:assert/strict";
import { waitForIce, startFrameLoop, prepareCrealityOffer } from "../src/components/cameraPlayback.js";

test("ICE gathering is cancelled and listeners released", async () => {
  class Peer extends EventTarget {
    iceGatheringState = "gathering";
    listeners = 0;
    addEventListener(...args) { this.listeners++; super.addEventListener(...args); }
    removeEventListener(...args) { this.listeners--; super.removeEventListener(...args); }
  }
  const peer = new Peer();
  const controller = new AbortController();
  const pending = waitForIce(peer, controller.signal, 100);
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(peer.listeners, 0);
});

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

test("Creality numeric candidate compatibility keeps SDP and IP candidates", () => {
  const offer = "v=0\r\na=candidate:1 1 UDP 123 browser.local 5000 typ host\r\na=candidate:2 1 UDP 123 192.168.1.2 5001 typ host\r\n";
  assert.equal(prepareCrealityOffer(offer), offer.replace("browser.local", "192.0.2.1"));
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

test('different printer queues do not block each other', async () => {
  const { cameraRequest } = await import('../src/components/cameraPlayback.js');
  const events = [];
  let releaseK1;
  const k1 = cameraRequest(async () => {
    events.push('k1-start');
    await new Promise(resolve => { releaseK1 = resolve; });
    events.push('k1-done');
  }, undefined, 'k1-connection');
  await new Promise(resolve => setTimeout(resolve, 0));

  const k2 = cameraRequest(() => events.push('k2'), undefined, 'k2-connection');
  await k2;
  assert.deepEqual(events, ['k1-start', 'k2']);

  releaseK1();
  await k1;
  assert.deepEqual(events, ['k1-start', 'k2', 'k1-done']);
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
