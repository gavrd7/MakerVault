import React, { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { LoadingBlock } from "./Common";

export default function AboutPage({ config }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    apiFetch("/api/attributions/").then(setData).catch(err => setError(err.message));
  }, []);

  const groups = useMemo(() => {
    const out = {};
    for (const row of data?.rows || []) {
      const key = row.provider || "External source";
      (out[key] ||= []).push(row);
    }
    return out;
  }, [data]);

  return <div className="aboutStack">
    <section className="panel legalHero">
      <span className="eyebrow">Open source</span>
      <h2>MakerVault {config?.version || ""}</h2>
      <p>MakerVault software is licensed under <strong>{config?.license || "AGPL-3.0-or-later"}</strong>. Third-party catalogue media keeps its own licence and attribution.</p>
      <div className="legalActions">
        <a className="buttonLink primary" href={config?.source_url} target="_blank" rel="noreferrer">Source code ↗</a>
        <a className="buttonLink" href={config?.license_url || "/legal/license/"} target="_blank" rel="noreferrer">View AGPL licence</a>
        <a className="buttonLink" href={config?.third_party_notices_url || "/legal/third-party-notices/"} target="_blank" rel="noreferrer">Third-party notices</a>
      </div>
      <p className="legalFine">MakerVault is provided without warranty, as described in the GNU Affero General Public License.</p>
    </section>

    <section className="panel">
      <div className="panelHead"><div><h3>Media attribution</h3><p>Credits recorded for catalogue images cached by this MakerVault instance.</p></div>{data && <span className="attributionCount">{data.summary.total} records</span>}</div>
      {error && <div className="inlineError">{error}</div>}
      {!data && !error ? <LoadingBlock label="Loading attribution records…" /> : <>
        {data?.summary?.needs_review > 0 && <div className="licenceWarning">{data.summary.needs_review} cached/source-linked item(s) do not have licence metadata recorded. Review their source terms before redistribution or commercial use.</div>}
        <div className="attributionGroups">
          {Object.entries(groups).map(([provider, rows]) => <section key={provider} className="attributionGroup">
            <h4>{provider} <span>{rows.length}</span></h4>
            <div className="attributionTable">
              {rows.map(row => <div className="attributionRow" key={`${row.kind}-${row.id}`}>
                <div><strong>{row.name}</strong><small>{row.kind}</small></div>
                <div><span>{row.author || "Author not recorded"}</span><small>{row.license || "Licence not recorded"}</small></div>
                <div>{row.source_page ? <a href={row.source_page} target="_blank" rel="noreferrer">Source ↗</a> : "—"}</div>
              </div>)}
            </div>
          </section>)}
          {data && data.rows.length === 0 && <div className="noRows">No third-party catalogue image attributions have been recorded yet.</div>}
        </div>
      </>}
    </section>

    <section className="panel legalPolicy">
      <h3>Automatic image policy</h3>
      <p>MakerVault's default automatic image source is Wikimedia Commons, restricted to raster media reported as CC0/Public Domain, CC BY or CC BY-SA. NonCommercial and NoDerivatives licences are excluded from the default automatic path.</p>
      <p>ESPBoards board illustrations are offered under CC BY-NC 4.0. Automatic ESPBoards image caching is therefore disabled by default; users may opt in for an appropriate non-commercial deployment after reviewing the source terms.</p>
    </section>
  </div>;
}
