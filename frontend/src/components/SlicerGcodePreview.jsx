import React, { useMemo, useState } from "react";
import SlicerToolpath3D from "./SlicerToolpath3D";

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
  { value: "solid", label: "Solid print (single preview colour)", supported: true },
  { value: "filament", label: "Filament", supported: false },
  { value: "speed", label: "Speed", supported: false },
  { value: "line-width", label: "Line width", supported: false },
  { value: "flow", label: "Flow", supported: false },
  { value: "layer-time", label: "Layer time", supported: false },
  { value: "fan", label: "Fan speed", supported: false },
  { value: "temperature", label: "Temperature", supported: false },
  { value: "acceleration", label: "Acceleration", supported: false },
];

export default function SlicerGcodePreview({ preview, bedSize = null }) {
  const [layer, setLayer] = useState(null);
  const [step, setStep] = useState(null);
  const [colourMode, setColourMode] = useState("feature");
  const [renderMode, setRenderMode] = useState("solid");
  const [visible, setVisible] = useState({});
  const [showToolhead, setShowToolhead] = useState(true);
  const layers = preview?.layers || [];
  const allSegments = preview?.segments || [];
  const currentLayer = Math.min(layer ?? Math.max(0, layers.length - 1), Math.max(0, layers.length - 1));
  const z = layers[currentLayer];

  const features = Object.keys(preview?.feature_counts || {});
  const colours = Object.fromEntries(features.map((feature, index) => [feature, PALETTE[index % PALETTE.length]]));
  const layerSegments = useMemo(() =>
    z == null ? [] : allSegments.filter(segment => Math.abs(segment[4] - z) < 0.0005),
    [allSegments, z]);
  const finalStep = Math.min(step ?? layerSegments.length, layerSegments.length);
  const formatTime = seconds => {
    if (seconds == null) return "Not declared";
    const hours = Math.floor(seconds / 3600), mins = Math.ceil((seconds % 3600) / 60);
    return hours ? `${hours}h ${mins}m` : `${mins}m`;
  };
  const metric = (value, unit) => value == null ? "Not declared" : `${value.toLocaleString()} ${unit}`;

  return <div className="slicerResultPreview">
    <div className="slicerResultStats">
      <div><small>Estimated print time · slicer</small><strong>{formatTime(preview?.estimated_time_seconds)}</strong></div>
      <div><small>Filament length</small><strong>{metric(preview?.filament_mm, "mm")}</strong></div>
      <div><small>Filament weight</small><strong>{metric(preview?.filament_g, "g")}</strong></div>
      <div><small>Filament volume</small><strong>{metric(preview?.filament_cm3, "cm³")}</strong></div>
      <div><small>Extrusion layers</small><strong>{preview?.layer_count ?? "Partial"}</strong></div>
    </div>
    {layers.length > 0 ? <>
      <div className="slicerResultModeRow">
        <label>Preview style
          <select value={renderMode} onChange={e => setRenderMode(e.target.value)}>
            <option value="solid">Solid filament paths</option>
            <option value="lines">Tool movement lines</option>
          </select>
        </label>
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
          <SlicerToolpath3D segments={allSegments} layers={layers}
            activeLayer={currentLayer} activeStep={finalStep} visible={visible}
            colourMode={colourMode} colours={colours} showToolhead={showToolhead} bedSize={bedSize}
            renderMode={renderMode} />
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
      <p className="projectUploadHint">Travel, retract, wipe, speed, flow, per-tool colour mapping and other
        native preview modes require a complete indexed toolpath. They are not represented by this extrusion-only sample.</p>
    </> : <p>No extrusion paths were available for the preview.</p>}
    <small>Print time comes from the generated G-code and depends on the selected printer and native profiles; it is not a manually editable value. Times and material are slicer-declared estimates. Layer selection and horizontal steps
      operate on sampled extrusion moves only; paths can be omitted. This is not a complete
      OrcaSlicer simulation or printer-safety check.</small>
    <p className="slicerPreviewCoverage" role="status">
      Displaying {allSegments.length.toLocaleString()} of {(preview?.segment_count ?? allSegments.length).toLocaleString()} detected deposited moves
      {preview?.sampled ? " · partial toolpath sample" : " · all indexed extrusion moves"}.
      Solid preview draws bead-width geometry; it does not simulate the complete native slicer.
    </p>
    {preview?.sampled && <p className="projectUploadHint">Preview is partial; the G-code contains
      additional paths beyond this bounded sample.</p>}
  </div>;
}
