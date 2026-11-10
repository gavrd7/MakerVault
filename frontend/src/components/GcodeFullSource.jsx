import React, { useEffect, useMemo, useState } from "react";

/**
 * Full, read-only G-code inspection. Unlike the bounded analysis preview, this
 * retrieves the stored source and pages the text rather than rendering every
 * command in a textarea. No partial text is ever offered as a complete copy.
 */
const PAGE_LINES = 400;
const formatSize = bytes => bytes >= 1048576
  ? `${(bytes / 1048576).toFixed(2)} MiB` : `${(bytes / 1024).toFixed(1)} KiB`;

export default function GcodeFullSource({ fileId }) {
  const [source, setSource] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [jump, setJump] = useState("");
  const [selectedObject, setSelectedObject] = useState("");
  const [notice, setNotice] = useState("");
  const url = `/api/files/${encodeURIComponent(fileId)}/gcode/source/`;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setSource(null); setPage(0);
    fetch(url, { credentials: "same-origin", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`Unable to retrieve complete G-code (HTTP ${response.status}).`);
        const blob = await response.blob();
        const text = await blob.text();
        if (text.includes("\0")) throw new Error("Binary G-code cannot be displayed as plain text.");
        setSource({ text, bytes: blob.size });
      })
      .catch(err => { if (err.name !== "AbortError") setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [url]);

  const lines = useMemo(() => source ? source.text.split(/\r?\n/) : [], [source]);
  const pages = Math.max(1, Math.ceil(lines.length / PAGE_LINES));
  const objects = useMemo(() => {
    const names = new Set();
    for (const line of lines) {
      const match = /^EXCLUDE_OBJECT_(?:DEFINE|START)\s+NAME=([^\s]+)/.exec(line);
      if (match) names.add(match[1]);
    }
    return [...names];
  }, [lines]);
  const objectStats = useMemo(() => {
    const stats = new Map();
    let object = null;
    let feature = "";
    for (const line of lines) {
      const start = /^EXCLUDE_OBJECT_START\s+NAME=([^\s]+)/.exec(line);
      if (start) { object = start[1]; if (!stats.has(object)) stats.set(object, { outer: 0, inner: 0, sparse: 0, solid: 0, total: 0 }); continue; }
      if (/^EXCLUDE_OBJECT_END\b/.test(line)) { object = null; continue; }
      const type = /^;TYPE:(.*)/.exec(line);
      if (type) { feature = type[1].trim().toLowerCase(); continue; }
      if (!object || !/^G[123]\s/.test(line)) continue;
      const extrusion = /(?:^|\s)E(-?\d+(?:\.\d+)?)/.exec(line);
      if (!extrusion || Number(extrusion[1]) <= 0) continue;
      const stat = stats.get(object);
      stat.total += 1;
      if (feature.includes("outer wall") || feature.includes("external perimeter")) stat.outer += 1;
      else if (feature.includes("inner wall") || feature === "perimeter") stat.inner += 1;
      else if (feature.includes("sparse infill") || feature === "internal infill") stat.sparse += 1;
      else if (feature.includes("solid infill")) stat.solid += 1;
    }
    return [...stats].map(([name, counts]) => ({ name, ...counts }));
  }, [lines]);
  const pageText = useMemo(() => lines.slice(page * PAGE_LINES, (page + 1) * PAGE_LINES)
    .map((line, index) => `${page * PAGE_LINES + index + 1}: ${line}`).join("\n"), [lines, page]);

  const goToLine = value => {
    const line = Number(value);
    if (!Number.isInteger(line) || line < 1 || line > lines.length) {
      setNotice("Enter a line number within the file."); return;
    }
    setPage(Math.floor((line - 1) / PAGE_LINES));
    setNotice(`Showing line ${line.toLocaleString()}.`);
  };
  const findNext = needle => {
    if (!needle) return;
    const first = Math.min(lines.length, (page + 1) * PAGE_LINES);
    let at = lines.findIndex((line, index) => index >= first && line.toLowerCase().includes(needle.toLowerCase()));
    if (at < 0) at = lines.findIndex(line => line.toLowerCase().includes(needle.toLowerCase()));
    if (at < 0) { setNotice("No matching G-code line."); return; }
    setPage(Math.floor(at / PAGE_LINES));
    setNotice(`Found match at line ${(at + 1).toLocaleString()}.`);
  };

  const copyEntireFile = async () => {
    try {
      if (!source) return;
      await navigator.clipboard.writeText(source.text);
      setNotice(`Copied all ${lines.length.toLocaleString()} lines.`);
    } catch {
      setNotice("Clipboard access was unavailable. Use Download complete G-code instead.");
    }
  };

  return <div className="gcodeFullSource">
    {loading && <p role="status">Loading complete G-code from storage…</p>}
    {error && <div className="formError" role="alert">{error}</div>}
    {source && <>
      <p role="status"><strong>Complete stored G-code:</strong> {lines.length.toLocaleString()} lines · {formatSize(source.bytes)}. The visual toolpath remains a sampled preview.</p>
      <div className="formActions" style={{ justifyContent: "flex-start", flexWrap: "wrap" }}>
        <button type="button" onClick={copyEntireFile}>Copy entire G-code</button>
        <a className="assetButton" href={url + "?download=1"}>Download complete G-code</a>
        <label>Find text <input aria-label="Find G-code text" value={query} onChange={event => setQuery(event.target.value)} /></label>
        <button type="button" disabled={!query} onClick={() => findNext(query)}>Find next</button>
        <label>Go to line <input aria-label="Go to G-code line" type="number" min="1" max={lines.length} value={jump} onChange={event => setJump(event.target.value)} style={{ maxWidth: 110 }} /></label>
        <button type="button" onClick={() => goToLine(jump)}>Go</button>
      </div>
      {objects.length > 0 && <div className="formActions" style={{ justifyContent: "flex-start" }}>
        <label>Jump to object
          <select value={selectedObject} onChange={event => {
            const name = event.target.value;
            setSelectedObject(name);
            if (name) findNext(`EXCLUDE_OBJECT_START NAME=${name}`);
          }}>
            <option value="">Select object</option>
            {objects.map(name => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
      </div>}
      {objectStats.length > 0 && <div style={{ overflowX: "auto" }}>
        <h4>Per-object toolpath evidence</h4>
        <table className="dataTable" style={{ width: "100%" }}>
          <thead><tr><th>Object</th><th>Outer-wall extrusion moves</th><th>Inner-wall extrusion moves</th><th>Sparse-infill extrusion moves</th><th>Solid-infill extrusion moves</th></tr></thead>
          <tbody>{objectStats.map(item => <tr key={item.name}>
            <td>{item.name}</td><td>{item.outer.toLocaleString()}</td><td>{item.inner.toLocaleString()}</td>
            <td>{item.sparse.toLocaleString()}</td><td>{item.solid.toLocaleString()}</td>
          </tr>)}</tbody>
        </table>
        <small>These are G-code extrusion command counts, not wall-loop counts or infill percentages. Different counts are evidence of distinct paths, but cannot alone prove that a requested 5-wall or 50% infill override was applied. The slicer's saved per-object settings should be checked separately.</small>
      </div>}
      <div className="formActions" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <button type="button" disabled={page === 0} onClick={() => setPage(p => Math.max(0, p - 1))}>Previous page</button>
        <span>Lines {(page * PAGE_LINES + 1).toLocaleString()}–{Math.min((page + 1) * PAGE_LINES, lines.length).toLocaleString()} of {lines.length.toLocaleString()}</span>
        <button type="button" disabled={page + 1 >= pages} onClick={() => setPage(p => Math.min(pages - 1, p + 1))}>Next page</button>
      </div>
      {notice && <p role="status">{notice}</p>}
      <textarea aria-label="Complete G-code, current page" readOnly spellCheck={false} value={pageText}
        rows={21} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }} />
      <small>Read-only, paged source. Showing {PAGE_LINES} lines per page for responsiveness; Copy and Download use the entire stored file, not the current page.</small>
    </>}
  </div>;
}
