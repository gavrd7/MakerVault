import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/**
 * Three-dimensional, read-only visualisation of the worker's bounded
 * extrusion sample. Coordinates are millimetres; printer Z maps to Three Y.
 * Never imply a complete print simulation when sampled paths are missing.
 */
export default function SlicerToolpath3D({
  segments = [], layers = [], activeLayer, activeStep, visible = {},
  colourMode = "feature", colours = {}, showToolhead = true, bedSize = null,
  renderMode = "solid", nozzleDiameter = 0.4,
}) {
  const mount = useRef(null);
  const sceneRef = useRef(null);
  const [unavailable, setUnavailable] = useState(false);
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
    const distance = nativeBed
      ? Math.max(80, Math.hypot(width, depth) * 1.5)
      : Math.max(60, size.length() * 1.8);
    const target = nativeBed ? bedCentre : centre;
    controls.target.copy(target);
    camera.position.copy(target).add(new THREE.Vector3(distance * 0.7, distance * 0.9, distance));
    camera.lookAt(target);
    controls.update();
    sceneRef.current = { scene, paths, marker, camera, controls, renderer };
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
      marker.geometry.dispose();
      marker.material.dispose();
      sceneRef.current = null;
      renderer.dispose();
      renderer.domElement.remove();
    };
  // Mount once per preview; geometry is replaced independently below.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bedSize?.[0], bedSize?.[1]]);

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
    const chosenLayer = Math.max(0, activeLayer);
    for (const segment of segments) {
      if (!Array.isArray(segment) || segment.length < 6 ||
          !segment.slice(0, 5).every(Number.isFinite)) continue;
      const [x1, y1, x2, y2, z, feature] = segment;
      if (z > selectedZ + 0.0005) continue;
      const isCurrent = Math.abs(z - selectedZ) <= 0.0005;
      if (isCurrent) {
        currentCount += 1;
        if (currentCount > maxStep) continue;
        lastStep = [x2, z, y2];
      }
      if (visible[feature] === false) continue;
      const hex = colourMode === "layer"
        ? new THREE.Color().setHSL(0.56 - 0.44 * (layers.length > 1
          ? Math.max(0, layers.findIndex(height => Math.abs(height - z) < 0.0005)) / (layers.length - 1) : 0), 0.85, 0.64)
        : new THREE.Color(colours[feature] || "#b8d4e5");
      // Dim completed layers while keeping current-layer paths vivid.
      if (!isCurrent) hex.multiplyScalar(0.35);
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
      const layerIndex = layers.findIndex(height => Math.abs(height - z) < 0.0005);
      const priorHeight = layerIndex > 0 ? layers[layerIndex - 1] : 0;
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
        paths.add(new THREE.Mesh(geometry,
          new THREE.MeshBasicMaterial({
            vertexColors: true, side: THREE.DoubleSide, transparent: false,
          })));
      }
    }
    marker.visible = Boolean(showToolhead && lastStep);
    if (lastStep) marker.position.set(...lastStep);
  }, [segments, layers, activeLayer, activeStep, visible, colourMode, colours, showToolhead, renderMode, nozzleDiameter]);

  return <div className="slicerToolpath3D">
    {unavailable ? <div role="status" className="projectUploadHint">
      3D preview requires WebGL. The generated G-code is still available for text inspection.
    </div> : <div className="slicerToolpath3DCanvas" ref={mount} role="img"
      aria-label="3D G-code toolpath preview. Drag to orbit, scroll to zoom and right-drag to pan." />}
    <small>Drag to orbit · Scroll to zoom · Right-drag to pan · Z is vertical ·
      {bedSize && Number(bedSize[0]) > 0 && Number(bedSize[1]) > 0
        ? " Bed is shown at its printer-coordinate origin (0, 0)."
        : " Bed is an approximate reference grid, not verified printer dimensions."}
    </small>
  </div>;
}
