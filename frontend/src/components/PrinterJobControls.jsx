import React, { useRef, useState } from "react";
import { apiFetch } from "../api";

const ACTIONS = [
  ["pause", "Pause print", <><path d="M8 5v14M16 5v14" /></>],
  ["resume", "Resume print", <path d="m8 5 11 7-11 7Z" />],
  ["cancel", "Cancel print", <rect x="6" y="6" width="12" height="12" rx="1" />],
];

function requestId() {
  const bytes = window.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export default function PrinterJobControls({ printer, connection, canControl, onChanged, disabled = false }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const sending = useRef(false);
  const controls = connection?.controls;
  if (!canControl || !controls?.supported || !controls.enabled) return null;

  async function send(action) {
    if (sending.current) return;
    if (action === "cancel" && !window.confirm(`Cancel the print on ${printer.name}?\n\nJob: ${connection.snapshot?.job?.file_name || "Unknown job"}\n\nThis stops the current print.`)) return;
    sending.current = true;
    setBusy(true); setMessage(""); setError(false);
    try {
      const result = await apiFetch(`/api/printing/printers/${printer.id}/connections/${connection.id}/control/`, {
        method: "POST", body: {
          action, request_id: requestId(), job_token: controls.job_token,
          confirmed_cancel: action === "cancel",
        },
      });
      setMessage(result.command.message);
    } catch (err) {
      setError(true); setMessage(err.message);
    } finally {
      try { await onChanged?.(); } catch { /* The next telemetry refresh can recover. */ }
      sending.current = false;
      setBusy(false);
    }
  }

  return <div className="printerJobControls">
    <div className="printerJobControlButtons" role="group" aria-label={`Print controls for ${printer.name}`}>
      {ACTIONS.map(([action, label, icon]) => <button key={action} type="button"
        className={"printerJobControl" + (action === "cancel" ? " printerJobControlCancel" : "")}
        aria-label={label} title={controls.actions?.includes(action) ? label : `${label} unavailable for the current job or source status`}
        disabled={disabled || busy || !controls.actions?.includes(action)} onClick={() => send(action)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icon}</svg>
      </button>)}
    </div>
    {message && <small className={"printerJobControlMessage" + (error ? " integrationError" : "")} role={error ? "alert" : "status"}>{message}</small>}
  </div>;
}
