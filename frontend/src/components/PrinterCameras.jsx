import React, { useState } from "react";
import { Modal } from "./Common";
import PrinterCamera from "./PrinterCamera";

export function PrinterCameraPreview({ printer, expanded, onWatch, onStop, onSetup, canEdit, onChanged }) {
  const connections = (printer.live_connections || []).filter(item => item.enabled && item.camera?.configured > 0);
  const [selected, setSelected] = useState("");
  const [activeCamera, setActiveCamera] = useState("");
  const connection = connections.find(item => item.id === selected) || connections[0];
  return <section className="printerCameraCard" aria-label={printer.name + " camera preview"}>
    <div className="printerCameraToolbar"><strong>Camera preview</strong>
      {canEdit && <button type="button" onClick={onSetup}>Camera setup</button>}
      {expanded && connection && <button type="button" onClick={() => { setActiveCamera(""); onStop(); }}>Close preview</button>}
    </div>
    {expanded && connection ? <>
      {connections.length > 1 && <label>Camera integration<select value={connection.id} onChange={e => { setActiveCamera(""); setSelected(e.target.value); }}>{connections.map(item => <option key={item.id} value={item.id}>{item.adapter_label}</option>)}</select></label>}
      <PrinterCamera key={connection.id} printerId={printer.id} connection={connection} canEdit={false} activeCamera={activeCamera} setActiveCamera={setActiveCamera} onChanged={onChanged} autoStart />
    </> : <div className="printerCameraPlaceholder">
      <span>{connection ? "Camera ready" : "No enabled camera configured"}</span>
      {connection ? <button type="button" onClick={onWatch}>Watch camera</button> : <small>{canEdit ? "Use Camera setup to add a feed." : "Ask an editor to configure a camera."}</small>}
    </div>}
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
