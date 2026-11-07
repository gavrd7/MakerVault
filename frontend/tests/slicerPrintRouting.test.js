import test from "node:test";
import assert from "node:assert/strict";
import {
  availableSlicerPrintConnections,
  preferredSlicerPrintConnection,
} from "../src/components/slicerPrintRouting.js";

test("slicer shortcut never chooses a connection from another printer or a disabled source", () => {
  const printer = {
    live_connections: [
      { id: "disabled", enabled: false, adapter: "creality_local" },
      { id: "native", enabled: true, adapter: "creality_local" },
      { id: "moonraker", enabled: true, adapter: "moonraker" },
    ],
    live_status: { id: "moonraker" },
  };
  assert.deepEqual(availableSlicerPrintConnections(printer).map(item => item.id), ["native", "moonraker"]);
  assert.equal(preferredSlicerPrintConnection(printer).id, "moonraker");
});

test("slicer shortcut defaults to first enabled connection and fails without any enabled source", () => {
  assert.equal(preferredSlicerPrintConnection({
    live_connections: [{ id: "native", enabled: true }, { id: "k2", enabled: true }],
  }).id, "native");
  assert.equal(preferredSlicerPrintConnection({ live_connections: [{ id: "no", enabled: false }] }), null);
  assert.equal(preferredSlicerPrintConnection(null), null);
  assert.deepEqual(availableSlicerPrintConnections({}), []);
});

test("slicer routing requires explicit enabled state and connection identity", () => {
  const printer = {
    live_connections: [
      { id: "missing-enabled" },
      { enabled: true },
      { id: "good", enabled: true },
    ],
    live_status: { connection_id: "good" },
  };
  assert.equal(preferredSlicerPrintConnection(printer).id, "good");
  assert.equal(availableSlicerPrintConnections(printer).length, 1);
});
