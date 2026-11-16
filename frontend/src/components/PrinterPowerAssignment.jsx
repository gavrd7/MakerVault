import React, {useEffect, useState} from "react";
import {apiFetch} from "../api";

/** Optional setting inside Manage Printer, absent without a working HA setup. */
export default function PrinterPowerAssignment({printerId}) {
  const [available, setAvailable] = useState(false);
  const [switches, setSwitches] = useState([]);
  const [entity, setEntity] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [{item}, assignment] = await Promise.all([
          apiFetch("/api/settings/home-assistant/"),
          apiFetch("/api/printing/printers/" + printerId + "/power/assignment/"),
        ]);
        if (!item?.enabled || !item.token_configured) return;
        const results = await apiFetch("/api/settings/home-assistant/switches/");
        if (active) {
          setEntity(assignment.entity_id || "");
          setSwitches(results.switches || []);
          setAvailable(true);
        }
      } catch (_) {
        // No blank control if the integration is disabled, unconfigured,
        // inaccessible to this user, or the Home Assistant server is offline.
      }
    })();
    return () => {active = false;};
  }, [printerId]);
  if (!available) return null;
  return <div className="printerPowerAssignment full">
    <label>Home Assistant power switch
      <select value={entity} disabled={busy} onChange={async event => {
        const next = event.target.value;
        setBusy(true);setError("");
        try {
          const result = await apiFetch("/api/printing/printers/" + printerId + "/power/assignment/", {
            method: "PATCH", body: {entity_id: next},
          });
          setEntity(result.entity_id || "");
          // Notify every mounted printer control immediately after the server
          // has saved the new mapping. No page reload or polling required.
          window.dispatchEvent(new CustomEvent("makervault:printer-power-assignment-changed", {
            detail: {printerId},
          }));
        } catch (err) {
          setError(err.message || "Could not assign switch.");
        } finally {setBusy(false);}
      }}>
        <option value="">No smart plug assigned</option>
        {entity && !switches.some(item => item.entity_id === entity) &&
          <option value={entity}>{entity} (currently unavailable)</option>}
        {switches.map(item => <option key={item.entity_id} value={item.entity_id}>
          {item.name} · {item.entity_id}
        </option>)}
      </select>
    </label>
    <small>Only an explicitly assigned Home Assistant switch adds printer power controls. Changes are saved immediately.</small>
    {error && <small role="alert" className="printerPowerError">{error}</small>}
  </div>;
}
