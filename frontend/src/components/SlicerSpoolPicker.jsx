import React, { useEffect, useRef, useState } from "react";
import { slicerSpoolHex } from "./slicerSpoolColour";

/** A searchable spool picker with real colour swatches (native <option>
 * elements cannot reliably display them across browsers).
 */
export default function SlicerSpoolPicker({ spools = [], value = "", onChange, disabled = false }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef(null);
  const searchRef = useRef(null);
  const selected = spools.find(spool => String(spool.id) === String(value));
  const label = spool => [spool?.spool_id, spool?.filament].filter(Boolean).join(" · ") || "Unnamed spool";
  const matches = spools.filter(spool => label(spool).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = event => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const onKeyDown = event => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  useEffect(() => {
    if (open) searchRef.current?.focus();
    else setQuery("");
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  const choose = id => {
    onChange?.(id);
    setOpen(false);
  };
  const swatch = spool => {
    const hex = slicerSpoolHex(spool);
    return <span className={"slicerSpoolPickerSwatch" + (!hex ? " isUnknown" : "")}
      style={hex ? { backgroundColor: hex } : undefined}
      aria-label={hex ? "Colour " + hex : "Colour unknown"}
      title={hex || "Colour not recorded"} />;
  };
  return <div className="slicerSpoolPicker" ref={rootRef}>
    <button type="button" className="slicerSpoolPickerTrigger"
      disabled={disabled} aria-expanded={open} aria-haspopup="listbox"
      aria-label="Select physical filament spool"
      onClick={() => setOpen(current => !current)}>
      {selected ? swatch(selected) : <span className="slicerSpoolPickerSwatch isUnknown" aria-hidden="true" />}
      <span className="slicerSpoolPickerName">{selected ? label(selected) : "No physical spool selected"}</span>
      <span aria-hidden="true" className="slicerSpoolPickerChevron">{open ? "▴" : "▾"}</span>
    </button>
    {open && <div className="slicerSpoolPickerMenu">
      <input ref={searchRef} type="search" value={query}
        placeholder="Search spool ID, brand or material"
        aria-label="Search physical filament spools"
        onChange={event => setQuery(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Enter") {
            event.preventDefault();
            if (matches.length === 1) choose(String(matches[0].id));
          }
        }} />
      <div role="listbox" aria-label="Available physical filament spools"
        className="slicerSpoolPickerOptions">
        {!query && <button type="button" role="option" aria-selected={!value}
          className="slicerSpoolPickerOption" onClick={() => choose("")}>
          <span className="slicerSpoolPickerSwatch isUnknown" aria-hidden="true" />
          <span>No physical spool selected</span>
        </button>}
        {matches.map(spool => <button type="button" role="option"
          key={spool.id} aria-selected={String(value) === String(spool.id)}
          className="slicerSpoolPickerOption"
          onClick={() => choose(String(spool.id))}>
          {swatch(spool)}
          <span className="slicerSpoolPickerName">{label(spool)}</span>
          {String(value) === String(spool.id) && <span className="slicerSpoolPickerSelected" aria-hidden="true">✓</span>}
        </button>)}
        {!matches.length && <p className="slicerSpoolPickerEmpty">No matching spools.</p>}
      </div>
    </div>}
  </div>;
}
