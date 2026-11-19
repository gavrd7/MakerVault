import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { featureMatchesFocus, featureFamily } from "./slicerToolpathFeatures";

// Reuse just eight unit vertices per deposited strand. Instancing sends one
// affine matrix and one colour per extrusion rather than duplicating many
// vertices and indices for each move. No original path is omitted.
function makeUnitBead() {
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute("position",new THREE.Float32BufferAttribute([
    -0.5,0.5,0.5, -0.5,0.5,-0.5, 0.5,0.5,0.5, 0.5,0.5,-0.5,
    -0.5,-0.5,0.5, -0.5,-0.5,-0.5, 0.5,-0.5,0.5, 0.5,-0.5,-0.5,
  ],3));
  geometry.setIndex([0,2,1, 1,2,3, 0,4,6, 0,6,2, 1,3,7, 1,7,5]);
  geometry.computeVertexNormals();
  return geometry;
}

/**
 * Three-dimensional, read-only visualisation of the worker's bounded
 * extrusion sample. Coordinates are millimetres; printer Z maps to Three Y.
 * Never imply a complete print simulation when sampled paths are missing.
 */
export default function SlicerToolpath3D({
  segments = [], segmentChunks = [], framingSegments = [], progressiveMode = false, layers = [], activeLayer, activeStep, visible = {},
  colourMode = "feature", colours = {}, filamentColours = {}, showToolhead = true, bedSize = null,
  renderMode = "solid", nozzleDiameter = 0.4,
  layerDisplay = "current", featureFocus = "all",
  previewSampled = false, fadePrevious = false, outerContrast = false,
  toolbarActions = null,
}) {
  const mount = useRef(null);
  const sceneRef = useRef(null);
  const framedInitialGeometry = useRef(false);
  const [unavailable, setUnavailable] = useState(false);
  const [showBedGrid, setShowBedGrid] = useState(true);
  const [mobileViewOpen, setMobileViewOpen] = useState(false);
  const [showBedSurface, setShowBedSurface] = useState(true);
  useEffect(() => {
    const mountPoint = mount.current;
    if (!mountPoint) return undefined;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setUnavailable(true);
      return undefined;
    }
    // On high-density/mobile displays avoid multiplying a large preview's
    // fragment workload by four. This does not reduce toolpath accuracy.
    const mobilePreview = window.matchMedia?.("(max-width: 700px)")?.matches;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, mobilePreview ? 1.25 : 1.5));
    renderer.localClippingEnabled = true;
    renderer.setClearColor(0x111b27);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute("aria-label", "Rotatable sampled 3D extrusion paths");
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";
    mountPoint.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111b27);
    // Ambient-only lighting flattens the small ridges and support contacts.
    // Balanced directional and hemispheric light makes individual beads legible
    // without changing native G-code geometry or its feature colours.
    scene.add(new THREE.AmbientLight(0xffffff, 0.72));
    scene.add(new THREE.HemisphereLight(0xddefff, 0x2b3240, 0.54));
    const directional = new THREE.DirectionalLight(0xffffff, 1.38);
    directional.position.set(120, 250, 140);
    scene.add(directional);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    controls.minDistance = 3;
    controls.maxDistance = 3000;
    const paths = new THREE.Group();
    scene.add(paths);
    // One shared clipping plane hides all geometry above the slider height.
    // Changing this plane never reallocates or rebuilds GPU extrusion buffers.
    const layerClipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 2000);
    const bedWidth = Number(bedSize?.[0]);
    const bedDepth = Number(bedSize?.[1]);
    const nativeBed = Number.isFinite(bedWidth) && Number.isFinite(bedDepth) &&
      bedWidth >= 50 && bedWidth <= 1000 && bedDepth >= 50 && bedDepth <= 1000;
    const width = nativeBed ? bedWidth : 220;
    const depth = nativeBed ? bedDepth : 220;
    const grid = new THREE.GridHelper(Math.max(width, depth), Math.max(5, Math.round(Math.max(width, depth) / 10)), 0x5c728b, 0x304154);
    grid.position.y = -0.2;
    scene.add(grid);
    const bed = new THREE.Mesh(
      new THREE.PlaneGeometry(width, depth),
      new THREE.MeshBasicMaterial({ color: 0x202d3c, side: THREE.DoubleSide, transparent: true, opacity: 0.52 })
    );
    bed.rotation.x = -Math.PI / 2;
    bed.position.y = -0.3;
    scene.add(bed);
    const plateBoundary = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, -0.12, 0),
        new THREE.Vector3(width, -0.12, 0),
        new THREE.Vector3(width, -0.12, depth),
        new THREE.Vector3(0, -0.12, depth),
      ]),
      new THREE.LineBasicMaterial({ color: 0x8092a9 })
    );
    plateBoundary.visible = nativeBed;
    scene.add(plateBoundary);
    // Native printer XY axes: red X points right and blue Y points into bed.
    // Never translate axes along with the sampled model's bounding box.
    const axes = new THREE.Group();
    for (const [end, colour] of [
      [new THREE.Vector3(Math.min(40, width / 4), -0.08, 0), 0xe36a74],
      [new THREE.Vector3(0, -0.08, Math.min(40, depth / 4)), 0x6ca9e8],
    ]) {
      axes.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, -0.08, 0), end]),
        new THREE.LineBasicMaterial({ color: colour })
      ));
    }
    axes.visible = nativeBed;
    scene.add(axes);
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(1.6, 12, 8),
      new THREE.MeshBasicMaterial({ color: 0xff922b, depthTest: false })
    );
    marker.renderOrder = 10;
    scene.add(marker);
    // Use the small, bounded summary only to frame the camera. Never draw it
    // as completed extrusion geometry; progressive exact layers render below.
    const cameraSource = framingSegments.length ? framingSegments : segments;
    const bounds = new THREE.Box3();
    let valid = 0;
    for (const segment of cameraSource) {
      if (!Array.isArray(segment) || segment.length < 5 ||
          !segment.slice(0, 5).every(Number.isFinite)) continue;
      bounds.expandByPoint(new THREE.Vector3(segment[0], segment[4], segment[1]));
      bounds.expandByPoint(new THREE.Vector3(segment[2], segment[4], segment[3]));
      valid += 1;
    }
    // Purge lines and skirt moves can span the bed and make the printed part
    // tiny. For camera framing only, use the densest XY footprint rather than
    // letting sparse outliers dictate the focal distance. Never alter toolpaths.
    const xs = [], ys = [];
    for (let i = 0; i < cameraSource.length; i += Math.max(1, Math.floor(cameraSource.length / 4000))) {
      const line = cameraSource[i];
      if (Array.isArray(line) && line.length >= 5 && line.slice(0, 5).every(Number.isFinite)) {
        xs.push(line[0], line[2]);
        ys.push(line[1], line[3]);
      }
    }
    const middleBounds = (values) => {
      if (!values.length) return null;
      values.sort((a,b) => a-b);
      const low = values[Math.floor(values.length * 0.03)];
      const high = values[Math.floor(values.length * 0.97)];
      return [low, high];
    };
    const bx = middleBounds(xs), by = middleBounds(ys);
    const rawCentre = valid ? bounds.getCenter(new THREE.Vector3()) : new THREE.Vector3(110, 0, 110);
    const rawSize = valid ? bounds.getSize(new THREE.Vector3()) : new THREE.Vector3(120, 40, 120);
    const centre = bx && by
      ? new THREE.Vector3((bx[0] + bx[1]) / 2, rawCentre.y, (by[0] + by[1]) / 2)
      : rawCentre;
    const size = bx && by
      ? new THREE.Vector3(Math.max(1, bx[1]-bx[0]), rawSize.y, Math.max(1, by[1]-by[0]))
      : rawSize;
    framedInitialGeometry.current = valid > 0;
    // With known machine dimensions, preserve the printer's actual XY origin
    // at (0, 0). The sample may contain outlying purge/skirt moves and must
    // not change the relative position of the bed and model.
    const bedCentre = nativeBed
      ? new THREE.Vector3(width / 2, 0, depth / 2)
      : centre;
    grid.position.x = bedCentre.x;
    grid.position.z = bedCentre.z;
    grid.scale.set(width / Math.max(width, depth), 1, depth / Math.max(width, depth));
    bed.position.x = bedCentre.x;
    bed.position.z = bedCentre.z;
    // Frame the printed part rather than the full printer bed initially.
    // An overview is still available from the Isometric camera control.
    const distance = Math.max(38, size.length() * 1.25);
    const target = valid ? centre : bedCentre;
    controls.target.copy(target);
    // G-code XY maps to Three X/Z. Printer front is negative native Y,
    // therefore negative Three Z. Match the interactive plate camera.
    // Viewing from positive Z showed the *rear* of the print and made
    // asymmetric lettering and prime tower placement appear mirrored.
    camera.position.copy(target).add(new THREE.Vector3(distance * 0.7, distance * 0.9, -distance));
    camera.lookAt(target);
    controls.update();
    sceneRef.current = { scene, paths, marker, camera, controls, renderer,
      grid, bed, plateBoundary, axes, bedCentre, modelCentre: centre, modelSize: size,
      bedWidth: width, bedDepth: depth, nativeBed, layerClipPlane };
    const resize = () => {
      const width = Math.max(mountPoint.clientWidth, 1);
      const height = Math.max(mountPoint.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
    observer?.observe(mountPoint);
    resize();
    let frame;
    let running = true;
    const renderFrame = () => {
      if (!running) return;
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(renderFrame);
    };
    renderFrame();
    return () => {
      running = false;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      controls.dispose();
      paths.traverse(object => {
        if (object.isLineSegments || object.isMesh) {
          object.geometry.dispose();
          object.material.dispose();
        }
      });
      grid.geometry.dispose();
      grid.material.dispose();
      bed.geometry.dispose();
      bed.material.dispose();
      plateBoundary.geometry.dispose();
      plateBoundary.material.dispose();
      axes.children.forEach(axis => { axis.geometry.dispose(); axis.material.dispose(); });
      marker.geometry.dispose();
      marker.material.dispose();
      sceneRef.current = null;
      renderer.dispose();
      renderer.domElement.remove();
    };
  // Framing sample is file-specific, but geometry updates independently.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bedSize?.[0], bedSize?.[1], framingSegments]);

  const setCameraView = (viewName) => {
    const view = sceneRef.current;
    if (!view) return;
    const { camera, controls, bedCentre, modelCentre, modelSize,
      bedWidth, bedDepth } = view;
    const focusModel = viewName === "model";
    const target = focusModel ? modelCentre : bedCentre;
    const span = focusModel
      ? Math.max(30, modelSize.length() * 1.8)
      : Math.max(80, Math.hypot(bedWidth, bedDepth) * 1.45);
    controls.target.copy(target);
    camera.up.set(0, 1, 0);
    if (viewName === "top") {
      camera.position.copy(target).add(new THREE.Vector3(0, span, 0.0001));
    } else if (viewName === "front") {
      camera.position.copy(target).add(new THREE.Vector3(0, span * 0.25, -span));
    } else {
      camera.position.copy(target).add(new THREE.Vector3(span * 0.7, span * 0.85, -span));
    }
    camera.lookAt(target);
    controls.update();
  };

  useEffect(() => {
    const view = sceneRef.current;
    if (view) {
      view.grid.visible = showBedGrid;
      view.plateBoundary.visible = showBedSurface && view.nativeBed;
      view.axes.visible = showBedGrid && view.nativeBed;
      view.bed.visible = showBedSurface;
    }
  }, [showBedGrid, showBedSurface]);

  // In the whole-print mode the native layer slider changes only this
  // clipping plane, not the extrusion geometry or its React dependencies.
  useEffect(() => {
    const view=sceneRef.current;
    if (!view) return;
    view.layerClipPlane.constant = Number.isFinite(layers[activeLayer])
      ? layers[activeLayer] + 0.0005 : 2000;
  }, [activeLayer, layers]);

  const geometryLayer = progressiveMode ? layers.length-1 : activeLayer;
  const geometryStep = progressiveMode ? -1 : activeStep;

  useEffect(() => {
    const view = sceneRef.current;
    if (!view) return;
    const { paths, marker } = view;
    // In whole-print mode, never re-tessellate hundreds of thousands of
    // extrusion moves every time another batch finishes loading.
    const styleKey = JSON.stringify([colourMode,colours,filamentColours,renderMode,
      nozzleDiameter,visible,featureFocus,layerDisplay,previewSampled,
      fadePrevious,outerContrast]);
    const previous=view.geometryCache;
    const canAppend=progressiveMode && previous?.styleKey===styleKey &&
      segmentChunks.length>=previous.chunkCount &&
      (previous.chunkCount===0 ||
       segmentChunks[previous.chunkCount-1]===previous.lastChunk);
    const startChunk=canAppend ? previous.chunkCount : 0;
    if(!canAppend){
      while(paths.children.length){
        const old=paths.children[0];
        paths.remove(old);
        old.geometry.dispose();
        old.material.dispose();
      }
    }
    const batches=progressiveMode ? segmentChunks.slice(startChunk) : [segments];
    const activeZ = progressiveMode ? Infinity : layers[geometryLayer];
    const featureShadeCache=new Map();
    const beadMatrix=new THREE.Matrix4();
    let lastStep=null;
    const selectedZ = Number.isFinite(activeZ) ? activeZ : Infinity;
    const maxStep = Math.max(0, Number(geometryStep) || 0);
    const layerIndexByHeight = new Map(layers.map((height, index) => [Number(height).toFixed(3), index]));
    const activeIndex = Math.max(0, Number(geometryLayer) || 0);
    const minVisibleIndex = layerDisplay === "current" ? activeIndex
      : layerDisplay === "context" ? Math.max(0, activeIndex - 8) : 0;
    for (const batch of batches) {
      const positions=[];
      const coloursArray=[];
      let currentCount=0;
      let beadCount=0;
      const beadMesh=renderMode==="lines" ? null : new THREE.InstancedMesh(
        makeUnitBead(),
        new THREE.MeshLambertMaterial({
          vertexColors:false,side:THREE.DoubleSide,
          clippingPlanes:[view.layerClipPlane],
        }),
        Math.max(1,batch.length),
      );
    for (const segment of batch) {
      if (!Array.isArray(segment) || segment.length < 6 ||
          !Number.isFinite(segment[0]) || !Number.isFinite(segment[1]) ||
          !Number.isFinite(segment[2]) || !Number.isFinite(segment[3]) ||
          !Number.isFinite(segment[4])) continue;
      const [x1, y1, x2, y2, z, feature] = segment;
      if (z > selectedZ + 0.0005) continue;
      const segmentLayerIndex = layerIndexByHeight.get(Number(z).toFixed(3));
      if (segmentLayerIndex == null || segmentLayerIndex < minVisibleIndex) continue;
      const isCurrent = segmentLayerIndex === activeIndex;
      if (isCurrent) {
        currentCount += 1;
        if (!progressiveMode && currentCount > maxStep) continue;
        lastStep = [x2, z, y2];
      }
      if (visible[feature] === false || !featureMatchesFocus(feature, featureFocus)) continue;
      // Inspection means *isolation*, not amber paint over dimmed green paths.
      // Skip internal segments entirely when comparing outer perimeters.
      if (outerContrast && featureFamily(feature) !== "outer") continue;
      const logicalTool = segment[7];
      const shadeKey = colourMode + "|" + feature + "|" + String(logicalTool??-1) +
        "|" + (colourMode==="layer"?segmentLayerIndex:0) + "|" + (isCurrent?1:0);
      let hex=featureShadeCache.get(shadeKey);
      if(!hex) {
        const declaredColour=Number.isInteger(logicalTool) ? filamentColours[logicalTool] : null;
        const hasDeclaredColour=typeof declaredColour==="string" && /^#[0-9a-f]{6}$/i.test(declaredColour);
        hex = colourMode === "filament"
        ? (hasDeclaredColour ? new THREE.Color(declaredColour)
          : Number.isInteger(logicalTool) && logicalTool >= 0 && logicalTool < 16
          ? new THREE.Color().setHSL((0.06 + logicalTool * 0.618034) % 1, 0.76, 0.61)
          : new THREE.Color("#718096"))
        : colourMode === "layer"
        ? new THREE.Color().setHSL(0.56 - 0.44 * (layers.length > 1
          ? Math.max(0, (layerIndexByHeight.get(z.toFixed(3)) ?? -1)) / (layers.length - 1) : 0), 0.85, 0.64)
        : new THREE.Color(colourMode === "solid" ? "#f09a4b" : (colours[feature] || "#b8d4e5"));
      // Inspection contrast is a display-only change. Don't alter or classify
      // native toolpaths as fuzzy; highlight outer-wall geometry while dimming
      // neighbouring deposited features for easier side-by-side comparison.
      if (outerContrast) {
        if (featureFamily(feature) === "outer") hex.set("#ffd166");
        else hex.multiplyScalar(0.20);
      }
      // A full indexed model is *not* a ghost backdrop: darkening every
      // earlier layer made thin walls and painted-support contacts appear
      // absent. Only intentionally fade them, or show a weaker context when
      // the overview is genuinely sampled/incomplete.
      if (!isCurrent) {
        const factor = layerDisplay === "context" ? 0.32
          : fadePrevious ? 0.38
          : previewSampled ? 0.82 : 1;
        hex.multiplyScalar(factor);
      }
        featureShadeCache.set(shadeKey,hex);
      }
      if (renderMode === "lines") {
        positions.push(x1, z, y1, x2, z, y2);
        for (let index = 0; index < 2; index++) coloursArray.push(hex.r, hex.g, hex.b);
        continue;
      }
      // Each G-code extrusion move represents a deposited strand with width
      // and layer height, not a zero-width wire. Draw a rectangular bead's
      // top and two visible walls; the visual volume is advisory and cannot
      // account for actual flow, squish or overlapping adjacent extrusions.
      const suppliedWidth = Number(segment[6]);
      const width = Number.isFinite(suppliedWidth) && suppliedWidth >= 0.05 && suppliedWidth <= 3
        ? suppliedWidth : Math.max(0.1, Math.min(2.4, Number(nozzleDiameter) * 1.05 || 0.42));
      const length = Math.hypot(x2 - x1, y2 - y1);
      if (length < 0.0001) continue;
      const dx=x2-x1, dy=y2-y1;
      const priorHeight=segmentLayerIndex>0 ? layers[segmentLayerIndex-1] : 0;
      const beadHeight=Math.max(0.07,Math.min(0.45,z-priorHeight||0.2));
      // In a unit bead, local X follows the extrusion centreline, Y is
      // layer height and Z is the lateral width. Each matrix is kept on GPU.
      beadMatrix.set(
        dx,0,-dy/length*width,(x1+x2)/2,
        0,beadHeight,0,z-beadHeight/2,
        dy,0,dx/length*width,(y1+y2)/2,
        0,0,0,1
      );
      beadMesh.setMatrixAt(beadCount,beadMatrix);
      beadMesh.setColorAt(beadCount,hex);
      beadCount++;
    }
    // On iOS the WebGL surface may mount before the async indexed layer is
    // populated. The initial camera would then target fallback dimensions,
    // leaving a tiny print until opening another modal caused a reflow.
    // Reframe once when first real extrusion geometry arrives, never on every
    // layer or during the user's manual camera interactions.
    if (!framedInitialGeometry.current && (positions.length || beadCount) && batch.length) {
      const bounds = new THREE.Box3();
      for (const row of batch) {
        if (!Array.isArray(row) || row.length < 5 ||
            !row.slice(0, 5).every(Number.isFinite)) continue;
        bounds.expandByPoint(new THREE.Vector3(row[0], row[4], row[1]));
        bounds.expandByPoint(new THREE.Vector3(row[2], row[4], row[3]));
      }
      if (!bounds.isEmpty()) {
        const modelCentre = bounds.getCenter(new THREE.Vector3());
        const modelSize = bounds.getSize(new THREE.Vector3());
        view.modelCentre.copy(modelCentre);
        view.modelSize.copy(modelSize);
        const distance = Math.max(38, modelSize.length() * 1.25);
        view.controls.target.copy(modelCentre);
        view.camera.position.copy(modelCentre).add(
          new THREE.Vector3(distance * .7, distance * .9, -distance)
        );
        view.camera.lookAt(modelCentre);
        view.controls.update();
        framedInitialGeometry.current = true;
      }
    }
    if (renderMode === "lines" && positions.length) {
      const geometry=new THREE.BufferGeometry();
      geometry.setAttribute("position",new THREE.Float32BufferAttribute(positions,3));
      geometry.setAttribute("color",new THREE.Float32BufferAttribute(coloursArray,3));
      paths.add(new THREE.LineSegments(geometry,
        new THREE.LineBasicMaterial({vertexColors:true,transparent:true,
          opacity:0.98,clippingPlanes:[view.layerClipPlane]})));
    }
    if (beadMesh) {
      if (beadCount) {
        beadMesh.count=beadCount;
        beadMesh.instanceMatrix.needsUpdate=true;
        if (beadMesh.instanceColor) beadMesh.instanceColor.needsUpdate=true;
        beadMesh.frustumCulled=false;
        paths.add(beadMesh);
      } else {
        beadMesh.geometry.dispose();
        beadMesh.material.dispose();
      }
    }
    } // Each completed response is a self-contained GPU mesh.
    view.geometryCache = progressiveMode ? {
      chunkCount:segmentChunks.length,styleKey,
      lastChunk:segmentChunks[segmentChunks.length-1],
    } : null;
    marker.visible = Boolean(showToolhead && lastStep);
    if (lastStep) marker.position.set(...lastStep);
  }, [segments, segmentChunks, layers, geometryLayer, geometryStep, visible, colourMode, colours, showToolhead,
    renderMode, nozzleDiameter, filamentColours, layerDisplay, featureFocus, previewSampled,
    fadePrevious, outerContrast, progressiveMode, bedSize?.[0], bedSize?.[1]]);

  return <div className="slicerToolpath3D">
    {unavailable ? <div role="status" className="projectUploadHint">
      3D preview requires WebGL. The generated G-code is still available for text inspection.
    </div> : <div className="slicerToolpath3DCanvas" ref={mount} role="img"
      aria-label="3D G-code toolpath preview. Drag to orbit, scroll to zoom and right-drag to pan." />}
    <div className="slicerToolpathViewBar" role="toolbar" aria-label="G-code preview camera and bed">
      <div className="slicerUnifiedViewActions">
        <button type="button" className="slicerMobileViewToggle" aria-expanded={mobileViewOpen}
          onClick={() => setMobileViewOpen(value => !value)}>View options</button>
        {toolbarActions}
      </div>
      <div className={"slicerToolpathViewOptions" + (mobileViewOpen ? " mobileOpen" : "")}>
      <button type="button" onClick={() => setCameraView("iso")} title="Reset to isometric bed view">Isometric</button>
      <button type="button" onClick={() => setCameraView("top")} title="View build plate from above">Top</button>
      <button type="button" onClick={() => setCameraView("front")} title="View build plate from front">Front</button>
      <button type="button" onClick={() => setCameraView("model")} title="Zoom and centre on printed model">Fit model</button>
      <label><input type="checkbox" checked={showBedGrid}
        onChange={event => setShowBedGrid(event.target.checked)} /> Grid</label>
      <label><input type="checkbox" checked={showBedSurface}
        onChange={event => setShowBedSurface(event.target.checked)} /> Bed</label>
      </div>
    </div>

  </div>;
}
