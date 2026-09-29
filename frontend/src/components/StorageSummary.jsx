import React, { useEffect, useState } from "react";
import { apiFetch } from "../api";

const CATEGORIES = [
  ["models", "Models / 3MF"],
  ["project_files", "Project files"],
  ["images", "Images"],
  ["other_files", "Other files"],
];

function formatBytes(value) {
  const bytes = Math.max(Number(value || 0), 0);
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const amount = bytes / (1024 ** index);
  const digits = index >= 3 ? 2 : index === 2 ? 1 : 0;
  return `${amount.toFixed(digits)} ${units[index]}`;
}

export default function StorageSummary() {
  const [storage, setStorage] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    apiFetch("/api/storage/")
      .then(result => {
        if (active) setStorage(result);
      })
      .catch(err => {
        if (active) setError(err.message || "Storage usage could not be loaded.");
      });
    return () => { active = false; };
  }, []);

  if (error) {
    return <section className="panel storagePanel">
      <div className="panelHead"><div><h3>Your storage</h3><p>{error}</p></div></div>
    </section>;
  }

  if (!storage) {
    return <section className="panel storagePanel">
      <div className="panelHead"><div><h3>Your storage</h3><p>Calculating persistent file usage…</p></div></div>
    </section>;
  }

  const percent = storage.unlimited ? 0 : Math.min(Math.max(Number(storage.percent_used || 0), 0), 100);
  const headline = storage.unlimited
    ? `${formatBytes(storage.used_bytes)} used · Unlimited quota`
    : `${formatBytes(storage.used_bytes)} of ${formatBytes(storage.quota_bytes)} used`;

  let warning = "";
  if (storage.warning_level === "full") {
    warning = "Storage quota reached. New persistent uploads are blocked until space is freed or the quota is increased.";
  } else if (storage.warning_level === "critical") {
    warning = "Storage is above 90% of quota. Consider freeing space before your next large upload.";
  } else if (storage.warning_level === "warning") {
    warning = "Storage is above 80% of quota.";
  }

  return <section className={`panel storagePanel storageLevel-${storage.warning_level || "ok"}`}>
    <div className="panelHead storageHead">
      <div>
        <h3>Your storage</h3>
        <p>{headline}</p>
      </div>
      {!storage.unlimited && <strong className="storagePercent">{storage.percent_used}%</strong>}
    </div>
    <div className="storageBody">
      {!storage.unlimited && <div
        className="storageMeter"
        role="progressbar"
        aria-label="Storage quota used"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={Math.round(percent)}
      >
        <span className="storageMeterFill" style={{ width: `${percent}%` }} />
      </div>}
      {warning && <div className="storageWarning">{warning}</div>}
      <div className="storageBreakdown">
        {CATEGORIES.map(([key, label]) => <div className="storageCategory" key={key}>
          <span>{label}</span>
          <strong>{formatBytes(storage.categories?.[key])}</strong>
        </div>)}
      </div>
      <div className="storageFoot">
        <span>{storage.unlimited ? "No storage limit is applied to this account." : `${formatBytes(storage.remaining_bytes)} remaining`}</span>
        <small>Immutable revisions and persistent generated assets count toward usage.</small>
      </div>
    </div>
  </section>;
}
