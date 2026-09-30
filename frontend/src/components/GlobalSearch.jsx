import React, { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";

export default function GlobalSearch({ onOpenResult, onOpenAdvanced }) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const rootRef = useRef(null);

  useEffect(() => {
    function close(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);

  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setRows([]);
      setBusy(false);
      setError("");
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError("");
    const timer = window.setTimeout(() => {
      apiFetch("/api/search/?q=" + encodeURIComponent(needle) + "&limit=4")
        .then(result => {
          if (cancelled) return;
          setRows((result.rows || []).slice(0, 10));
          setOpen(true);
        })
        .catch(err => {
          if (cancelled) return;
          setError(err.message || "Search failed.");
          setOpen(true);
        })
        .finally(() => {
          if (!cancelled) setBusy(false);
        });
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  function advanced() {
    setOpen(false);
    onOpenAdvanced(query.trim());
  }

  function choose(row) {
    setOpen(false);
    onOpenResult(row);
  }

  return <div className="globalSearch" ref={rootRef}>
    <div className="globalSearchInputWrap">
      <span aria-hidden="true">⌕</span>
      <input
        value={query}
        onFocus={() => query.trim().length >= 2 && setOpen(true)}
        onChange={event => setQuery(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Enter") advanced();
          if (event.key === "Escape") setOpen(false);
        }}
        placeholder="Search MakerVault…"
        aria-label="Search MakerVault"
      />
      {busy && <span className="globalSearchBusy">•••</span>}
    </div>
    {open && <div className="globalSearchPopover">
      {error && <div className="globalSearchMessage">{error}</div>}
      {!error && !busy && !rows.length && <div className="globalSearchMessage">No matching records.</div>}
      {rows.map(row => <button type="button" className="globalSearchResult" key={row.type + ":" + row.id} onClick={() => choose(row)}>
        <span className="globalSearchType">{row.type_label}</span>
        <strong>{row.title}</strong>
        <small>{row.subtitle || row.status || "MakerVault record"}</small>
      </button>)}
      <button type="button" className="globalSearchAdvanced" onClick={advanced}>
        Advanced search{query.trim() ? " for “" + query.trim() + "”" : ""} →
      </button>
    </div>}
  </div>;
}
