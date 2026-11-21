import React, {useEffect, useState} from "react";
import {apiFetch} from "../api";
import "./homeAssistantPower.css";

/** Intentionally renders nothing until a configured printer power entity is found.
 * No polling or automation; state is refreshed only after explicit interaction.
 */
export default function PrinterPowerButton({printerId, compact = false, connectionHint = null}) {
  const [power, setPower] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  useEffect(() => {
    let alive = true;
    let generation = 0;
    setPower(null);
    setError("");
    setFeedback("");
    if (!printerId) return () => { alive = false; };
    const refresh = () => {
      const request = ++generation;
      apiFetch("/api/printing/printers/" + printerId + "/power/")
        .then(data => {
          if (alive && request === generation) setPower(data.available ? data.state : null);
        })
        .catch(() => {
          if (alive && request === generation) setPower(null);
        });
    };
    const onAssignmentChange = event => {
      if (String(event.detail?.printerId) === String(printerId)) refresh();
    };
    const onFocus = () => refresh();
    refresh();
    window.addEventListener("makervault:printer-power-assignment-changed", onAssignmentChange);
    // Resync external Home Assistant changes when returning to MakerVault.
    window.addEventListener("focus", onFocus);
    return () => {
      alive = false;
      window.removeEventListener("makervault:printer-power-assignment-changed", onAssignmentChange);
      window.removeEventListener("focus", onFocus);
    };
  }, [printerId]);
  if (power == null) return null;
  // Only the actual Home Assistant switch state may authorise a command.
  // Printer connectivity does not establish whether mains power is on or off.
  const effectivePower = power;
  const available = power === "on" || power === "off";
  const turn = async () => {
    if (busy || !available) return;
    const action = effectivePower === "on" ? "off" : "on";
    if (action === "off" && !window.confirm(
      "Turn off printer power? Confirm printing is finished and the hotend, bed and electronics have cooled. This cuts mains power immediately."
    )) return;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const result = await apiFetch("/api/printing/printers/" + printerId + "/power/", {
        method: "POST", body: {action, ...(action === "off" ? {confirm: true} : {})},
      });
      if (!result.available || result.state !== action) {
        throw new Error("Home Assistant has not confirmed the requested switch state.");
      }
      setPower(result.state);
      setFeedback("success");
    } catch (err) {
      setError(err.message || "Power command failed.");
      setFeedback("error");
    } finally {
      setBusy(false);
    }
  };
  return <span className={"printerPowerControl" + (compact ? " isCompact" : "")}>
    <button type="button"
      className={"printerPowerButton state-" + effectivePower + (busy ? " isSwitching" : "") + (feedback ? " feedback-" + feedback : "")}
      disabled={busy || !available} onClick={turn}
      onAnimationEnd={event => {
        if (event.target === event.currentTarget) setFeedback("");
      }}
      aria-label={busy ? "Switching printer power" : effectivePower === "on" ? "Turn printer power off" : available ? "Turn printer power on" : "Printer power state unavailable"}
      title={error || (!available ? "Home Assistant switch state unavailable. Power commands are disabled until the actual switch state is known." : "Home Assistant reports power " + power + ". Click to turn " + (power === "on" ? "off" : "on") + ".")}>
      <span className="printerPowerGlyph" aria-hidden="true">{feedback === "success" ? "✓" : feedback === "error" ? "!" : "⏻"}</span>
      <span className="printerPowerLabel">{busy ? "Switching…" : effectivePower === "on" ? "Turn off" : effectivePower === "off" ? "Turn on" : "Unavailable"}</span>
    </button>
    <span className="printerPowerSrOnly" role="status" aria-live="polite">
      {busy ? "Switching printer power" : error ? error : feedback === "success" ? "Printer power confirmed " + power : ""}
    </span>
  </span>;
}
