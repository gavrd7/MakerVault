import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./Common";

/** Compact read-only history reused by spool, part and project details. */
export default function WeightHistory({ targetType, targetId }) {
  const [state, setState] = useState({ rows: [], total: 0 });
  const [all, setAll] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setState({ rows: [], total: 0 });
    setError("");
    setAll(false);
    if (!targetId) return;
    apiFetch(`/api/weight-history/?target_type=${encodeURIComponent(targetType)}&target_id=${encodeURIComponent(targetId)}&limit=3`)
      .then(result => { if (!cancelled) setState(result); })
      .catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [targetType, targetId]);
  async function openAll() {
    setError("");
    try {
      const result = await apiFetch(`/api/weight-history/?target_type=${encodeURIComponent(targetType)}&target_id=${encodeURIComponent(targetId)}&limit=100`);
      setState(result);
      setAll(true);
    } catch (err) { setError(err.message); }
  }
  const display = row => (
    <div key={row.id} className="printingListRow">
      <div>
        <strong>{Number(row.net_weight_g).toFixed(2)} g net</strong>
        <small>{new Date(row.recorded_at).toLocaleString()} · Gross {row.gross_weight_g} g · Tare {row.tare_weight_g} g{row.updated_spool ? " · Inventory updated" : ""}</small>
      </div>
    </div>
  );
  return <section className="panel" style={{ marginTop: 12 }}>
    <div className="sectionHeader"><h3>Weight History</h3>{state.total > 3 && !all && <button type="button" className="buttonSecondary" onClick={openAll}>View All ({state.total})</button>}</div>
    {error && <p className="formError">{error}</p>}
    {!state.total && !error && <p className="muted">No recorded measurements yet.</p>}
    {state.rows.slice(0, 3).map(display)}
    {all && <Modal title="Weight History" subtitle={`${state.total} recorded measurements`} onClose={() => setAll(false)}>
      <div style={{ maxHeight: "65vh", overflowY: "auto" }}>{state.rows.map(display)}</div>
      {state.total > state.rows.length && <p className="muted">Showing the latest {state.rows.length} measurements.</p>}
    </Modal>}
  </section>;
}
