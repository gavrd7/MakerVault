import React, { useMemo, useState } from "react";

/**
 * Incremental read-only preview for generated G-code.
 *
 * This is a bounded, sampled extrusion visualisation. Native slicer estimates
 * come from G-code metadata. Layer and step controls operate on the available
 * sample, not a claim of complete simulation; missing categories remain gated.
 */
const PALETTE = ["#6ddfc7", "#be9aff", "#fbbf75", "#7eb6ff", "#ef9ab1", "#e1d781"];
const COLOUR_MODES = [
  { value: "feature", label: "Line type", supported: true },
  { value: "layer", label: "Layer height / Z", supported: true },
  { value: "filament", label: "Filament", supported: false },
  { value: "speed", label: "Speed", supported: false },
  { value: "line-width", label: "Line width", supported: false },
  { value: "flow", label: "Flow", supported: false },
  { value: "layer-time", label: "Layer time", supported: false },
  { value: "fan", label: "Fan speed", supported: false },
  { value: "temperature", label: "Temperature", supported: false },
  { value: "acceleration", label: "Acceleration", supported: false },
];

export default function SlicerGcodePreview({ preview }) {
  const [layer, setLayer] = useState(null);
  const [step, setStep] = useState(null);
  const [colourMode, setColourMode] = useState("feature");
  const [visible, setVisible] = useState({});
  const [showToolhead, setShowToolhead] = useState(true);
  const layers = preview?.layers || [];
  const allSegments = preview?.segments || [];
  const currentLayer = Math.min(layer ?? Math.max(0, layers.length - 1), Math.max(0, layers.length - 1));
  const z = layers[currentLayer];

  const features = Object.keys(preview?.feature_counts || {});
  const colours = Object.fromEntries(features.map((feature, index) => [feature, PALETTE[index % PALETTE.length]]));
  const allBounds = useMemo(() => {
    if (!allSegments.length) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const segment of allSegments) {
      minX = Math.min(minX, segment[0], segment[2]);
      maxX = Math.max(maxX, segment[0], segment[2]);
      minY = Math.min(minY, segment[1], segment[3]);
      maxY = Math.max(maxY, segment[1], segment[3]);
    }
    const span = Math.max(maxX - minX, maxY - minY, 1);
    const point = (x, y) => [
      20 + (x - minX) * 560 / span,
      580 - (y - minY) * 560 / span,
    ];
    return { point };
  }, [allSegments]);
  const layerSegments = useMemo(() =>
    z == null ? [] : allSegments.filter(segment => Math.abs(segment[4] - z) < 0.0005),
    [allSegments, z]);
  const finalStep = Math.min(step ?? layerSegments.length, layerSegments.length);
  const shownSegments = useMemo(() => layerSegments.slice(0, finalStep)
    .filter(segment => visible[segment[5]] !== false), [layerSegments, finalStep, visible]);
  // Toolhead follows the actual selected sampled step, even if its feature is hidden.
  const toolhead = finalStep > 0 && allBounds ? allBounds.point(
    layerSegments[finalStep - 1][2], layerSegments[finalStep - 1][3]) : null;
  function lineColour(segment) {
    if (colourMode === "layer") {
      const ratio = layers.length > 1 ? currentLayer / (layers.length - 1) : 0;
      return `hsl(${200 - 160 * ratio} 85% 64%)`;
    }
    return colours[segment[5]] || "#b8d4e5";
  }
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
      <div className="slicerResultModeRow">
        <label>Colour by
          <select value={colourMode} onChange={e => setColourMode(e.target.value)}>
            {COLOUR_MODES.map(mode => <option key={mode.value} value={mode.value}
              disabled={!mode.supported}>{mode.label}{mode.supported ? "" : " · unavailable"}</option>)}
          </select>
        </label>
        <label className="checkRow"><input type="checkbox" checked={showToolhead}
          onChange={e => setShowToolhead(e.target.checked)} /> Show toolhead marker</label>
      </div>
      <div className="slicerResultLayerLayout">
        <div className="slicerResultViewport">
          <svg viewBox="0 0 600 600" role="img"
            aria-label="Top-down sampled extrusion toolpaths with toolhead position"
            className="slicerResultToolpath">
            {allBounds && shownSegments.map((segment, index) => {
              const [x1, y1] = allBounds.point(segment[0], segment[1]);
              const [x2, y2] = allBounds.point(segment[2], segment[3]);
              return <line key={index} x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={lineColour(segment)} strokeWidth="1.8" strokeLinecap="round" />;
            })}
            {showToolhead && toolhead && <>
              <circle cx={toolhead[0]} cy={toolhead[1]} r="7" fill="#f97316"
                stroke="#fff" strokeWidth="1.5" aria-label="Current sampled toolhead location" />
              <line x1={toolhead[0]-12} x2={toolhead[0]+12}
                y1={toolhead[1]} y2={toolhead[1]} stroke="#f97316" strokeWidth="1" />
              <line x1={toolhead[0]} x2={toolhead[0]}
                y1={toolhead[1]-12} y2={toolhead[1]+12} stroke="#f97316" strokeWidth="1" />
            </>}
          </svg>
          <div className="slicerResultSteps">
            <label htmlFor="slice-step-slider">Sampled toolhead step {finalStep} / {layerSegments.length}</label>
            <input id="slice-step-slider" type="range" min="0" max={layerSegments.length}
              step="1" value={finalStep} onChange={e => setStep(Number(e.target.value))} />
            <div className="settingsActions">
              <button type="button" disabled={finalStep <= 0} onClick={() => setStep(Math.max(0, finalStep - 1))}
                aria-label="Previous sampled toolhead step">◀</button>
              <button type="button" disabled={finalStep >= layerSegments.length}
                onClick={() => setStep(Math.min(layerSegments.length, finalStep + 1))}
                aria-label="Next sampled toolhead step">▶</button>
              <button type="button" onClick={() => setStep(null)}>Show entire sampled layer</button>
            </div>
          </div>
        </div>
        <label className="slicerResultLayerSlider" htmlFor="slice-layer-slider">
          <span>Layer {currentLayer + 1} / {layers.length}</span>
          <input id="slice-layer-slider" type="range" min="0"
            max={Math.max(0, layers.length - 1)} step="1" value={currentLayer}
            onChange={e => { setLayer(Number(e.target.value)); setStep(null); }} />
          <span>Z {z?.toFixed(2)} mm</span>
        </label>
      </div>
      <fieldset className="slicerResultVisibility">
        <legend>Visible extrusion features</legend>
        {features.map(feature => <label className="checkRow" key={feature}>
          <input type="checkbox" checked={visible[feature] !== false}
            onChange={e => setVisible(state => ({ ...state, [feature]: e.target.checked }))} />
          <i style={{ background: colours[feature] }} aria-hidden="true" />
          {feature} ({preview.feature_counts[feature]?.toLocaleString() || 0})
        </label>)}
      </fieldset>
      <p className="projectUploadHint">Travel, retract, wipe, speed, flow, filament mapping and other
        native preview modes require a complete indexed toolpath. They are not represented by this extrusion-only sample.</p>
    </> : <p>No extrusion paths were available for the preview.</p>}
    <small>Times and material are slicer-declared estimates. Layer selection and horizontal steps
      operate on sampled extrusion moves only; paths can be omitted. This is not a complete
      OrcaSlicer simulation or printer-safety check.</small>
    {preview?.sampled && <p className="projectUploadHint">Preview is partial; the G-code contains
      additional paths beyond this bounded sample.</p>}
  </div>;
}
