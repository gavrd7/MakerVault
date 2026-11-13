import React from "react";

const defaultFlush = () => ({ multiplier: null, prime_tower: "native", transitions: [] });
const nameFor = slot => `Slot ${Number(slot.slot_index ?? 0) + 1} · ${slot.product_name || slot.material || "Unknown"}`;

/** Draft-only native Orca flushing configuration for observed changer slots.
 * The profile's original matrix is preserved for blank cells. A physical
 * CFS/AMS bay is never assumed to be the matching native tool number.
 */
export default function SlicerFlushVolumes({ slots = [], value = null, onChange, disabled = false }) {
  const visible = slots.filter(slot => slot?.id != null).slice(0, 8);
  const data = value || defaultFlush();
  const change = update => onChange?.(update);
  const updateTransition = (from, to, raw) => {
    if (!raw.trim()) {
      change({ ...data, transitions: data.transitions.filter(item =>
        item.from_slot_id !== String(from.id) || item.to_slot_id !== String(to.id)) });
      return;
    }
    const number = Number(raw);
    if (!Number.isFinite(number) || number < 0 || number > 20000) return;
    const rest = data.transitions.filter(item =>
      item.from_slot_id !== String(from.id) || item.to_slot_id !== String(to.id));
    change({ ...data, transitions: [...rest, {
      from_slot_id: String(from.id), to_slot_id: String(to.id), volume_mm3: number,
    }] });
  };
  const transitionValue = (from, to) => data.transitions.find(item =>
    item.from_slot_id === String(from.id) && item.to_slot_id === String(to.id))?.volume_mm3 ?? "";

  return <details className="slicerFlushPanel">
    <summary>Flushing volumes &amp; prime tower <small>{value ? "· Draft overrides" : "· Native profile defaults"}</small></summary>
    <p className="projectUploadHint">
      For CFS/AMS-style single-nozzle changers. The volume for A → B can differ
      from B → A. Empty cells preserve the native slicer preset; they are not zero.
      Physical slot order is not treated as native tool order.
    </p>
    <div className="slicerFlushPanelControls">
      <label>Flush multiplier
        <input type="number" min="0.1" max="3" step="0.1" value={data.multiplier ?? ""} placeholder="Native"
          disabled={disabled} onChange={event => {
            const number = Number(event.target.value);
            if (!event.target.value.trim()) change({ ...data, multiplier: null });
            else if (number >= 0.1 && number <= 3)
              change({ ...data, multiplier: number });
          }} />
      </label>
      <label>Prime tower
        <select value={data.prime_tower} disabled={disabled}
          onChange={event => change({ ...data, prime_tower: event.target.value })}>
          <option value="native">Use native profile</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </select>
      </label>
      <button type="button" disabled={disabled || !value} onClick={() => change(null)}>
        Reset all to native defaults
      </button>
    </div>
    {visible.length >= 2 ? <div className="slicerFlushTableScroll">
      <table className="dataTable slicerFlushTable">
        <caption>Directional flushing volumes (mm³): from row → to column</caption>
        <thead><tr><th>From / To</th>{visible.map(slot =>
          <th key={slot.id} title={nameFor(slot)}>Slot {Number(slot.slot_index ?? 0) + 1}</th>)}</tr></thead>
        <tbody>{visible.map(from => <tr key={from.id}>
          <th title={nameFor(from)}>{nameFor(from)}</th>
          {visible.map(to => <td key={to.id}>{String(from.id) === String(to.id)
            ? <span aria-label="Same filament">—</span>
            : <input type="number" min="0" max="20000" step="1"
              aria-label={`Flush ${nameFor(from)} to ${nameFor(to)} in cubic millimetres`}
              placeholder="Native" value={transitionValue(from, to)}
              disabled={disabled}
              onChange={event => updateTransition(from, to, event.target.value)} />}</td>)}
        </tr>)}</tbody>
      </table>
    </div> : <p className="projectUploadHint">
      Refresh the loaded filament list to configure at least two observed slots.
    </p>}
    {slots.length > 8 && <p className="formError">
      More than eight loaded slots: edit a smaller supported palette before applying these overrides.
    </p>}
    <p className="projectUploadHint">
      These are saved with the slicing draft. Native profiles define the
      machine's unloading, loading, purging and prime-tower implementation;
      MakerVault does not generate its own firmware purge commands.
      Different materials and printers may need measured volumes. Never
      assume colour alone determines a safe flushing amount. Independent
      toolheads use a separate priming strategy.
    </p>
  </details>;
}
