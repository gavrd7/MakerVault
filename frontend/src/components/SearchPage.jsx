import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock } from "./Common";

const DEFAULT_TYPES = ["projects", "inventory", "boards", "components", "files", "models", "printers", "spools", "filaments"];

function formatDate(value) {
  if (!value) return "";
  try { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value)); }
  catch { return value; }
}

export default function SearchPage({ initialQuery = "", projects = [], onOpenResult }) {
  const [query, setQuery] = useState(initialQuery);
  const [types, setTypes] = useState(DEFAULT_TYPES);
  const [sort, setSort] = useState("relevance");
  const [projectId, setProjectId] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [updatedAfter, setUpdatedAfter] = useState("");
  const [updatedBefore, setUpdatedBefore] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setQuery(initialQuery || ""), [initialQuery]);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setBusy(true);
      setError("");
      try {
        const params = new URLSearchParams();
        if (query.trim()) params.set("q", query.trim());
        if (types.length && types.length !== DEFAULT_TYPES.length) params.set("types", types.join(","));
        params.set("sort", sort);
        params.set("limit", "50");
        if (projectId) params.set("project", projectId);
        if (manufacturer.trim()) params.set("manufacturer", manufacturer.trim());
        if (updatedAfter) params.set("updated_after", updatedAfter);
        if (updatedBefore) params.set("updated_before", updatedBefore);
        const result = await apiFetch("/api/search/?" + params.toString());
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) setError(err.message || "MakerVault could not search.");
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, types, sort, projectId, manufacturer, updatedAfter, updatedBefore]);

  const typeOptions = data?.types || DEFAULT_TYPES.map(value => ({ value, label: value }));
  const counts = useMemo(() => {
    const result = {};
    for (const row of data?.rows || []) result[row.type] = (result[row.type] || 0) + 1;
    return result;
  }, [data]);

  function toggleType(value) {
    setTypes(current => {
      if (current.includes(value)) {
        if (current.length === 1) return current;
        return current.filter(item => item !== value);
      }
      return [...current, value];
    });
  }

  return <div className="searchPage">
    <section className="panel searchHero">
      <div>
        <span className="settingsEyebrow">Universal search</span>
        <h2>Find anything in MakerVault</h2>
        <p>Search your private workspace and shared catalogues together. Private results always remain scoped to your account.</p>
      </div>
      <div className="searchHeroInput">
        <span aria-hidden="true">⌕</span>
        <input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Boards, projects, files, models, inventory…" />
      </div>
    </section>

    <section className="searchWorkspace">
      <div className="panel searchFilters">
        <div className="searchFilterSection">
          <strong>Record types</strong>
          <div className="searchTypeFilters">
            {typeOptions.map(item => <label key={item.value}>
              <input type="checkbox" checked={types.includes(item.value)} onChange={() => toggleType(item.value)} />
              <span>{item.label}</span>
              <small>{counts[item.value] || 0}</small>
            </label>)}
          </div>
          <button type="button" onClick={() => setTypes(DEFAULT_TYPES)}>Select all</button>
        </div>

        <div className="searchFilterSection">
          <label><span>Project</span><select value={projectId} onChange={event => setProjectId(event.target.value)}>
            <option value="">All projects</option>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select></label>
          <label><span>Manufacturer</span><input value={manufacturer} onChange={event => setManufacturer(event.target.value)} placeholder="e.g. Espressif" /></label>
          <label><span>Updated from</span><input type="date" value={updatedAfter} onChange={event => setUpdatedAfter(event.target.value)} /></label>
          <label><span>Updated to</span><input type="date" value={updatedBefore} onChange={event => setUpdatedBefore(event.target.value)} /></label>
          <label><span>Sort</span><select value={sort} onChange={event => setSort(event.target.value)}>
            <option value="relevance">Relevance</option>
            <option value="name">Name A–Z</option>
            <option value="newest">Recently updated</option>
            <option value="oldest">Oldest updated</option>
          </select></label>
        </div>
      </div>

      <section className="panel searchResultsPanel">
        <div className="panelHead">
          <div><h3>Results</h3><p>{busy ? "Searching…" : String(data?.total || 0) + " result" + (data?.total === 1 ? "" : "s")}</p></div>
          {query.trim() && <Badge tone="accent">{query.trim()}</Badge>}
        </div>
        {error && <div className="inlineError">{error}</div>}
        {busy && !data ? <LoadingBlock label="Searching MakerVault…" /> : <div className="searchResults">
          {(data?.rows || []).map(row => <button type="button" className="searchResultCard" key={row.type + ":" + row.id} onClick={() => onOpenResult(row)}>
            <div className="searchResultMain">
              <div className="searchResultTitle"><Badge>{row.type_label}</Badge>{row.badge && <Badge tone="accent">{row.badge}</Badge>}</div>
              <strong>{row.title}</strong>
              <p>{row.subtitle || row.status || "MakerVault record"}</p>
            </div>
            <div className="searchResultMeta">
              {row.status && <span>{row.status}</span>}
              {row.updated_at && <small>{formatDate(row.updated_at)}</small>}
              <span className="searchOpenArrow">→</span>
            </div>
          </button>)}
          {!busy && !(data?.rows || []).length && <div className="searchEmpty">
            <strong>No results match these filters.</strong>
            <span>Try a broader search term or enable additional record types.</span>
          </div>}
        </div>}
      </section>
    </section>
  </div>;
}
