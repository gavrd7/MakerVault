import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, LoadingBlock } from "./Common";

function tone(percent) {
  if (percent >= 90) return "good";
  if (percent >= 70) return "accent";
  return "danger";
}

export default function CatalogueCoveragePanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const result = await apiFetch("/api/settings/catalogue-coverage/");
      setData(result);
    } catch (err) {
      setError(err.message || "MakerVault could not audit catalogue coverage.");
    }
  }

  useEffect(() => { load(); }, []);

  return <section className="panel settingsPanel catalogueCoveragePanel">
    <div className="panelHead">
      <div>
        <h3>Catalogue coverage</h3>
        <p>Live completeness audit for the shared reference catalogues. This identifies where the next enrichment pass should focus.</p>
      </div>
      <button type="button" onClick={load}>Refresh audit</button>
    </div>
    {error && <div className="inlineError">{error}</div>}
    {!data ? <LoadingBlock label="Auditing catalogue coverage…" /> : <div className="catalogueCoverageGrid">
      {(data.catalogues || []).map(catalogue => <article className="catalogueCoverageCard" key={catalogue.key}>
        <div className="catalogueCoverageHead">
          <div><strong>{catalogue.label}</strong><small>{catalogue.total} records</small></div>
        </div>
        <div className="catalogueCoverageMetrics">
          {(catalogue.metrics || []).map(metric => <div className="catalogueCoverageMetric" key={metric.key}>
            <div>
              <span>{metric.label}</span>
              <Badge tone={tone(metric.percent)}>{metric.percent}%</Badge>
            </div>
            <div className="coverageMeter"><span style={{ width: Math.min(metric.percent, 100) + "%" }} /></div>
            <small>{metric.complete} complete · {metric.missing} missing</small>
          </div>)}
        </div>
        {!!catalogue.missing_samples?.length && <details className="catalogueCoverageSamples">
          <summary>Examples needing attention</summary>
          <div>
            {catalogue.missing_samples.map(item => <span key={item.id}>
              <strong>{item.name}</strong>
              <small>{[
                ...(item.missing || []),
                ...(item.missing_image ? ["image"] : []),
                ...((item.unresolved_fields || []).slice(0, 4)),
              ].join(" · ")}</small>
            </span>)}
          </div>
        </details>}
      </article>)}
    </div>}
  </section>;
}
