import React, { useEffect, useMemo, useRef, useState } from "react";
import SlicerToolpath3D from "./SlicerToolpath3D";
import "./slicerPreviewMobile.css";
import GcodeLayerInsert from "./GcodeLayerInsert";
import { featureColour, hasFeatureFocus } from "./slicerToolpathFeatures";

/**
 * Incremental read-only preview for generated G-code.
 *
 * This is a bounded, sampled extrusion visualisation. Native slicer estimates
 * come from G-code metadata. Layer and step controls operate on the available
 * sample, not a claim of complete simulation; missing categories remain gated.
 */
const COLOUR_MODES = [
  { value: "feature", label: "Line type", supported: true },
  { value: "layer", label: "Layer height / Z", supported: true },
  { value: "solid", label: "Solid print (single preview colour)", supported: true },
  { value: "filament", label: "Logical filament / tool", supported: false },
  { value: "speed", label: "Speed", supported: false },
  { value: "line-width", label: "Line width", supported: false },
  { value: "flow", label: "Flow", supported: false },
  { value: "layer-time", label: "Layer time", supported: false },
  { value: "fan", label: "Fan speed", supported: false },
  { value: "temperature", label: "Temperature", supported: false },
  { value: "acceleration", label: "Acceleration", supported: false },
];

export default function SlicerGcodePreview({ fileId = null, preview, bedSize = null, file = null, canEdit = false, onSaved = null, startTemperatures = null }) {
  const [mobilePanel, setMobilePanel] = useState(null);
  const [layer, setLayer] = useState(null);
  const [step, setStep] = useState(null);
  const [colourMode, setColourMode] = useState("feature");
  const [renderMode, setRenderMode] = useState("solid");
  const [layerDisplay, setLayerDisplay] = useState("all");
  const [highlightCurrent, setHighlightCurrent] = useState(false);
  const [featureFocus, setFeatureFocus] = useState("all");
  const [outerContrast, setOuterContrast] = useState(false);
  const previousInspectionSettings = useRef(null);
  const toggleOuterInspection = (enabled) => {
    if (enabled) {
      previousInspectionSettings.current = {
        renderMode, layerDisplay, featureFocus, highlightCurrent,
      };
      // A sampled all-layer solid model visually piles disconnected bead
      // rectangles on top of one another. Use exact selected-layer centreline
      // geometry when inspecting fuzzy-skin displacement.
      setRenderMode("lines");
      setLayerDisplay("current");
      setFeatureFocus("outer");
      setHighlightCurrent(false);
    } else if (previousInspectionSettings.current) {
      const previous = previousInspectionSettings.current;
      setRenderMode(previous.renderMode);
      setLayerDisplay(previous.layerDisplay);
      setFeatureFocus(previous.featureFocus);
      setHighlightCurrent(previous.highlightCurrent);
      previousInspectionSettings.current = null;
    }
    setOuterContrast(enabled);
  };
  const [visible, setVisible] = useState({});
  const [showToolhead, setShowToolhead] = useState(false);
  const [exactLayer, setExactLayer] = useState(null);
  const [layerBusy, setLayerBusy] = useState(false);
  const [layerError, setLayerError] = useState("");
  const [showLayerInsert, setShowLayerInsert] = useState(false);
  const fullLayerCache = useRef(new Map());
  const layers = preview?.layers || [];
  const allSegments = preview?.segments || [];
  const currentLayer = Math.min(layer ?? Math.max(0, layers.length - 1), Math.max(0, layers.length - 1));
  const z = layers[currentLayer];

  const features = Object.keys(preview?.feature_counts || {});
  const colours = Object.fromEntries(features.map(feature => [feature, featureColour(feature)]));
  // Query original stored G-code for this exact layer. Global 80k-move
  // samples are not sufficient for continuous wall and support geometry.
  useEffect(() => {
    if (!fileId || !Number.isFinite(z)) return undefined;
    const key = String(fileId) + ":" + Number(z).toFixed(3);
    const cached = fullLayerCache.current.get(key);
    if (cached) {
      setExactLayer(cached);
      setLayerError("");
      setLayerBusy(false);
      return undefined;
    }
    let live = true;
    const controller = new AbortController();
    setExactLayer(null);
    setLayerError("");
    setLayerBusy(true);
    fetch(`/api/files/${encodeURIComponent(fileId)}/gcode/layer/?z=${encodeURIComponent(z.toFixed(3))}`, {
      credentials: "same-origin", signal: controller.signal,
    }).then(async response => {
      if (!response.ok) {
        let message = `Layer retrieval failed (HTTP ${response.status}).`;
        try { message = (await response.json()).error || message; } catch { /* Retain HTTP detail. */ }
        throw new Error(message);
      }
      return response.json();
    }).then(data => {
      if (!live) return;
      if (!Array.isArray(data.segments)) throw new Error("Invalid layer response.");
      fullLayerCache.current.set(key, data);
      // Retain only a small number of recent layers in browser memory.
      if (fullLayerCache.current.size > 12) {
        fullLayerCache.current.delete(fullLayerCache.current.keys().next().value);
      }
      setExactLayer(data);
    }).catch(error => {
      if (live && error.name !== "AbortError") setLayerError(error.message);
    }).finally(() => { if (live) setLayerBusy(false); });
    return () => { live = false; controller.abort(); };
  }, [fileId, z]);

  const layerSegments = useMemo(() => {
    if (exactLayer?.z != null && Math.abs(exactLayer.z - z) < 0.0005)
      return exactLayer.segments;
    // While loading, do not pretend that the sparse global sample is exact.
    return [];
  }, [exactLayer, z]);
  const displaySegments = useMemo(() => {
    const current = layerSegments;
    if (layerDisplay === "current") return current;
    const previous = allSegments.filter(segment =>
      Math.abs(segment[4] - z) > 0.0005 && segment[4] <= z);
    return [...previous, ...current];
  }, [allSegments, layerSegments, layerDisplay, z]);
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
      <div><small>Requested nozzle · G-code</small><strong>{startTemperatures?.nozzle_c != null ? startTemperatures.nozzle_c + " °C" : "Not declared"}</strong></div>
      <div><small>Requested bed · G-code</small><strong>{startTemperatures?.bed_c != null ? startTemperatures.bed_c + " °C" : "Not declared"}</strong></div>
    </div>
    {layers.length > 0 ? <>

      {mobilePanel && <div className="slicerPreviewBackdrop" onClick={() => setMobilePanel(null)} aria-hidden="true" />}
      <div className={"slicerResultModeRow slicerPreviewOptionsPanel" + (mobilePanel === "display" ? " mobileOpen" : "")}
        role={mobilePanel === "display" ? "dialog" : undefined}
        aria-modal={mobilePanel === "display" ? "true" : undefined}
        aria-label={mobilePanel === "display" ? "Display settings" : undefined}>
        <div className="slicerPreviewPanelHeader"><strong>Display settings</strong>
          <button type="button" onClick={() => setMobilePanel(null)}>Close</button>
        </div>
        <label>Preview style
          <select value={renderMode} onChange={e => setRenderMode(e.target.value)}>
            <option value="solid">Solid filament paths</option>
            <option value="lines">Tool movement lines</option>
          </select>
        </label>
        <label>Colour by
          <select value={colourMode} onChange={e => setColourMode(e.target.value)}>
            {COLOUR_MODES.map(mode => {
              const available = mode.value === "filament"
                ? (preview?.observed_tools?.length || 0) > 0
                : mode.supported;
              return <option key={mode.value} value={mode.value}
                disabled={!available}>{mode.label}{available ? "" : " · unavailable"}</option>;
            })}
          </select>
        </label>
        <label>Layer visibility
          <select value={layerDisplay} onChange={event => setLayerDisplay(event.target.value)}>
            <option value="current">Current layer only · detail</option>
            <option value="context">Current + 8 faded layers</option>
            <option value="all">{preview?.sampled || preview?.complete === false
              ? "All earlier layers · sampled overview"
              : "Complete model · all extrusion paths"}</option>
          </select>
        </label>
        <label>Feature focus
          <select value={featureFocus} onChange={event => setFeatureFocus(event.target.value)}>
            <option value="all">All extrusion types</option>
            <option value="support" disabled={!hasFeatureFocus(features, "support")}>Support + interface</option>
            <option value="outer" disabled={!hasFeatureFocus(features, "outer")}>Outer walls only · fuzzy-skin inspection</option>
            <option value="walls" disabled={!hasFeatureFocus(features, "walls")}>Walls / perimeters</option>
            <option value="shell" disabled={!hasFeatureFocus(features, "shell")}>Shell detail · hide internal infill</option>
            <option value="infill" disabled={!hasFeatureFocus(features, "infill")}>Infill / solid / bridge</option>
          </select>
        </label>
        <label className="checkRow"><input type="checkbox" checked={outerContrast}
          onChange={e => toggleOuterInspection(e.target.checked)} />
          Inspect outer walls (clean lines)
        </label>
        <label className="checkRow"><input type="checkbox" checked={highlightCurrent}
          disabled={layerDisplay==="current"}
          onChange={e => setHighlightCurrent(e.target.checked)} />
          Fade previous layers
        </label>
        <label className="checkRow"><input type="checkbox" checked={showToolhead}
          onChange={e => setShowToolhead(e.target.checked)} /> Show toolhead marker</label>
      </div>
      {colourMode === "filament" && <div className="slicerLogicalToolNotice" role="status">
        Logical tool colours are illustrative. They do not confirm physical
        CFS/AMS bay mapping or actual filament colour. Recorded tools:
        {" "}{(preview?.observed_tools || []).map(tool => "T"+tool).join(", ") || "unknown"}.
      </div>}
      <div className="slicerResultLayerLayout">
        <div className="slicerResultViewport">
          <SlicerToolpath3D segments={displaySegments} layers={layers}
            activeLayer={currentLayer} activeStep={finalStep} visible={visible}
            colourMode={colourMode} colours={colours} showToolhead={showToolhead} bedSize={bedSize}
            renderMode={renderMode} layerDisplay={layerDisplay}
            previewSampled={!!preview?.sampled || preview?.complete === false} fadePrevious={highlightCurrent}
            featureFocus={featureFocus} outerContrast={outerContrast}
            toolbarActions={<>
              <button type="button" aria-expanded={mobilePanel === "display"}
                onClick={() => setMobilePanel("display")}>Display settings</button>
              <button type="button" aria-expanded={mobilePanel === "features"}
                onClick={() => setMobilePanel("features")}>Toolpaths</button>
            </>} />
          <div className="slicerResultSteps">
            <label htmlFor="slice-step-slider">{exactLayer && !exactLayer.limited ? "Full-resolution" : "Available"} layer move {finalStep} / {layerSegments.length}</label>
            <input id="slice-step-slider" className="slicerFullRange" type="range" min="0" max={layerSegments.length}
              step="1" value={finalStep} onChange={e => setStep(Number(e.target.value))} />
            <div className="settingsActions">
              <button type="button" onClick={() => setStep(null)}>Show entire selected layer</button>
            </div>
          </div>
        </div>
        <label className="slicerResultLayerSlider" htmlFor="slice-layer-slider">
          <span>Layer {currentLayer + 1} / {layers.length}</span>
          <input id="slice-layer-slider" className="slicerFullRange" type="range" min="0"
            max={Math.max(0, layers.length - 1)} step="1" value={currentLayer}
            onChange={e => { setLayer(Number(e.target.value)); setStep(null); }} />
          <span>Z {z?.toFixed(2)} mm</span>
          {canEdit && fileId && file && <button type="button" className="slicerGcodeInsertButton"
            onClick={() => setShowLayerInsert(value => !value)} aria-expanded={showLayerInsert}
            aria-label="Add G-code at selected layer" title="Add G-code after selected layer">
            + G-code
          </button>}
        </label>
      </div>
      {showLayerInsert && canEdit && fileId && file && <GcodeLayerInsert
        key={String(currentLayer) + ":" + String(fileId)}
        file={file} selectedZ={z} nextZ={layers[currentLayer + 1]}
        onSaved={onSaved} onCancel={() => setShowLayerInsert(false)} />}
      <div className="slicerPreviewCoverage" role="status">
        {layerBusy ? "Loading complete toolpaths for the selected layer…" :
          layerError ? "Full-resolution layer unavailable: " + layerError :
          exactLayer?.limited ? `Layer contains ${exactLayer.segment_count.toLocaleString()} moves; only the first ${exactLayer.segments.length.toLocaleString()} are shown. Reduce model complexity or increase the server limit.` :
          exactLayer ? `Full-resolution layer: ${exactLayer.segments.length.toLocaleString()} consecutive extrusion moves at Z ${z?.toFixed(3)} mm.` :
          "Select a G-code layer to inspect its complete extrusion paths."}
      </div>
      {layerDisplay !== "current" && (preview?.sampled || preview?.complete === false) && <p className="projectUploadHint">
        This overview is incomplete because the toolpath exceeds the preview budget.
        Current layer only retrieves precise geometry; missing small details do not imply missing G-code.
      </p>}

      <fieldset className={"slicerResultVisibility slicerPreviewOptionsPanel" + (mobilePanel === "features" ? " mobileOpen" : "")}
        role={mobilePanel === "features" ? "dialog" : undefined}
        aria-modal={mobilePanel === "features" ? "true" : undefined}
        aria-label={mobilePanel === "features" ? "Visible toolpaths" : undefined}>
        <legend>Visible toolpaths</legend>
        <div className="slicerPreviewPanelHeader"><strong>Visible toolpaths</strong>
          <button type="button" onClick={() => setMobilePanel(null)}>Close</button>
        </div>
        {features.map(feature => <label className="checkRow" key={feature}>
          <input type="checkbox" checked={visible[feature] !== false}
            onChange={e => setVisible(state => ({ ...state, [feature]: e.target.checked }))} />
          <i style={{ background: colours[feature] }} aria-hidden="true" />
          {feature} ({preview.feature_counts[feature]?.toLocaleString() || 0})
        </label>)}
      </fieldset>

    </> : <p>No extrusion paths were available for the preview.</p>}

    {(preview?.unresolved_arc_moves || 0) > 0 && <p className="projectUploadHint" role="status">
      {preview.unresolved_arc_moves.toLocaleString()} unsupported curved extrusion move(s)
      could not be drawn faithfully. The original G-code has not been altered.
    </p>}

  </div>;
}
