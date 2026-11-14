import test from "node:test";
import assert from "node:assert/strict";
import { isDashboardPrinterOffline } from "../src/components/dashboardPrinterStatus.js";

test("stale telemetry takes precedence over cached completed job", () => {
  assert.equal(isDashboardPrinterOffline({ state: "complete", stale: true, job: { progress: 100 } }), true);
});
test("explicit disconnected status is offline despite previous job", () => {
  assert.equal(isDashboardPrinterOffline({ state: "complete", connection_status: "disconnected" }), true);
  assert.equal(isDashboardPrinterOffline({ state: "printing", connection_status: "offline" }), true);
});
test("a live printer error is not falsely labelled offline", () => {
  assert.equal(isDashboardPrinterOffline({ state: "error", connection_status: "connected", stale: false }), false);
});
test("missing connectivity flags do not infer an offline printer", () => {
  assert.equal(isDashboardPrinterOffline({ state: "idle" }), false);
  assert.equal(isDashboardPrinterOffline({ state: "complete", connection_status: "connected", stale: false }), false);
});
