import React, { useState } from "react";
import { Modal } from "./Common";
import PrinterCamera, { CameraPlayback } from "./PrinterCamera";
import { defaultCamera } from "./cameraPlayback";

// Camera playback is intentionally mounted as soon as the preview renders.
// No viewport/visibility observer or document.hidden gate: this isolates
// Safari HLS startup from scrolling and intersection-driven mount churn.
export function PrinterCameraPreview({ printer, compact = true }) {
  const selected = defaultCamera(printer.live_connections || printer.camera_connections || []);
  if (!selected) return null;
  const url = `/api/printing/printers/${printer.id}/connections/${selected.connectionId}/cameras/${selected.camera.id}/media/`;
  return <section className="printerCameraCard cameraGlanceCard" aria-label={printer.name + " live camera"}>
    <CameraPlayback key={selected.connectionId + ":" + selected.camera.id} camera={selected.camera} url={url} compact={compact} />
  </section>;
}

export function PrinterCameraSetupModal({ printer, initialConnectionId, onClose, onChanged }) {
  const connections = printer.live_connections || [];
  const [selected, setSelected] = useState(initialConnectionId || connections[0]?.id || "");
  const connection = connections.find(item => item.id === selected) || connections[0];
  return <Modal title={"Camera setup · " + printer.name} subtitle="Configure camera feeds independently of live printer monitoring." onClose={onClose} wide>
    <div className="printerCameraSetupLayout">
    {connection ? <>
      <label className="printerCameraIntegrationField">Printer integration<select value={connection.id} onChange={e => setSelected(e.target.value)}>{connections.map(item => <option key={item.id} value={item.id}>{item.adapter_label}{item.enabled ? "" : " · disabled"}</option>)}</select></label>
      <PrinterCamera key={connection.id} printerId={printer.id} connection={connection} canEdit setupOnly activeCamera="" setActiveCamera={() => {}} onChanged={onChanged} />
    </> : <p>Add a live printer source first, then return here to configure its camera.</p>}
    <div className="settingsActions printerCameraDoneActions"><button type="button" onClick={onClose}>Done</button></div>
    </div>
  </Modal>;
}
