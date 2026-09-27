import React, { useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, BoardImage, Modal } from "./Common";

function money(value, currency) {
  if (value === null || value === undefined || value === "") return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency || "GBP",
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function qty(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

export default function ProjectBomSection({
  project,
  boards,
  components,
  inventory,
  canEdit,
  config,
  onRefresh,
  refreshInventory,
}) {
  const [editing, setEditing] = useState(null);
  const [allocating, setAllocating] = useState(null);
  const [allocationEdit, setAllocationEdit] = useState(null);
  const [error, setError] = useState("");

  const summary = project.bom_summary || {
    line_count: project.bom?.length || 0,
    complete_lines: 0,
    partial_lines: 0,
    unallocated_lines: 0,
    estimated_cost: null,
    currency: config?.currency || "GBP",
  };

  async function refreshAll() {
    await Promise.all([onRefresh(project), refreshInventory?.()]);
  }

  async function removeItem(item) {
    if (!window.confirm(`Remove "${item.name}" from the BOM? Any allocations on this line will be released.`)) return;
    setError("");
    try {
      await apiFetch(`/api/projects/${project.id}/bom/${item.id}/`, { method: "DELETE" });
      await refreshAll();
    } catch (err) {
      setError(err.message);
    }
  }

  async function releaseAllocation(item, allocation) {
    if (!window.confirm(`Release ${qty(allocation.quantity)} from ${allocation.inventory_id}?`)) return;
    setError("");
    try {
      await apiFetch(
        `/api/projects/${project.id}/bom/${item.id}/allocations/${allocation.id}/`,
        { method: "DELETE" },
      );
      await refreshAll();
    } catch (err) {
      setError(err.message);
    }
  }

  return <section className="projectSection projectBomSection">
    <div className="projectSectionHead">
      <div>
        <h3>Bill of materials</h3>
        <p className="projectSectionIntro">Plan what the build needs and allocate physical stock without losing inventory history.</p>
      </div>
      <div className="bomHeadActions">
        <span>{summary.complete_lines || 0}/{summary.line_count || 0} allocated</span>
        {canEdit && <button onClick={() => setEditing({})}>＋ BOM item</button>}
      </div>
    </div>

    {error && <div className="inlineError">{error}</div>}

    <div className="bomSummaryGrid">
      <div><span>Lines</span><strong>{summary.line_count || 0}</strong></div>
      <div><span>Fully allocated</span><strong>{summary.complete_lines || 0}</strong></div>
      <div><span>Partial</span><strong>{summary.partial_lines || 0}</strong></div>
      <div><span>Unallocated</span><strong>{summary.unallocated_lines || 0}</strong></div>
      <div><span>Estimated BOM</span><strong>{summary.mixed_currency ? "Mixed currencies" : money(summary.estimated_cost, summary.currency)}</strong></div>
    </div>

    <div className="bomList">
      {(project.bom || []).map(item => <article className="bomRow" key={item.id}>
        <div className="bomMain">
          <div className="bomTitleRow">
            <div>
              <strong>{item.name}</strong>
              <small>{item.source_type === "board" ? "Board catalogue" : item.source_type === "component" ? "Component catalogue" : "Custom item"}</small>
            </div>
            <Badge tone={item.allocation_status === "complete" ? "good" : item.allocation_status === "partial" ? "accent" : "neutral"}>
              {item.allocation_status === "complete" ? "Allocated" : item.allocation_status === "partial" ? "Partial" : "Unallocated"}
            </Badge>
          </div>

          <div className="bomProgressMeta">
            <span>Required <strong>{qty(item.quantity)} {item.unit}</strong></span>
            <span>Allocated <strong>{qty(item.allocated_quantity)} {item.unit}</strong></span>
            <span>Remaining <strong>{qty(item.remaining_quantity)} {item.unit}</strong></span>
            <span>Cost <strong>{item.estimated_cost === null ? "—" : money(item.estimated_cost, item.currency)}</strong></span>
          </div>

          <div className="bomProgressTrack" aria-label={`${item.allocated_quantity} of ${item.quantity} allocated`}>
            <span style={{ width: `${Math.min(100, item.quantity ? (Number(item.allocated_quantity || 0) / Number(item.quantity)) * 100 : 0)}%` }} />
          </div>

          {item.notes && <p className="bomNotes">{item.notes}</p>}

          <div className="bomAllocations">
            {(item.allocations || []).map(allocation => <div className="bomAllocationRow" key={allocation.id}>
              <BoardImage src={allocation.inventory_image} alt={allocation.inventory_name} size="tiny" placeholder="INV" />
              <div>
                <strong>{allocation.inventory_name}</strong>
                <small>{allocation.inventory_id} · {allocation.status_label}{allocation.location ? ` · ${allocation.location}` : ""}</small>
              </div>
              <span>{qty(allocation.quantity)}</span>
              {canEdit && <div className="bomAllocationActions">
                <button onClick={() => { setAllocating(item); setAllocationEdit(allocation); }}>Adjust</button>
                <button className="assetDanger" onClick={() => releaseAllocation(item, allocation)}>Release</button>
              </div>}
            </div>)}
            {!item.allocations?.length && <div className="bomAllocationEmpty">No physical inventory allocated yet.</div>}
          </div>
        </div>

        {canEdit && <div className="bomRowActions">
          <button disabled={Number(item.remaining_quantity || 0) <= 0} onClick={() => { setAllocating(item); setAllocationEdit(null); }}>Allocate</button>
          <button onClick={() => setEditing(item)}>Edit</button>
          <button className="assetDanger" onClick={() => removeItem(item)}>Remove</button>
        </div>}
      </article>)}
      {!project.bom?.length && <div className="projectAssetEmpty">No BOM lines yet. Add the boards, components and custom materials this build requires.</div>}
    </div>

    {editing && <BomItemModal
      project={project}
      item={editing.id ? editing : null}
      boards={boards}
      components={components}
      currency={config?.currency || "GBP"}
      onClose={() => setEditing(null)}
      onSaved={async () => { setEditing(null); await refreshAll(); }}
    />}

    {allocating && <BomAllocationModal
      project={project}
      item={allocating}
      allocation={allocationEdit}
      inventory={inventory}
      onClose={() => { setAllocating(null); setAllocationEdit(null); }}
      onSaved={async () => { setAllocating(null); setAllocationEdit(null); await refreshAll(); }}
    />}
  </section>;
}

function BomItemModal({ project, item, boards, components, currency, onClose, onSaved }) {
  const initialType = item?.source_type || "custom";
  const [sourceType, setSourceType] = useState(initialType);
  const [boardId, setBoardId] = useState(item?.board_id || "");
  const [componentId, setComponentId] = useState(item?.component_id || "");
  const [name, setName] = useState(item?.custom_name || "");
  const [quantity, setQuantity] = useState(item?.quantity ?? 1);
  const [unit, setUnit] = useState(item?.unit || "item");
  const [unitCost, setUnitCost] = useState(item?.unit_cost ?? "");
  const [notes, setNotes] = useState(item?.notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const body = {
        board_id: sourceType === "board" ? boardId : "",
        component_id: sourceType === "component" ? componentId : "",
        custom_name: name,
        quantity,
        unit,
        unit_cost: unitCost,
        currency,
        notes,
      };
      await apiFetch(
        item ? `/api/projects/${project.id}/bom/${item.id}/` : `/api/projects/${project.id}/bom/`,
        { method: item ? "PATCH" : "POST", body },
      );
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={item ? "Edit BOM item" : "Add BOM item"} subtitle="Define a required part or material for this project." onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}

      <label>Source
        <select value={sourceType} onChange={e => setSourceType(e.target.value)}>
          <option value="custom">Custom item</option>
          <option value="board">Board catalogue</option>
          <option value="component">Component catalogue</option>
        </select>
      </label>

      {sourceType === "board" && <label>Board
        <select required value={boardId} onChange={e => setBoardId(e.target.value)}>
          <option value="">Choose board…</option>
          {(boards || []).map(board => <option key={board.id} value={board.id}>{board.display_name}</option>)}
        </select>
      </label>}

      {sourceType === "component" && <label>Component
        <select required value={componentId} onChange={e => setComponentId(e.target.value)}>
          <option value="">Choose component…</option>
          {(components || []).map(component => <option key={component.id} value={component.id}>{component.manufacturer ? `${component.manufacturer} · ` : ""}{component.name}</option>)}
        </select>
      </label>}

      <label className={sourceType === "custom" ? "" : "full"}>{sourceType === "custom" ? "Name" : "Optional label"}
        <input required={sourceType === "custom"} value={name} onChange={e => setName(e.target.value)} placeholder={sourceType === "custom" ? "M3 × 8 mm screws" : "Optional project-specific name"} />
      </label>

      <label>Required quantity<input type="number" min="0.001" step="0.001" required value={quantity} onChange={e => setQuantity(e.target.value)} /></label>
      <label>Unit<input required value={unit} onChange={e => setUnit(e.target.value)} placeholder="item, m, g…" /></label>
      <label>Unit cost<input type="number" min="0" step="0.0001" value={unitCost} onChange={e => setUnitCost(e.target.value)} placeholder="Optional" /></label>
      <label>Currency<input value={currency} readOnly /></label>
      <label className="full">Notes<textarea rows="4" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Supplier, variant, tolerances, alternatives…" /></label>
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save BOM item"}</button></div>
    </form>
  </Modal>;
}

function BomAllocationModal({ project, item, allocation, inventory, onClose, onSaved }) {
  const candidates = useMemo(() => {
    const alreadyAllocated = new Set((item.allocations || []).map(row => row.inventory_item_id));
    return (inventory || []).filter(stock => {
      if (allocation && stock.id === allocation.inventory_item_id) return true;
      if (alreadyAllocated.has(stock.id)) return false;
      if (stock.status === "repair" || stock.status === "retired") return false;
      if (stock.project_id && stock.project_id !== project.id) return false;
      if (item.board_id && stock.board_id !== item.board_id) return false;
      if (item.component_id && stock.component_id !== item.component_id) return false;
      return Number(stock.available_quantity ?? stock.quantity ?? 0) > 0;
    });
  }, [inventory, item, project.id, allocation]);

  const [inventoryId, setInventoryId] = useState(allocation?.inventory_item_id || candidates[0]?.id || "");
  const [quantity, setQuantity] = useState(allocation?.quantity ?? Math.min(1, Number(item.remaining_quantity || 1)));
  const [notes, setNotes] = useState(allocation?.notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = candidates.find(row => row.id === inventoryId);
  const maxAvailable = selected
    ? Number(selected.available_quantity ?? selected.quantity ?? 0) + (allocation && selected.id === allocation.inventory_item_id ? Number(allocation.quantity || 0) : 0)
    : 0;
  const maxBom = Number(item.remaining_quantity || 0) + (allocation ? Number(allocation.quantity || 0) : 0);
  const maxQuantity = Math.min(maxAvailable, maxBom);

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      if (allocation) {
        await apiFetch(
          `/api/projects/${project.id}/bom/${item.id}/allocations/${allocation.id}/`,
          { method: "PATCH", body: { quantity, notes } },
        );
      } else {
        await apiFetch(
          `/api/projects/${project.id}/bom/${item.id}/allocations/`,
          { method: "POST", body: { inventory_item_id: inventoryId, quantity, notes } },
        );
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={allocation ? "Adjust allocation" : `Allocate stock · ${item.name}`} subtitle={`${qty(item.remaining_quantity)} ${item.unit} currently remain on this BOM line.`} onClose={onClose} wide>
    <form className="formGrid" onSubmit={submit}>
      {error && <div className="formError full">{error}</div>}
      <label className="full">Inventory item
        {allocation ? <input value={`${allocation.inventory_id} · ${allocation.inventory_name}`} readOnly /> :
          <select required value={inventoryId} onChange={e => setInventoryId(e.target.value)}>
            <option value="">Choose inventory…</option>
            {candidates.map(stock => <option key={stock.id} value={stock.id}>{stock.inventory_id} · {stock.name} · {qty(stock.available_quantity ?? stock.quantity)} free</option>)}
          </select>}
      </label>
      <label>Allocation quantity<input type="number" min="0.001" max={maxQuantity || undefined} step="0.001" required value={quantity} onChange={e => setQuantity(e.target.value)} /></label>
      <label>Available<input value={selected ? `${qty(maxAvailable)} stock · ${qty(maxBom)} BOM capacity` : "Choose inventory"} readOnly /></label>
      <label className="full">Notes<textarea rows="3" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional allocation note" /></label>
      {!candidates.length && !allocation && <div className="formError full">No compatible inventory currently has free quantity for this BOM line.</div>}
      <div className="formActions full"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !inventoryId || maxQuantity <= 0}>{busy ? "Saving…" : allocation ? "Save allocation" : "Allocate stock"}</button></div>
    </form>
  </Modal>;
}
