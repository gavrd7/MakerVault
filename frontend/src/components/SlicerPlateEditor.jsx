import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { apiFetch } from "../api";
import { plateExtentWarning, plateFootprintsOverlap, autoArrangePlate } from "./slicerPlateGeometry";

const PALETTE = ["#58b5e4", "#f59e0b", "#a78bfa", "#10b981", "#ef4444", "#f472b6"];
const MAX_OBJECTS = 12;
const MAX_FILE_BYTES = 32 * 1024 * 1024;

function plateUuid() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // crypto.getRandomValues is available in ordinary LAN HTTP contexts where
  // crypto.randomUUID (secure contexts only) is not exposed.
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

export function newPlateInstance(assetId, index = 0) {
  return {
    instance_id: plateUuid(), asset_id: String(assetId),
    x_mm: (index % 4) * 25, y_mm: Math.floor(index / 4) * 25,
    rotation_deg: 0, scale_percent: 100, color: PALETTE[index % PALETTE.length],
  };
}

function pretty(value) {
  return Math.round(Number(value) * 100) / 100;
}

export default function SlicerPlateEditor({
  files = [], objects = [], onChange, onPrimaryChange, plate = null,
  canEdit = false, onFilesUploaded, defaultColor = null, onManualColorChange,
}) {
  const hostRef = useRef(null);
  const sceneRef = useRef(null);
  const latestObjectsRef = useRef(objects);
  const latestOnChangeRef = useRef(onChange);
  const dimensionsRef = useRef({});
  const pendingArrangeRef = useRef(false);
  const pendingAddIdsRef = useRef(new Set());
  latestObjectsRef.current = objects;
  latestOnChangeRef.current = onChange;
  const [selected, setSelected] = useState("");
  const [assetChoice, setAssetChoice] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [saveImports, setSaveImports] = useState(false);
  const [localAssets, setLocalAssets] = useState([]);
  const localAssetsRef = useRef([]);
  localAssetsRef.current = localAssets;
  useEffect(() => () => { localAssetsRef.current.forEach(asset => URL.revokeObjectURL(asset.url)); }, []);
  const [error, setError] = useState("");
  const [dimensions, setDimensions] = useState({});
  dimensionsRef.current = dimensions;
  const sourceFiles = useMemo(() => [
    ...localAssets,
    ...files.filter(file =>
      file.category === "mesh" && /\.stl$/i.test(file.filename || file.name || "") &&
      file.url && !localAssets.some(local => local.id === String(file.id))
    ),
  ], [files, localAssets]);
  const bedX = Number(plate?.size_mm?.[0]) >= 1 && Number(plate?.size_mm?.[0]) <= 1000 ? Number(plate.size_mm[0]) : 220;
  const bedY = Number(plate?.size_mm?.[1]) >= 1 && Number(plate?.size_mm?.[1]) <= 1000 ? Number(plate.size_mm[1]) : 220;
  const chosen = objects.find(item => item.instance_id === selected) || objects[0] || null;
  const objectKey = objects.map(item => item.instance_id + ":" + item.asset_id).join("|");
  const extentWarnings = objects.map((item, index) => ({
    id: item.instance_id,
    label: sourceFiles.find(file => String(file.id) === item.asset_id)?.name || "Model " + (index + 1),
    message: dimensions[item.instance_id]
      ? plateExtentWarning(item, dimensions[item.instance_id], bedX, bedY) : "",
  })).filter(row => row.message);
  const overlapWarnings = objects.flatMap((item, index) => objects.slice(index + 1)
    .filter(other => plateFootprintsOverlap(item, dimensions[item.instance_id],
      other, dimensions[other.instance_id], 2) === true)
    .map(other => ({
      id: item.instance_id + ":" + other.instance_id,
      message: (sourceFiles.find(file => String(file.id) === item.asset_id)?.name || "Model " + (index + 1)) +
        " overlaps " + (sourceFiles.find(file => String(file.id) === other.asset_id)?.name || "another model"),
    })));

  function arrangeModels(items = objects, announce = true) {
    const result = autoArrangePlate(items, dimensionsRef.current, bedX, bedY, 5);
    if (result.error) {
      if (announce) setError(result.error);
      return false;
    }
    onChange(result.objects);
    if (announce) setError("");
    return true;
  }

  function validPlacement(candidate, items) {
    const own = dimensionsRef.current[candidate.instance_id];
    if (!own) return false;
    if (plateExtentWarning(candidate, own, bedX, bedY)) return false;
    return !items.some(other => other.instance_id !== candidate.instance_id &&
      plateFootprintsOverlap(candidate, own, other,
        dimensionsRef.current[other.instance_id], 2) !== false);
  }

  // Newly imported STLs are measured asynchronously. Arrange them as soon as
  // ALL footprints are known; do not guess a size or stack at fixed 25mm steps.
  useEffect(() => {
    if (!pendingArrangeRef.current || !objects.length) return;
    if (objects.some(item => !dimensions[item.instance_id])) return;
    pendingArrangeRef.current = false;
    const result = autoArrangePlate(objects, dimensions, bedX, bedY, 5);
    if (result.objects) {
      pendingAddIdsRef.current.clear();
      onChange(result.objects);
      setError("");
    } else {
      const previous = objects.filter(item => !pendingAddIdsRef.current.has(item.instance_id));
      pendingAddIdsRef.current.clear();
      onChange(previous);
      if (!previous.length) onPrimaryChange?.("");
      setSelected(previous[0]?.instance_id || "");
      setError(result.error + " The newly added models were not placed; adjust the plate or try fewer models.");
    }
  }, [objectKey, dimensions, bedX, bedY]);

  function addAsset(id) {
    if (!id) return;
    if (objects.length >= MAX_OBJECTS) {
      setError("The preparation editor currently supports at most twelve STL instances.");
      return;
    }
    const next = newPlateInstance(id, objects.length);
    if (defaultColor) next.color = defaultColor;
    pendingArrangeRef.current = true;
    pendingAddIdsRef.current.add(next.instance_id);
    onChange([...objects, next]);
    if (!objects.length && !String(id).startsWith("local:")) onPrimaryChange?.(id);
    setSelected(next.instance_id);
    setError("");
  }

  function removeSelected() {
    if (!chosen) return;
    const remaining = objects.filter(item => item.instance_id !== chosen.instance_id);
    onChange(remaining);
    onPrimaryChange?.(remaining.find(item => !String(item.asset_id).startsWith("local:"))?.asset_id || "");
    setSelected(remaining[0]?.instance_id || "");
  }

  function patch(field, value) {
    if (!chosen) return;
    const candidate = { ...chosen, [field]: value };
    if (["x_mm", "y_mm", "rotation_deg", "scale_percent"].includes(field) &&
        !validPlacement(candidate, objects)) {
      setError("This position or transform overlaps another model, exceeds the build plate, or has dimensions still loading. Try Auto-arrange.");
      return;
    }
    setError("");
    onChange(objects.map(item => item.instance_id === chosen.instance_id ? candidate : item));
  }

  async function uploadFiles(event) {
    const imports = Array.from(event.target.files || []);
    event.target.value = "";
    if (!imports.length || !canEdit) return;
    if (imports.length + objects.length > MAX_OBJECTS) {
      setError("Maximum twelve models per build plate.");
      return;
    }
    if (imports.some(file => !/\.stl$/i.test(file.name) || !file.size || file.size > MAX_FILE_BYTES)) {
      setError("Choose nonempty STL files below 32 MiB each.");
      return;
    }
    setUploadBusy(true);
    setError("");
    const additions = [];
    const previews = [];
    try {
      for (const file of imports) {
        let id = "local:" + plateUuid();
        if (saveImports) {
          const form = new FormData();
          form.append("file", file);
          form.append("category", "mesh");
          form.append("name", file.name);
          const result = await apiFetch("/api/files/", { method: "POST", body: form });
          if (!result?.file?.id) throw new Error("MakerVault did not return a model file ID.");
          id = String(result.file.id);
        }
        previews.push({ id, category: "mesh", name: file.name, filename: file.name,
          url: URL.createObjectURL(file), localOnly: !saveImports });
        const addition = newPlateInstance(id, objects.length + additions.length);
        if (defaultColor) addition.color = defaultColor;
        additions.push(addition);
      }
    } catch (err) {
      setError((err.message || "Could not add models.") +
        (additions.length ? " Earlier models in this batch remain on the plate." : ""));
    } finally {
      if (previews.length) {
        setLocalAssets(current => [...current, ...previews]);
        pendingArrangeRef.current = true;
        additions.forEach(item => pendingAddIdsRef.current.add(item.instance_id));
        onChange([...objects, ...additions]);
        if (!objects.length && saveImports) onPrimaryChange?.(additions[0].asset_id);
        setSelected(additions[0].instance_id);
        if (saveImports) {
          try { await onFilesUploaded?.(); }
          catch { setError("Models were saved but the Files list could not refresh."); }
        }
      }
      setUploadBusy(false);
    }
  }

  useEffect(() => {
    const mount = hostRef.current;
    if (!mount) return undefined;
    let disposed = false;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setError("WebGL is unavailable on this device; object controls remain accessible.");
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.replaceChildren(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0f1720");
    scene.add(new THREE.HemisphereLight(0xffffff, 0x26384b, 2.6));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(100, -120, 260);
    scene.add(sun);

    const bed = new THREE.Mesh(
      new THREE.PlaneGeometry(bedX, bedY),
      new THREE.MeshStandardMaterial({ color: "#263342", side: THREE.DoubleSide, roughness: 0.94 }),
    );
    scene.add(bed);
    const grid = new THREE.GridHelper(Math.max(bedX, bedY), 20, 0x66839e, 0x40536b);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.25;
    scene.add(grid);
    const boundary = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-bedX / 2, -bedY / 2, 0.5),
        new THREE.Vector3(bedX / 2, -bedY / 2, 0.5),
        new THREE.Vector3(bedX / 2, bedY / 2, 0.5),
        new THREE.Vector3(-bedX / 2, bedY / 2, 0.5),
      ]),
      new THREE.LineBasicMaterial({ color: "#7dd3fc" }),
    );
    scene.add(boundary);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 20000);
    camera.up.set(0, 0, 1);
    camera.position.set(bedX * 1.0, -bedY * 1.3, Math.max(bedX, bedY) * 1.35);
    camera.lookAt(0, 0, 0);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    const meshes = new Map();
    const raycaster = new THREE.Raycaster();
    const bedPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    let dragging = null;

    function rayFromPointer(event) {
      const rect = renderer.domElement.getBoundingClientRect();
      const point = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(point, camera);
      return raycaster;
    }

    function pointerDown(event) {
      if (!canEdit || event.button > 0) return;
      rayFromPointer(event);
      const hits = raycaster.intersectObjects([...meshes.values()], false);
      if (!hits.length) return;
      const target = hits[0].object;
      const location = new THREE.Vector3();
      if (!raycaster.ray.intersectPlane(bedPlane, location)) return;
      const id = target.userData.instanceId;
      setSelected(id);
      dragging = {
        id, pointerId: event.pointerId,
        deltaX: target.position.x - location.x,
        deltaY: target.position.y - location.y,
      };
      controls.enabled = false;
      renderer.domElement.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    }

    function pointerMove(event) {
      if (!dragging || dragging.pointerId !== event.pointerId) return;
      rayFromPointer(event);
      const location = new THREE.Vector3();
      if (!raycaster.ray.intersectPlane(bedPlane, location)) return;
      const x = Math.max(-10000, Math.min(10000, Math.round((location.x + dragging.deltaX) * 2) / 2));
      const y = Math.max(-10000, Math.min(10000, Math.round((location.y + dragging.deltaY) * 2) / 2));
      const current = latestObjectsRef.current;
      if (!current.some(item => item.instance_id === dragging.id)) return;
      const target = current.find(item => item.instance_id === dragging.id);
      const candidate = { ...target, x_mm: x, y_mm: y };
      if (!validPlacement(candidate, current)) return;
      latestOnChangeRef.current(current.map(item => item.instance_id === dragging.id ? candidate : item));
    }

    function pointerUp(event) {
      if (!dragging || dragging.pointerId !== event.pointerId) return;
      dragging = null;
      controls.enabled = true;
      if (renderer.domElement.hasPointerCapture?.(event.pointerId)) {
        renderer.domElement.releasePointerCapture(event.pointerId);
      }
    }
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointermove", pointerMove);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    renderer.domElement.addEventListener("pointercancel", pointerUp);
    const resize = () => {
      if (!mount.clientWidth || !mount.clientHeight) return;
      renderer.setSize(mount.clientWidth, mount.clientHeight, false);
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();
    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });
    sceneRef.current = { scene, meshes };
    return () => {
      disposed = true;
      sceneRef.current = null;
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointermove", pointerMove);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      renderer.domElement.removeEventListener("pointercancel", pointerUp);
      renderer.setAnimationLoop(null);
      controls.dispose();
      for (const mesh of meshes.values()) {
        scene.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      bed.geometry.dispose();
      bed.material.dispose();
      grid.geometry.dispose();
      grid.material.dispose();
      boundary.geometry.dispose();
      boundary.material.dispose();
      renderer.dispose();
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
    };
  }, [bedX, bedY]);

  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return undefined;
    const controller = new AbortController();
    let live = true;
    const keep = new Set(objects.map(item => item.instance_id));
    for (const [id, mesh] of state.meshes) {
      if (keep.has(id)) continue;
      state.scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
      state.meshes.delete(id);
    }
    for (const item of objects) {
      if (state.meshes.has(item.instance_id)) continue;
      const file = sourceFiles.find(row => String(row.id) === item.asset_id);
      if (!file?.url) continue;
      fetch(file.url, { credentials: "same-origin", signal: controller.signal })
        .then(async response => {
          if (!response.ok) throw new Error("Could not load a selected STL.");
          if (Number(response.headers.get("Content-Length") || 0) > MAX_FILE_BYTES)
            throw new Error("STL exceeds the preview limit.");
          const buffer = await response.arrayBuffer();
          if (buffer.byteLength > MAX_FILE_BYTES) throw new Error("STL exceeds the preview limit.");
          return buffer;
        })
        .then(buffer => {
          if (!live || state.meshes.has(item.instance_id)) return;
          const geometry = new STLLoader().parse(buffer);
          geometry.computeVertexNormals();
          geometry.computeBoundingBox();
          const box = geometry.boundingBox;
          if (!box || box.isEmpty()) throw new Error("The STL contains no visible geometry.");
          geometry.translate(
            -(box.min.x + box.max.x) / 2,
            -(box.min.y + box.max.y) / 2,
            -box.min.z,
          );
          setDimensions(current => ({ ...current, [item.instance_id]: {
            width: box.max.x - box.min.x, depth: box.max.y - box.min.y,
          } }));
          const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
            color: item.color, roughness: 0.72, metalness: 0.04, side: THREE.DoubleSide,
          }));
          mesh.userData.instanceId = item.instance_id;
          const latest = latestObjectsRef.current.find(row => row.instance_id === item.instance_id) || item;
          mesh.position.set(latest.x_mm, latest.y_mm, 0);
          mesh.rotation.z = latest.rotation_deg * Math.PI / 180;
          mesh.scale.setScalar(latest.scale_percent / 100);
          state.meshes.set(item.instance_id, mesh);
          state.scene.add(mesh);
        })
        .catch(err => { if (live && err.name !== "AbortError") setError(err.message || "STL preview failed."); });
    }
    return () => { live = false; controller.abort(); };
  }, [objectKey, sourceFiles, bedX, bedY]);

  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    for (const item of objects) {
      const mesh = state.meshes.get(item.instance_id);
      if (!mesh) continue;
      mesh.position.set(item.x_mm, item.y_mm, 0);
      mesh.rotation.z = item.rotation_deg * Math.PI / 180;
      mesh.scale.setScalar(item.scale_percent / 100);
      mesh.material.color.set(item.color);
      mesh.material.emissive.set(item.instance_id === (chosen?.instance_id || selected) ? "#182f43" : "#000000");
    }
  }, [objects, selected]);

  return <section className="panel printingSection slicerPlatePanel" aria-labelledby="slicer-plate-heading">
    <div className="slicerPlateHeading">
      <h3 id="slicer-plate-heading">Visual build plate</h3>
      <button type="button" onClick={() => arrangeModels()} disabled={!canEdit || !objects.length || uploadBusy}>Auto-arrange models</button>
    </div>
    <p>Arrange models, change their size and position, and preview the build plate. Multi-object slicing is not yet available.</p>
    <div className="slicerPlateWorkspace">
      <div className="slicerPlateCanvasColumn">
    <div ref={hostRef} className="slicerPlateCanvas" aria-label="Interactive three-dimensional model plate preview" />

    <p className="slicerPlateHint"><strong>Build plate volume:</strong> {pretty(bedX)} × {pretty(bedY)} mm (X × Y). Drag in 0.5 mm steps or enter coordinates below.</p>
    {extentWarnings.length > 0 && <div role="status" className="integrationError">
      <strong>Preliminary plate-fit warnings</strong>
      <ul>{extentWarnings.map(warning => <li key={warning.id}>{warning.label}: {warning.message}</li>)}</ul>
      These checks use an XY rectangular envelope of the preview mesh, not the exact printable polygon,
      excluded regions, model height or toolhead clearance. They do not certify printability.
    </div>}

    {overlapWarnings.length > 0 && <div role="alert" className="integrationError">
      <strong>Models overlap on the build plate.</strong>
      <ul>{overlapWarnings.map(row => <li key={row.id}>{row.message}</li>)}</ul>
      Select Auto-arrange models or move the affected objects before saving.
    </div>}

    {objects.length > 0 && <p role="status" className="slicerPlateHint">{objects.length} model{objects.length === 1 ? "" : "s"} on the plate
      {objects.some(item => String(item.asset_id).startsWith("local:")) ? " · Temporary models will be lost on reload." : " · Plate ready to save as a draft."}</p>}

      </div>
      <aside className="slicerPlateControls" aria-label="Build plate controls">
        <div className="slicerPlateControlsGroup">
          <h4>Add models</h4>
    <div className="formGrid slicerPlateImportFields">
      <label>Existing STL from Files
        <select value={assetChoice} onChange={event => setAssetChoice(event.target.value)} disabled={!canEdit || uploadBusy}>
          <option value="">Choose an STL to add</option>
          {sourceFiles.map(file => <option key={file.id} value={file.id}>{file.name || file.filename}</option>)}
        </select>
      </label>
      <div className="settingsActions">
        <button type="button" onClick={() => addAsset(assetChoice)} disabled={!canEdit || !assetChoice || uploadBusy || objects.length >= MAX_OBJECTS}>Add STL to plate</button>
      </div>
      <label className="full">Add STL files from your device
        <input type="file" accept=".stl" multiple onChange={uploadFiles} disabled={!canEdit || uploadBusy || objects.length >= MAX_OBJECTS} />
      </label>
      <label className="full checkRow slicerPlateSaveImports"><input type="checkbox" checked={saveImports} onChange={event => setSaveImports(event.target.checked)} disabled={!canEdit || uploadBusy} />
        <span>Also save imported models to MakerVault Files</span>
      </label>
      <p className="full slicerPlateHint">Unchecked: models stay in this browser session. Saving a persistent draft requires saved source files.</p>
    </div>

        </div>
        {error && <p className="integrationError" role="alert">{error}</p>}
        <div className="slicerPlateControlsGroup">
          <h4>Selected model</h4>
    {objects.length > 0 && <div className="slicerPlateToolbar">
      <label>Selected object
        <select value={chosen?.instance_id || ""} onChange={event => setSelected(event.target.value)}>
          {objects.map((item, index) => <option key={item.instance_id} value={item.instance_id}>{index + 1}. {sourceFiles.find(file => String(file.id) === item.asset_id)?.name || "STL model"}</option>)}
        </select>
      </label>
      <button type="button" disabled={!canEdit || !chosen} onClick={removeSelected}>Remove selected model</button>
      <button type="button" disabled={!canEdit || !chosen || objects.length >= MAX_OBJECTS} onClick={() => addAsset(chosen.asset_id)}>Duplicate selected</button>
    </div>}

    {objects.length > 0 && <div className="formGrid slicerPlateTransformFields">
      <label>X position (mm)
        <input type="number" min={-10000} max={10000} step="0.5" value={chosen?.x_mm ?? 0}
          disabled={!canEdit} onChange={event => patch("x_mm", pretty(event.target.value))} />
      </label>
      <label>Y position (mm)
        <input type="number" min={-10000} max={10000} step="0.5" value={chosen?.y_mm ?? 0}
          disabled={!canEdit} onChange={event => patch("y_mm", pretty(event.target.value))} />
      </label>
      <label>Rotation around Z (degrees)
        <input type="number" min={-360} max={360} step="5" value={chosen?.rotation_deg ?? 0}
          disabled={!canEdit} onChange={event => patch("rotation_deg", pretty(event.target.value))} />
      </label>
      <label>Uniform scale (%)
        <input type="number" min={5} max={400} step="5" value={chosen?.scale_percent ?? 100}
          disabled={!canEdit} onChange={event => patch("scale_percent", pretty(event.target.value))} />
      </label>
      <label>Preview/material colour
        <input type="color" value={chosen?.color || PALETTE[0]} disabled={!canEdit}
          onChange={event => { onManualColorChange?.(chosen.instance_id); patch("color", event.target.value); }} />
      </label>
      <div className="settingsActions">
        <button type="button" disabled={!canEdit} onClick={() => patch("rotation_deg", ((chosen.rotation_deg + 90) % 360))}>Rotate 90°</button>
      </div>
    </div>}

        </div>
      </aside>
    </div>
  </section>;
}
