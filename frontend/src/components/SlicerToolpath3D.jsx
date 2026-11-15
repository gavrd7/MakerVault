import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { featureMatchesFocus } from "./slicerToolpathFeatures";

/**
 * Three-dimensional, read-only visualisation of the worker's bounded
 * extrusion sample. Coordinates are millimetres; printer Z maps to Three Y.
 * Never imply a complete print simulation when sampled paths are missing.
 */
export default function SlicerToolpath3D({
  segments = [], layers = [], activeLayer, activeStep, visible = {},
  colourMode = "feature", colours = {}, showToolhead = true, bedSize = null,
  renderMode = "solid", nozzleDiameter = 0.4,
  layerDisplay = "current", featureFocus = "all",
}) {
  const mount = useRef(null);
  const sceneRef = useRef(null);
  const [unavailable, setUnavailable] = useState(false);
  const [showBedGrid, setShowBedGrid] = useState(true);
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
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x111b27);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute("aria-label", "Rotatable sampled 3D extrusion paths");
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";
    mountPoint.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111b27);
    scene.add(new THREE.AmbientLight(0xffffff, 1.25));
    const directional = new THREE.DirectionalLight(0xffffff, 1.7);
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
    const bounds = new THREE.Box3();
    let valid = 0;
    for (const segment of segments) {
      if (!Array.isArray(segment) || segment.length < 5 ||
          !segment.slice(0, 5).every(Number.isFinite)) continue;
      bounds.expandByPoint(new THREE.Vector3(segment[0], segment[4], segment[1]));
      bounds.expandByPoint(new THREE.Vector3(segment[2], segment[4], segment[3]));
      valid += 1;
    }
    const centre = valid ? bounds.getCenter(new THREE.Vector3()) : new THREE.Vector3(110, 0, 110);
    const size = valid ? bounds.getSize(new THREE.Vector3()) : new THREE.Vector3(120, 40, 120);
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
    const distance = Math.max(45, size.length() * 1.7);
    const target = valid ? centre : bedCentre;
    controls.target.copy(target);
    camera.position.copy(target).add(new THREE.Vector3(distance * 0.7, distance * 0.9, distance));
    camera.lookAt(target);
    controls.update();
    sceneRef.current = { scene, paths, marker, camera, controls, renderer,
      grid, bed, plateBoundary, axes, bedCentre, modelCentre: centre, modelSize: size,
      bedWidth: width, bedDepth: depth, nativeBed };
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
  // Mount once per preview; geometry is replaced independently below.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bedSize?.[0], bedSize?.[1]]);

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
      camera.position.copy(target).add(new THREE.Vector3(0, span * 0.25, span));
    } else {
      camera.position.copy(target).add(new THREE.Vector3(span * 0.7, span * 0.85, span));
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

  useEffect(() => {
    const view = sceneRef.current;
    if (!view) return;
    const { paths, marker } = view;
    while (paths.children.length) {
      const old = paths.children[0];
      paths.remove(old);
      old.geometry.dispose();
      old.material.dispose();
    }
    const activeZ = layers[activeLayer];
    const positions = [];
    const coloursArray = [];
    let currentCount = 0;
    let lastStep = null;
    const selectedZ = Number.isFinite(activeZ) ? activeZ : Infinity;
    const maxStep = Math.max(0, Number(activeStep) || 0);
    const layerIndexByHeight = new Map(layers.map((height, index) => [Number(height).toFixed(3), index]));
    const activeIndex = Math.max(0, Number(activeLayer) || 0);
    const minVisibleIndex = layerDisplay === "current" ? activeIndex
      : layerDisplay === "context" ? Math.max(0, activeIndex - 8) : 0;
    for (const segment of segments) {
      if (!Array.isArray(segment) || segment.length < 6 ||
          !segment.slice(0, 5).every(Number.isFinite)) continue;
      const [x1, y1, x2, y2, z, feature] = segment;
      if (z > selectedZ + 0.0005) continue;
      const segmentLayerIndex = layerIndexByHeight.get(Number(z).toFixed(3));
      if (segmentLayerIndex == null || segmentLayerIndex < minVisibleIndex) continue;
      const isCurrent = segmentLayerIndex === activeIndex;
      if (isCurrent) {
        currentCount += 1;
        if (currentCount > maxStep) continue;
        lastStep = [x2, z, y2];
      }
      if (visible[feature] === false || !featureMatchesFocus(feature, featureFocus)) continue;
      const hex = colourMode === "layer"
        ? new THREE.Color().setHSL(0.56 - 0.44 * (layers.length > 1
          ? Math.max(0, (layerIndexByHeight.get(z.toFixed(3)) ?? -1)) / (layers.length - 1) : 0), 0.85, 0.64)
        : new THREE.Color(colourMode === "solid" ? "#f09a4b" : (colours[feature] || "#b8d4e5"));
      // Render only selected layers by default. Optional previous layers
      // provide subtle context without overwhelming fine surface detail.
      if (!isCurrent) hex.multiplyScalar(layerDisplay === "context" ? 0.24 : 0.33);
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
      const half = width / 2;
      const sideX = -(y2 - y1) / length * half;
      const sideY = (x2 - x1) / length * half;
      const priorHeight = segmentLayerIndex > 0 ? layers[segmentLayerIndex - 1] : 0;
      const beadHeight = Math.max(0.07, Math.min(0.45, z - priorHeight || 0.2));
      const top = z;
      const bottom = z - beadHeight;
      const leftA = [x1 + sideX, y1 + sideY], rightA = [x1 - sideX, y1 - sideY];
      const leftB = [x2 + sideX, y2 + sideY], rightB = [x2 - sideX, y2 - sideY];
      const pushTri = (a, b, c, topA, topB, topC) => {
        positions.push(a[0], topA, a[1], b[0], topB, b[1], c[0], topC, c[1]);
        for (let index = 0; index < 3; index++) coloursArray.push(hex.r, hex.g, hex.b);
      };
      // Top surface, outer left side and outer right side.
      pushTri(leftA, rightA, leftB, top, top, top);
      pushTri(rightA, rightB, leftB, top, top, top);
      pushTri(leftA, leftB, leftB, top, top, bottom);
      pushTri(leftA, leftB, leftA, top, bottom, bottom);
      pushTri(rightA, rightB, rightB, top, bottom, top);
      pushTri(rightA, rightB, rightA, top, bottom, bottom);
    }
    if (positions.length) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.Float32BufferAttribute(coloursArray, 3));
      if (renderMode === "lines") {
        paths.add(new THREE.LineSegments(geometry,
          new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.98 })));
      } else {
        // Orca/LibVGCode renders lit bead volume, not only flat face colours.
        // Three.js supplies normals for correctly lit top and side walls.
        geometry.computeVertexNormals();
        paths.add(new THREE.Mesh(geometry,
          new THREE.MeshLambertMaterial({
            vertexColors: true, side: THREE.DoubleSide, transparent: false,
          })));
      }
    }
    marker.visible = Boolean(showToolhead && lastStep);
    if (lastStep) marker.position.set(...lastStep);
  }, [segments, layers, activeLayer, activeStep, visible, colourMode, colours, showToolhead,
    renderMode, nozzleDiameter, layerDisplay, featureFocus, bedSize?.[0], bedSize?.[1]]);

  return <div className="slicerToolpath3D">
    {unavailable ? <div role="status" className="projectUploadHint">
      3D preview requires WebGL. The generated G-code is still available for text inspection.
    </div> : <div className="slicerToolpath3DCanvas" ref={mount} role="img"
      aria-label="3D G-code toolpath preview. Drag to orbit, scroll to zoom and right-drag to pan." />}
    <div className="slicerToolpathViewBar" role="toolbar" aria-label="G-code preview camera and bed">
      <button type="button" onClick={() => setCameraView("iso")} title="Reset to isometric bed view">Isometric</button>
      <button type="button" onClick={() => setCameraView("top")} title="View build plate from above">Top</button>
      <button type="button" onClick={() => setCameraView("front")} title="View build plate from front">Front</button>
      <button type="button" onClick={() => setCameraView("model")} title="Zoom and centre on printed model">Fit model</button>
      <label><input type="checkbox" checked={showBedGrid}
        onChange={event => setShowBedGrid(event.target.checked)} /> Grid</label>
      <label><input type="checkbox" checked={showBedSurface}
        onChange={event => setShowBedSurface(event.target.checked)} /> Bed</label>
    </div>
    <small>Drag to orbit · Scroll to zoom · Right-drag to pan · Z is vertical ·
      {bedSize && Number(bedSize[0]) > 0 && Number(bedSize[1]) > 0
        ? " Bed origin (0, 0) · red X axis · blue Y axis."
        : " Bed is an approximate reference grid, not verified printer dimensions."}
    </small>
  </div>;
}
