import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { apiFetch } from "../api";
import { plateExtentWarning } from "./slicerPlateGeometry";

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
  canEdit = false, onFilesUploaded,
}) {
  const hostRef = useRef(null);
  const sceneRef = useRef(null);
  const latestObjectsRef = useRef(objects);
  const latestOnChangeRef = useRef(onChange);
  latestObjectsRef.current = objects;
  latestOnChangeRef.current = onChange;
  const [selected, setSelected] = useState("");
  const [assetChoice, setAssetChoice] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [error, setError] = useState("");
  const [dimensions, setDimensions] = useState({});
  const sourceFiles = useMemo(() => files.filter(file =>
    file.category === "mesh" && /\.stl$/i.test(file.filename || file.name || "") && file.url
  ), [files]);
  const bedX = plate?.size_mm?.[0] > 0 ? Number(plate.size_mm[0]) : 220;
  const bedY = plate?.size_mm?.[1] > 0 ? Number(plate.size_mm[1]) : 220;
  const chosen = objects.find(item => item.instance_id === selected) || objects[0] || null;
  const objectKey = objects.map(item => item.instance_id + ":" + item.asset_id).join("|");
  const extentWarnings = objects.map((item, index) => ({
    id: item.instance_id,
    label: sourceFiles.find(file => String(file.id) === item.asset_id)?.name || "Model " + (index + 1),
    message: dimensions[item.instance_id]
      ? plateExtentWarning(item, dimensions[item.instance_id], bedX, bedY) : "",
  })).filter(row => row.message);

  function addAsset(id) {
    if (!id) return;
    if (objects.length >= MAX_OBJECTS) {
      setError("The preparation editor currently supports at most twelve STL instances.");
      return;
    }
    const next = newPlateInstance(id, objects.length);
    onChange([...objects, next]);
    if (!objects.length) onPrimaryChange?.(id);
    setSelected(next.instance_id);
    setError("");
  }

  function patch(field, value) {
    if (!chosen) return;
    onChange(objects.map(item => item.instance_id === chosen.instance_id
      ? { ...item, [field]: value }
      : item));
  }

  async function uploadFiles(event) {
    const imports = Array.from(event.target.files || []);
    event.target.value = "";
    if (!imports.length) return;
    if (!canEdit) return;
    if (imports.length + objects.length > MAX_OBJECTS) {
      setError("Too many STL models for this preparation plate.");
      return;
    }
    if (imports.some(file => !/\.stl$/i.test(file.name) || !file.size || file.size > MAX_FILE_BYTES)) {
      setError("Select nonempty STL files smaller than 32 MiB each.");
      return;
    }
    setUploadBusy(true);
    setError("");
    const imported = [];
    try {
      for (const file of imports) {
        const form = new FormData();
        form.append("file", file);
        form.append("category", "mesh");
        form.append("name", file.name);
        const result = await apiFetch("/api/files/", { method: "POST", body: form });
        if (!result?.file?.id) throw new Error("MakerVault did not return a model file ID.");
        imported.push(result.file.id);
      }
      await onFilesUploaded?.();
      const additions = imported.map((id, index) => newPlateInstance(id, objects.length + index));
      onChange([...objects, ...additions]);
      if (!objects.length) onPrimaryChange?.(imported[0]);
      setSelected(additions[0].instance_id);
    } catch (err) {
      setError((err.message || "Could not upload STL files.") +
        (imported.length ? " Successfully uploaded files remain in your MakerVault Files library." : ""));
      if (imported.length) {
        try { await onFilesUploaded?.(); } catch { /* Uploaded assets remain in Files. */ }
        const additions = imported.map((id, index) => newPlateInstance(id, objects.length + index));
        onChange([...objects, ...additions]);
        if (!objects.length) onPrimaryChange?.(imported[0]);
        setSelected(additions[0].instance_id);
      }
    } finally {
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
      const x = Math.max(-10000, Math.min(10000, Math.round(location.x + dragging.deltaX)));
      const y = Math.max(-10000, Math.min(10000, Math.round(location.y + dragging.deltaY)));
      const current = latestObjectsRef.current;
      if (!current.some(item => item.instance_id === dragging.id)) return;
      latestOnChangeRef.current(current.map(item => item.instance_id === dragging.id
        ? { ...item, x_mm: x, y_mm: y }
        : item));
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

  return <section className="panel printingSection" aria-labelledby="slicer-plate-heading">
    <h3 id="slicer-plate-heading">Visual build plate</h3>
    <p>Arrange multiple STLs, assign preview colours and adjust placement, rotation and uniform scale. This is a working visual <strong>draft editor</strong>; the current single-model worker cannot slice these arrangements yet.</p>
    <div className="formGrid">
      <label>Existing STL from Files
        <select value={assetChoice} onChange={event => setAssetChoice(event.target.value)} disabled={!canEdit || uploadBusy}>
          <option value="">Choose an STL to add</option>
          {sourceFiles.map(file => <option key={file.id} value={file.id}>{file.name || file.filename}</option>)}
        </select>
      </label>
      <div className="settingsActions">
        <button type="button" onClick={() => addAsset(assetChoice)} disabled={!canEdit || !assetChoice || uploadBusy || objects.length >= MAX_OBJECTS}>Add STL to plate</button>
      </div>
      <label className="full">Upload multiple STL files to the MakerVault library and plate
        <input type="file" accept=".stl" multiple onChange={uploadFiles} disabled={!canEdit || uploadBusy || objects.length >= MAX_OBJECTS} />
      </label>
    </div>
    {error && <p className="integrationError" role="alert">{error}</p>}
    <div ref={hostRef} aria-label="Interactive three-dimensional model plate preview" style={{
      height: 370, width: "100%", borderRadius: 12, overflow: "hidden", border: "1px solid var(--border, #435365)",
      background: "#0f1720", touchAction: "none",
    }} />
    <p>Plate extent: {pretty(bedX)} × {pretty(bedY)} mm. Drag a model to move it on the bed (1 mm steps), tap to select, or orbit the view around empty space. Precise numeric transforms are available below. This does not certify fit or generate G-code.</p>
    {extentWarnings.length > 0 && <div role="status" className="integrationError">
      <strong>Preliminary plate-fit warnings</strong>
      <ul>{extentWarnings.map(warning => <li key={warning.id}>{warning.label}: {warning.message}</li>)}</ul>
      These checks use an XY rectangular envelope of the preview mesh, not the exact printable polygon,
      excluded regions, model height or toolhead clearance. They do not certify printability.
    </div>}
    {objects.length > 0 && <div className="formGrid">
      <label className="full">Model instance
        <select value={chosen?.instance_id || ""} onChange={event => setSelected(event.target.value)}>
          {objects.map((item, index) => <option key={item.instance_id} value={item.instance_id}>
            {index + 1}. {sourceFiles.find(file => String(file.id) === item.asset_id)?.name || "STL model"}
          </option>)}
        </select>
      </label>
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
          onChange={event => patch("color", event.target.value)} />
      </label>
      <div className="settingsActions">
        <button type="button" disabled={!canEdit} onClick={() => patch("rotation_deg", ((chosen.rotation_deg + 90) % 360))}>Rotate 90°</button>
        <button type="button" disabled={!canEdit || objects.length >= MAX_OBJECTS}
          onClick={() => addAsset(chosen.asset_id)}>Duplicate</button>
        <button type="button" disabled={!canEdit} onClick={() => {
          const filtered = objects.filter(item => item.instance_id !== chosen.instance_id);
          onChange(filtered);
          if (filtered.length) onPrimaryChange?.(filtered[0].asset_id);
          setSelected(filtered[0]?.instance_id || "");
        }}>Remove model</button>
      </div>
    </div>}
    {objects.length > 0 && <p role="status">{objects.length} model instance{objects.length === 1 ? "" : "s"} on the preparation plate. Saving a draft preserves this arrangement; slicing the arrangement remains disabled until verified.</p>}
  </section>;
}
