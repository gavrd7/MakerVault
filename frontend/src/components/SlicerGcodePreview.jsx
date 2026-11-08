import React, { useMemo, useState } from "react";

/** Read-only slice results. The visual sample is not a complete G-code simulator. */
export default function SlicerGcodePreview({ preview }) {
  const [layer, setLayer] = useState(null);
  const layers = preview?.layers || [];
  const current = Math.min(layer ?? Math.max(0, layers.length - 1), Math.max(0, layers.length - 1));
  const height = layers[current];
  const display = useMemo(() => {
    const segments = preview?.segments || [];
    const shown = height == null ? segments :
      segments.filter(s => Math.abs(s[4] - height) < 0.0005);
    if (!shown.length) return [];
    const xs = shown.flatMap(s => [s[0], s[2]]);
    const ys = shown.flatMap(s => [s[1], s[3]]);
    const lowX = Math.min(...xs), highX = Math.max(...xs);
    const lowY = Math.min(...ys), highY = Math.max(...ys);
    const span = Math.max(highX - lowX, highY - lowY, 1);
    const point = (x, y) => `${(20 + (x - lowX) * 560 / span).toFixed(1)} ${(580 - (y - lowY) * 560 / span).toFixed(1)}`;
    return shown.map((s, i) => ({ id: i, d: `M ${point(s[0], s[1])} L ${point(s[2], s[3])}`, feature: s[5] }));
  }, [preview, height]);

  const features = Object.keys(preview?.feature_counts || {});
  const palette = ["#6ddfc7", "#be9aff", "#fbbf75", "#7eb6ff", "#ef9ab1", "#e1d781"];
  const colours = Object.fromEntries(features.map((feature, i) => [feature, palette[i % palette.length]]));
  const formatTime = seconds => {
    if (seconds == null) return "Not declared";
    const hours = Math.floor(seconds / 3600), mins = Math.ceil((seconds % 3600) / 60);
    return hours ? `${hours}h ${mins}m` : `${mins}m`;
  };
  const metric = (value, unit) => value == null ? "Not declared" : `${value.toLocaleString()} ${unit}`;
  return <div className="slicerResultPreview">
    <div className="slicerResultStats">
      <div><small>Estimated print time</small><strong>{formatTime(preview?.estimated_time_seconds)}</strong></div>
      <div><small>Filament length</small><strong>{metric(preview?.filament_mm, "mm")}</strong></div>
      <div><small>Filament weight</small><strong>{metric(preview?.filament_g, "g")}</strong></div>
      <div><small>Filament volume</small><strong>{metric(preview?.filament_cm3, "cm³")}</strong></div>
      <div><small>Extrusion layers</small><strong>{preview?.layer_count ?? "Partial"}</strong></div>
    </div>
    {layers.length > 0 ? <>
      <label>Preview layer {current + 1} / {layers.length} · Z {height?.toFixed(2)} mm
        <input type="range" min="0" max={Math.max(0, layers.length - 1)} step="1"
          value={current} onChange={e => setLayer(Number(e.target.value))} />
      </label>
      <svg viewBox="0 0 600 600" role="img" aria-label="Sampled extrusion-only layer preview" className="slicerResultToolpath">
        {display.map(path => <path key={path.id} d={path.d}
          stroke={colours[path.feature] || "#b8d4e5"} strokeWidth="1.8"
          strokeLinecap="round" fill="none" />)}
      </svg>
      <div className="slicerResultFeatures">
        {features.map(feature => <span key={feature}><i style={{ background: colours[feature] }} />{feature}</span>)}
      </div>
    </> : <p>No extrusion paths were available for the preview.</p>}
    <small>Estimates are read from slicer-generated G-code metadata, not recalculated by MakerVault. Layer geometry is sampled and may omit paths. This is not a complete OrcaSlicer simulation or printer-safety check.</small>
    {preview?.sampled && <p className="projectUploadHint">Layer preview is partial; the G-code contains more paths than the preview limit.</p>}
  </div>;
}
