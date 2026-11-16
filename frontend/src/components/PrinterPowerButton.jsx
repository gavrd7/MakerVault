import React, {useEffect, useState} from "react";
import {apiFetch} from "../api";
import "./homeAssistantPower.css";

/** Intentionally renders nothing until a configured printer power entity is found.
 * No polling or automation; state is refreshed only after explicit interaction.
 */
export default function PrinterPowerButton({printerId, compact = false}) {
  const [power, setPower] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setPower(null);
    setError("");
    if (!printerId) return () => { alive = false; };
    apiFetch("/api/printing/printers/" + printerId + "/power/")
      .then(data => { if (alive) setPower(data.available ? data.state : null); })
      .catch(() => { if (alive) setPower(null); });
    return () => { alive = false; };
  }, [printerId]);
  if (power == null) return null;
  const available = power === "on" || power === "off";
  const turn = async () => {
    if (busy || !available) return;
    const action = power === "on" ? "off" : "on";
    if (action === "off" && !window.confirm(
      "Turn off printer power? Confirm printing is finished and the hotend, bed and electronics have cooled. This cuts mains power immediately."
    )) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch("/api/printing/printers/" + printerId + "/power/", {
        method: "POST", body: {action, ...(action === "off" ? {confirm: true} : {})},
      });
      if (!result.available || result.state !== action) {
        throw new Error("Home Assistant has not confirmed the requested switch state.");
      }
      setPower(result.state);
    } catch (err) {
      setError(err.message || "Power command failed.");
    } finally {
      setBusy(false);
    }
  };
  return <span className={"printerPowerControl" + (compact ? " isCompact" : "")}>
    <button type="button" className={"printerPowerButton state-" + power}
      disabled={busy || !available} onClick={turn}
      aria-label={busy ? "Switching printer power" : power === "on" ? "Turn printer power off" : "Turn printer power on"}
      title={available ? "Home Assistant printer power: " + power : "Home Assistant switch unavailable"}>
      <span aria-hidden="true">⏻</span>
      <span className="printerPowerLabel">{busy ? "Switching…" : power === "on" ? "Power on" : power === "off" ? "Power off" : "Unavailable"}</span>
    </button>
    {error && <small className="printerPowerError" role="alert">{error}</small>}
  </span>;
}
