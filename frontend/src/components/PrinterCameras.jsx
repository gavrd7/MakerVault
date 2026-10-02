import React, { useEffect, useRef, useState } from "react";
import { Modal } from "./Common";
import PrinterCamera, { CameraPlayback } from "./PrinterCamera";
import { defaultCamera } from "./cameraPlayback";

export function PrinterCameraPreview({ printer, suspended = false }) {
  const container = useRef(null);
  const [visible, setVisible] = useState(false);
  const [pageVisible, setPageVisible] = useState(!document.hidden);
  const selected = defaultCamera(printer.live_connections || printer.camera_connections || []);
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const changed = () => setPageVisible(!document.hidden);
    document.addEventListener("visibilitychange", changed);
    let observer;
    if (globalThis.IntersectionObserver) {
      observer = new IntersectionObserver(entries => setVisible(entries[0]?.isIntersecting || false));
      observer.observe(node);
    } else setVisible(true);
    return () => { observer?.disconnect(); document.removeEventListener("visibilitychange", changed); };
  }, [Boolean(selected)]);
  if (!selected) return null;
  const url = `/api/printing/printers/${printer.id}/connections/${selected.connectionId}/cameras/${selected.camera.id}/media/`;
  return <section ref={container} className="printerCameraCard cameraGlanceCard" aria-label={printer.name + " live camera"}>
    {visible && pageVisible && !suspended ? <CameraPlayback key={selected.connectionId + ":" + selected.camera.id} camera={selected.camera} url={url} compact /> : <div className="printerCameraPlaceholder">Camera paused</div>}
  </section>;
}

export function PrinterCameraSetupModal({ printer, initialConnectionId, onClose, onChanged }) {
  const connections = printer.live_connections || [];
  const [selected, setSelected] = useState(initialConnectionId || connections[0]?.id || "");
  const connection = connections.find(item => item.id === selected) || connections[0];
  return <Modal title={"Camera setup · " + printer.name} subtitle="Configure camera feeds independently of live printer monitoring." onClose={onClose} wide>
    {connection ? <>
      <label>Printer integration<select value={connection.id} onChange={e => setSelected(e.target.value)}>{connections.map(item => <option key={item.id} value={item.id}>{item.adapter_label}{item.enabled ? "" : " · disabled"}</option>)}</select></label>
      <PrinterCamera key={connection.id} printerId={printer.id} connection={connection} canEdit setupOnly activeCamera="" setActiveCamera={() => {}} onChanged={onChanged} />
    </> : <p>Add a live printer source first, then return here to configure its camera.</p>}
    <div className="settingsActions"><button type="button" onClick={onClose}>Done</button></div>
  </Modal>;
}
