import React, { useEffect, useMemo, useRef, useState } from "react";
import SlicerToolpath3D from "./SlicerToolpath3D";
import "./slicerPreviewMobile.css";
import GcodeLayerInsert from "./GcodeLayerInsert";
import { featureColour, hasFeatureFocus } from "./slicerToolpathFeatures";

const EMPTY_PATHS = Object.freeze([]);

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

export default function SlicerGcodePreview({ fileId = null, preview, bedSize = null, file = null, canEdit = false, onSaved = null, startTemperatures = null, profileTemperatures = null, filamentColours = {} }) {
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
  // Never draw sparse global samples as though they were a complete print.
  // Fetch consecutive full-resolution layers from the original file instead.
  const [wholeModel, setWholeModel] = useState({
    chunks: [], loadedLayers: 0, complete: false, limited: false,
    loading: false, message: "",
  });
  const sourceLayerHeights = layers.join(",");
  useEffect(() => {
    if (!fileId || !layers.length) return undefined;
    const controller = new AbortController();
    // Retain complete geometry in independent GPU upload batches. The old
    // 700k mobile cutoff silently stopped tall prints halfway through.
    // Streaming batches avoid repeatedly copying the entire model in JS.
    const maxMoves = 1500000;
    let cancelled = false;
    setWholeModel({chunks:[],loadedLayers:0,complete:false,limited:false,loading:true,message:""});
    const load = async () => {
      const chunks = [];
      let used = 0;
      let completed = 0;
      let limited = false;
      let pendingLayers = 0;
      try {
        for (let offset = 0; offset < layers.length && !cancelled; offset += 64) {
          const requested = layers.slice(offset, offset + 64);
          // Cold indexes are prepared by Celery, never synchronously inside
          // a web request. Cached pages load immediately; a failed/unavailable
          // worker falls back to bounded direct parsing after brief polling.
          const url = "/api/files/" + encodeURIComponent(fileId) +
            "/gcode/layers/?quality=full&zs=" + encodeURIComponent(requested.join(","));
          let response;
          for (let attempt=0;attempt<6;attempt++){
            response = await fetch(url + "&warm=1", {
              credentials:"same-origin",signal:controller.signal,
            });
            if(response.status !== 202)break;
            await new Promise(resolve=>setTimeout(resolve,750));
          }
          if(response?.status===202 || response?.status===503 || response?.status>=500){
            response=await fetch(url + "&direct=1",{
              credentials:"same-origin",signal:controller.signal,
            });
          }
          if (!response.ok) {
            const detail = await response.json().catch(()=>({}));
            throw new Error(detail.error || "Preview unavailable (HTTP " + response.status + ").");
          }
          const data = await response.json();
          if (!Array.isArray(data.layers) || data.layers.length !== requested.length)
            throw new Error("Invalid full-resolution layer response.");
          if (data.complete === false) limited = true;
          const batch = [];
          for (const item of data.layers) {
            if (!item.complete) limited = true;
            if (!Array.isArray(item.segments)) throw new Error("Invalid layer geometry.");
            if (used + item.segments.length > maxMoves) {
              limited = true;
              break;
            }
            for (const move of item.segments) batch.push(move);
            used += item.segments.length;
            completed++;
            pendingLayers++;
            // Full-model geometry may coalesce straight runs; exact movement
            // inspection continues to retrieve the unmodified original layer.
          }
          if (cancelled) return;
          // Each completed response becomes one immutable render batch. The
          // renderer appends a new GPU mesh without copying/re-uploading older
          // batches. Keep all layers available rather than stopping at 488.
          if (batch.length) chunks.push(batch);
          if (pendingLayers >= 64 || completed === layers.length || limited) {
            setWholeModel({chunks:chunks.slice(),loadedLayers:completed,
              complete:completed===layers.length&&!limited,limited,
              loading:!limited&&completed<layers.length,message:""});
            pendingLayers = 0;
          }
          if (limited) break;
          // Let camera controls and touch gestures run between large batches.
          await new Promise(resolve=>setTimeout(resolve, 12));
        }
        if (!cancelled) setWholeModel({
          chunks:chunks.slice(),loadedLayers:completed,
          complete:completed===layers.length&&!limited,
          limited,loading:false,message:"",
        });
      } catch (error) {
        if (!cancelled && error.name!=="AbortError") {
          setWholeModel({
            chunks:chunks.slice(),loadedLayers:completed,complete:false,
            limited:true,loading:false,message:error.message,
          });
        }
      }
    };
    load();
    return () => {cancelled=true;controller.abort();};
  // The layer list is stable for an inspected file; avoid restarting when a
  // user changes camera, rendering style, or selected layer.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId, sourceLayerHeights]);

  // Grow the print from its actual loaded height. Otherwise a fully rendered
  // final-layer island floats above still-loading lower geometry.
  const naturalLayer = wholeModel.complete
    ? Math.max(0, layers.length - 1)
    : Math.max(0, wholeModel.loadedLayers - 1);
  const currentLayer = Math.min(layer ?? naturalLayer, Math.max(0, layers.length - 1));
  const z = layers[currentLayer];

  const features = Object.keys(preview?.feature_counts || {});
  // Stable palette identity matters: the GPU mesh effect depends on colours.
  // Recreating this object on every slider event previously invalidated the
  // complete model even though not a single colour had changed.
  const colours = useMemo(() =>
    Object.fromEntries(features.map(feature => [feature, featureColour(feature)])),
    // Only the feature names determine the palette, not slider position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [features.join("|")]);
  // Query original stored G-code for this exact layer. Global 80k-move
  // samples are not sufficient for continuous wall and support geometry.
  useEffect(() => {
    // Scrubbing through the already-rendered model must never initiate a
    // full-file scan. Retrieve exact paths only for detailed current-layer
    // inspection, or when the movement slider is explicitly used.
    if (!fileId || !Number.isFinite(z) || (layerDisplay !== "current" && step === null)) return undefined;
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
  }, [fileId, z, layerDisplay, step]);

  const layerSegments = useMemo(() => {
    if (exactLayer?.z != null && Math.abs(exactLayer.z - z) < 0.0005)
      return exactLayer.segments;
    // While loading, do not pretend that the sparse global sample is exact.
    return [];
  }, [exactLayer, z]);
  // Even when the user drags the layer slider, continue reusing the same
  // complete GPU buffers. The renderer clips them at the selected Z height.
  const progressiveMode=layerDisplay==="all" && !highlightCurrent && !outerContrast;
  const displaySegments = useMemo(() => {
    // GPU-managed chunks are never flattened for the normal whole-print view.
    // Concatenate only for an explicit detailed/filtering inspection.
    if (progressiveMode) return EMPTY_PATHS;
    const current = layerSegments;
    if (layerDisplay === "current") return current;
    const startZ = layerDisplay === "context" ? layers[Math.max(0,currentLayer-8)] : -Infinity;
    const previous = wholeModel.chunks.flat().filter(segment =>
      segment[4] >= startZ - 0.0005 && segment[4] < z - 0.0005);
    return [...previous, ...current];
  }, [wholeModel.chunks,layerSegments,layerDisplay,layers,currentLayer,z,progressiveMode]);
  const finalStep = Math.min(step ?? layerSegments.length, layerSegments.length);
  const formatTime = seconds => {
    if (seconds == null) return "Not declared";
    const hours = Math.floor(seconds / 3600), mins = Math.ceil((seconds % 3600) / 60);
    return hours ? `${hours}h ${mins}m` : `${mins}m`;
  };
  const metric = (value, unit) => value == null ? "Not declared" : `${value.toLocaleString()} ${unit}`;
  const temperatureInfo = key => {
    if (startTemperatures?.[key] != null) return startTemperatures[key] + " °C";
    if (profileTemperatures?.[key] != null) return profileTemperatures[key] + " °C (profile only)";
    return "Not declared";
  };

  return <div className="slicerResultPreview">
    <div className="slicerResultStats">
      <div><small>Estimated print time · slicer</small><strong>{formatTime(preview?.estimated_time_seconds)}</strong></div>
      <div><small>Filament length</small><strong>{metric(preview?.filament_mm, "mm")}</strong></div>
      <div><small>Filament weight</small><strong>{metric(preview?.filament_g, "g")}</strong></div>
      <div><small>Filament volume</small><strong>{metric(preview?.filament_cm3, "cm³")}</strong></div>
      <div><small>Extrusion layers</small><strong>{preview?.layer_count ?? "Partial"}</strong></div>
      <div><small>Requested nozzle · G-code</small><strong>{temperatureInfo("nozzle_c")}</strong></div>
      <div><small>Requested bed · G-code</small><strong>{temperatureInfo("bed_c")}</strong></div>
      <div><small>Requested chamber · G-code</small><strong>{temperatureInfo("chamber_c")}</strong></div>
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
            <option value="all">Whole print · full-detail paths</option>
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
        Tool colours use the slicer's declared filament colours when available,
        with illustrative fallbacks otherwise. These declarations do not confirm
        physical CFS/AMS bay mapping. Recorded tools:
        {" "}{(preview?.observed_tools || []).map(tool => "T"+tool).join(", ") || "unknown"}.
      </div>}
      <div className="slicerResultLayerLayout">
        <div className="slicerResultViewport">
          {((wholeModel.loading && wholeModel.loadedLayers===0) || wholeModel.message) &&
            <div className="slicerPreviewLoadOverlay" role="status">
              {wholeModel.message
                ? "Preview loading issue: " + wholeModel.message
                : "Preparing 3D preview… Existing G-code is unchanged."}
            </div>}
          <SlicerToolpath3D segments={displaySegments} segmentChunks={progressiveMode ? wholeModel.chunks : []} progressiveMode={progressiveMode} framingSegments={preview?.segments || []} filamentColours={filamentColours} layers={layers}
            activeLayer={currentLayer} activeStep={finalStep} visible={visible}
            colourMode={colourMode} colours={colours} showToolhead={showToolhead} bedSize={bedSize}
            renderMode={renderMode} layerDisplay={layerDisplay}
            previewSampled={false} fadePrevious={highlightCurrent}
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
              step="1" value={finalStep} onChange={e => {
                // Movement inspection is the separate, exact-detail mode.
                setLayerDisplay("current");
                setStep(Number(e.target.value));
              }} />
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
      <div className="slicerWholeModelProgress" role="status">
        <span>{wholeModel.complete
          ? "Full-detail geometry · "+layers.length.toLocaleString()+" layers"
          : wholeModel.loading
          ? "Loading complete extrusion geometry · "+wholeModel.loadedLayers.toLocaleString()+" / "+layers.length.toLocaleString()+" layers"
          : "Incomplete full-detail preview · "+wholeModel.loadedLayers.toLocaleString()+" / "+layers.length.toLocaleString()+" layers"}
        </span>
        {wholeModel.loading && <progress value={wholeModel.loadedLayers} max={layers.length} />}
        {(wholeModel.limited || wholeModel.message) && <small>
          {wholeModel.message || "The preview reached its resource budget; no missing paths have been fabricated. Select a layer for original G-code inspection."}
        </small>}
      </div>
      {wholeModel.complete && <small className="slicerPreviewAccuracyNote">
        Full-detail preview preserves walls, skins, supports and prime tower; only collinear extrusion moves are merged. Select a layer to inspect the original movements.
      </small>}
      {showLayerInsert && canEdit && fileId && file && <GcodeLayerInsert
        key={String(currentLayer) + ":" + String(fileId)}
        file={file} selectedZ={z} nextZ={layers[currentLayer + 1]}
        onSaved={onSaved} onCancel={() => setShowLayerInsert(false)} />}
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
