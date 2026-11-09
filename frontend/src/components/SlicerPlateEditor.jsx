import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { threeMfGeometryToStl, MAX_3MF_IMPORT_BYTES } from "./slicer3mfGeometry";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import { SlicerOrientationCube } from "./slicerOrientationCube";
import { apiFetch } from "../api";
import { plateExtentWarning, plateFootprintsOverlap, autoArrangePlate } from "./slicerPlateGeometry";
import { nativeBedArtwork } from "./slicerNativePlateArt";
import makerVaultLogoSvg from "../assets/slicer-bed-art/makervault-official-logo.svg?raw";

const PALETTE = ["#58b5e4", "#f59e0b", "#a78bfa", "#10b981", "#ef4444", "#f472b6"];
const MAX_OBJECTS = 12;
const MAX_FILE_BYTES = 32 * 1024 * 1024;

const PLATE_SURFACE = {
  default: { base: "#263342", speckled: false, label: "Native default" },
  cool: { base: "#37465a", speckled: false, label: "Smooth Cool Plate" },
  engineering: { base: "#303c4d", speckled: false, label: "Engineering Plate" },
  high_temp: { base: "#344451", speckled: false, label: "Smooth High Temp Plate" },
  textured_pei: { base: "#2c3338", speckled: true, label: "Textured PEI Plate" },
  textured_cool: { base: "#303f4b", speckled: true, label: "Textured Cool Plate" },
  supertack: { base: "#3b3c45", speckled: false, label: "SuperTack Plate" },
};

function makeMakerVaultPlateTexture(type, bedX, bedY) {
  // A resolution-independent, locally generated MakerVault bed surface.
  // Geometry is supplied by the printer's native polygon, and UVs span that
  // polygon's bounding rectangle: no assumptions about brand or plate size.
  const canvas = document.createElement("canvas");
  canvas.width = 2048;
  canvas.height = 2048;
  const ctx = canvas.getContext("2d");
  // Paint in logical 1024-unit coordinates onto a sharper 2048px texture.
  ctx?.scale(2, 2);
  if (!ctx) return makeRepresentativePlateTexture(type);
  const surface = PLATE_SURFACE[type] || PLATE_SURFACE.default;
  ctx.fillStyle = surface.base;
  ctx.fillRect(0, 0, 1024, 1024);
  const light = ctx.createLinearGradient(0, 0, 1024, 1024);
  light.addColorStop(0, "rgba(145,177,204,.19)");
  light.addColorStop(.4, "rgba(80,120,150,.025)");
  light.addColorStop(1, "rgba(0,0,0,.2)");
  ctx.fillStyle = light;
  ctx.fillRect(0, 0, 1024, 1024);
  if (surface.speckled) {
    for (let i = 0; i < 6500; i++) {
      ctx.fillStyle = i % 3 ? "rgba(205,218,228,.09)" : "rgba(0,0,0,.12)";
      ctx.fillRect((i * 73 + 17) % 1024, (i * 137 + 43) % 1024, 2, 2);
    }
  }
  // The edge stripe and MakerVault signature are part of the physical
  // surface, behind models and independent of the optional user labels.
  const margin = 18;
  ctx.strokeStyle = "rgba(135,173,206,.72)";
  ctx.lineWidth = 5;
  ctx.strokeRect(margin, margin, 1024 - 2 * margin, 1024 - 2 * margin);
  ctx.strokeStyle = "rgba(82,115,144,.62)";
  ctx.lineWidth = 2;
  ctx.strokeRect(margin + 11, margin + 11, 1024 - 2 * (margin + 11), 1024 - 2 * (margin + 11));
  // Brand from the official uploaded MakerVault logo rather than a drawn placeholder.
  // Image loading is asynchronous, so refresh the canvas texture when it arrives.
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  texture.generateMipmaps = true;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.userData = { makerVaultBed: true, width: bedX, depth: bedY };
  const logo = new Image();
  logo.onload = () => {
    ctx.save();
    // The provided dark-lettered logo needs a light, unobtrusive backing
    // to preserve legibility on the dark build-plate surface.
    ctx.fillStyle = "rgba(228,238,246,.9)";
    ctx.fillRect(361, 875, 302, 109);
    ctx.drawImage(logo, 371, 883, 282, 97);
    ctx.restore();
    texture.needsUpdate = true;
  };
  logo.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(makerVaultLogoSvg);
  return texture;
}

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
    rotation_deg: 0, scale_percent: 100, scale_xyz_percent: [100, 100, 100],
    color: PALETTE[index % PALETTE.length],
  };
}

function pretty(value) {
  return Math.round(Number(value) * 100) / 100;
}

export default function SlicerPlateEditor({
  files = [], objects = [], onChange, onPrimaryChange, plate = null, plateType = "default",
  plateLabel = "Plate 1", onPlateLabelChange, printerLabel = "",
  canEdit = false, onFilesUploaded, defaultColor = null, onManualColorChange, footer = null,
  selectedInstanceId = null, onSelectedInstanceChange, toolMode = "select",
  localAssets = [], onLocalAssetsChange, onExitToolMode,
}) {
  const hostRef = useRef(null);
  const sceneRef = useRef(null);
  const latestObjectsRef = useRef(objects);
  const latestOnChangeRef = useRef(onChange);
  const latestToolModeRef = useRef(toolMode);
  const exitToolModeRef = useRef(onExitToolMode);
  exitToolModeRef.current = onExitToolMode;
  const dimensionsRef = useRef({});
  const pendingArrangeRef = useRef(false);
  const pendingManualArrangeRef = useRef(false);
  const pendingAddIdsRef = useRef(new Set());
  latestObjectsRef.current = objects;
  latestOnChangeRef.current = onChange;
  latestToolModeRef.current = toolMode;
  const [localSelected, setLocalSelected] = useState("");
  const [showNativeArtwork, setShowNativeArtwork] = useState(false);
  const [nativeArtworkError, setNativeArtworkError] = useState("");
  const [showOrientationLabels, setShowOrientationLabels] = useState(false);
  const [showMachineLabel, setShowMachineLabel] = useState(false);
  const [showDimensionsLabel, setShowDimensionsLabel] = useState(false);
  const [showAxisLabels, setShowAxisLabels] = useState(false);
  const selected = selectedInstanceId === null ? localSelected : selectedInstanceId;
  const setSelected = next => {
    if (selectedInstanceId === null) setLocalSelected(next);
    else onSelectedInstanceChange?.(next);
  };
  const [assetChoice, setAssetChoice] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [saveImports, setSaveImports] = useState(false);
  // Temporary mesh previews belong to the parent workbench, not this view.
  const [error, setError] = useState("");
  const [arrangeNotice, setArrangeNotice] = useState("");
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
  // The controls show the first model by default; only an explicitly selected
  // mesh should receive a visual highlight.
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
    if (items.some(item => !dimensionsRef.current[item.instance_id])) {
      pendingArrangeRef.current = true;
      pendingManualArrangeRef.current = true;
      setArrangeNotice("Measuring models before auto-arranging…");
      setError("");
      return false;
    }
    const result = autoArrangePlate(items, dimensionsRef.current, bedX, bedY, 5);
    if (result.error) {
      if (announce) { setError(result.error); setArrangeNotice(""); }
      return false;
    }
    onChange(result.objects);
    // Arranging is a plate-wide operation; do not leave the first/last mesh highlighted.
    setSelected("");
    if (announce) {
      setError("");
      setArrangeNotice(items.length === 1
        ? "Single model centred on the build plate."
        : "Models arranged with 5 mm clearance. Identical models are kept as separate instances.");
    }
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
    const wasManual = pendingManualArrangeRef.current;
    pendingManualArrangeRef.current = false;
    const result = autoArrangePlate(objects, dimensions, bedX, bedY, 5);
    if (result.objects) {
      pendingAddIdsRef.current.clear();
      onChange(result.objects);
      setSelected("");
      setError("");
      if (wasManual) setArrangeNotice(objects.length === 1
        ? "Single model centred on the build plate."
        : "Models arranged with 5 mm clearance.");
    } else if (wasManual || pendingAddIdsRef.current.size === 0) {
      pendingAddIdsRef.current.clear();
      setArrangeNotice("");
      setError(result.error + " Existing models were left unchanged.");
    } else {
      // A failed packing heuristic is not grounds for deleting the imported
      // mesh. Keep the object selectable and report its measured XY envelope.
      const sizes = objects.map(item => {
        const d = dimensions[item.instance_id];
        const name = sourceFiles.find(f => String(f.id) === String(item.asset_id))?.name || "Model";
        return d ? name + " (" + pretty(d.width) + " × " + pretty(d.depth) + " mm)" : name;
      });
      pendingAddIdsRef.current.clear();
      setArrangeNotice("");
      setError(result.error + " Models were kept on the plate for inspection. " +
        "Measured footprints: " + sizes.join("; ") +
        ". Available plate: " + pretty(bedX) + " × " + pretty(bedY) + " mm.");
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

  function duplicateSelected() {
    if (!chosen || objects.length >= MAX_OBJECTS) return;
    // A duplicate must retain orientation, colour and individual XYZ scale.
    // Assign a new instance identity, then arrange after its mesh is measured.
    const copy = { ...chosen, instance_id: plateUuid() };
    if (Array.isArray(chosen.scale_xyz_percent))
      copy.scale_xyz_percent = [...chosen.scale_xyz_percent];
    pendingArrangeRef.current = true;
    pendingAddIdsRef.current.add(copy.instance_id);
    onChange([...objects, copy]);
    setSelected(copy.instance_id);
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
    if (field === "scale_percent") candidate.scale_xyz_percent = [value, value, value];
    if (field === "scale_xyz_percent") {
      if (!Array.isArray(value) || value.length !== 3 ||
          value.some(axis => !Number.isFinite(axis) || axis < 5 || axis > 400)) {
        setError("Each axis scale must be between 5% and 400%.");
        return;
      }
      candidate.scale_percent = 100;
    }
    if (["x_mm", "y_mm", "rotation_deg", "scale_percent", "scale_xyz_percent"].includes(field) &&
        !validPlacement(candidate, objects)) {
      setError("This position or transform overlaps another model, exceeds the build plate, or has dimensions still loading. Try Auto-arrange.");
      return;
    }
    setError("");
    onChange(objects.map(item => item.instance_id === chosen.instance_id ? candidate : item));
  }

  function applySelectedTransform(fields, message) {
    if (!chosen || !canEdit) return;
    const candidate = { ...chosen, ...fields };
    if (!validPlacement(candidate, objects)) {
      setError(message || "The selected transformation would overlap another model or leave the build plate.");
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
    if (imports.some(file => !/\.(stl|3mf)$/i.test(file.name) || !file.size ||
      file.size > (/\.3mf$/i.test(file.name) ? MAX_3MF_IMPORT_BYTES : MAX_FILE_BYTES))) {
      setError("Choose STL files below 32 MiB or 3MF files below 16 MiB.");
      return;
    }
    setUploadBusy(true);
    setError("");
    const additions = [];
    const previews = [];
    let imported3mfCount = 0;
    let oversizedForSlice = 0;
    try {
      for (const original of imports) {
        // Geometry-only conversion uses the same owner-scoped STL upload
        // endpoint as normal imports; native project settings are not retained.
        const converted = /\.3mf$/i.test(original.name)
          ? await threeMfGeometryToStl(original) : null;
        const file = converted?.file || original;
        if (converted) {
          imported3mfCount += 1;
          if (converted.exceedsPackagedSliceLimit) oversizedForSlice += 1;
        }
        const form = new FormData();
        form.append("file", file);
        if (saveImports) {
          form.append("category", "mesh");
          form.append("name", file.name);
        }
        const result = await apiFetch(saveImports ? "/api/files/" :
          "/api/printing/slicer/meshes/temporary/", { method: "POST", body: form });
        const id = String(saveImports ? (result?.file?.id || "") : (result?.asset_id || ""));
        if (!id) throw new Error("MakerVault did not return an STL input identifier.");
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
        onLocalAssetsChange?.(current => [...current, ...previews]);
        pendingArrangeRef.current = true;
        additions.forEach(item => pendingAddIdsRef.current.add(item.instance_id));
        onChange([...objects, ...additions]);
        if (!objects.length) onPrimaryChange?.(additions[0].asset_id);
        setSelected(additions[0].instance_id);
        if (imported3mfCount) {
          setArrangeNotice(imported3mfCount + " 3MF project" +
            (imported3mfCount === 1 ? "" : "s") +
            " imported as flattened STL geometry. Part positions within each project are retained, " +
            "but native 3MF settings, material painting, and separate part editing are not imported." +
            (oversizedForSlice
              ? " " + oversizedForSlice + " imported model(s) exceed the validated " +
                "3MF geometry limit. Slicing may be unavailable until the geometry is simplified."
              : ""));
        }
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

    // Draw the selected native printer polygon where available; use a
    // plainly rectangular, labelled fallback when no inspected profile exists.
    const nativePoints = Array.isArray(plate?.polygon_mm) &&
      plate.polygon_mm.length >= 3 && plate.polygon_mm.length <= 24 &&
      plate.polygon_mm.every(row => Array.isArray(row) && row.length === 2 &&
        row.every(v => typeof v === "number" && Number.isFinite(v) && Math.abs(v) <= 10000))
      ? plate.polygon_mm : null;
    const nativeBounds = plate?.bounds_mm;
    const centerX = nativePoints && Array.isArray(nativeBounds?.min) && Array.isArray(nativeBounds?.max)
      ? (nativeBounds.min[0] + nativeBounds.max[0]) / 2 : bedX / 2;
    const centerY = nativePoints && Array.isArray(nativeBounds?.min) && Array.isArray(nativeBounds?.max)
      ? (nativeBounds.min[1] + nativeBounds.max[1]) / 2 : bedY / 2;
    const points = nativePoints
      ? nativePoints.map(([x, y]) => [x - centerX, y - centerY])
      : [[-bedX / 2, -bedY / 2], [bedX / 2, -bedY / 2],
        [bedX / 2, bedY / 2], [-bedX / 2, bedY / 2]];
    const plateShape = new THREE.Shape();
    points.forEach(([x, y], index) => {
      if (index === 0) plateShape.moveTo(x, y);
      else plateShape.lineTo(x, y);
    });
    plateShape.closePath();
    const profileArtwork = /^\/api\/printing\/slicer\/profiles\/[0-9a-f-]{36}\/artwork\/$/i.test(
      String(plate?.artwork_url || "")
    ) ? plate.artwork_url : null;
    const bundledArtwork = nativeBedArtwork(printerLabel, bedX, bedY);
    const artworkPath = showNativeArtwork
      ? (profileArtwork || bundledArtwork) : null;
    const useMakerVaultBed = !artworkPath;
    // An official bed uses one stable, non-repeating surface. Drawing its
    // artwork on that same texture avoids coplanar z-fighting during orbit.
    const bedTexture = useMakerVaultBed
      ? makeMakerVaultPlateTexture(plateType, bedX, bedY)
      : (() => {
          const canvas = document.createElement("canvas");
          canvas.width = 2048;
          canvas.height = 2048;
          const context = canvas.getContext("2d");
          if (context) {
            context.fillStyle = PLATE_SURFACE[plateType]?.base || "#263342";
            context.fillRect(0, 0, canvas.width, canvas.height);
          }
          const texture = new THREE.CanvasTexture(canvas);
          texture.colorSpace = THREE.SRGBColorSpace;
          texture.minFilter = THREE.LinearMipmapLinearFilter;
          texture.magFilter = THREE.LinearFilter;
          texture.generateMipmaps = true;
          texture.anisotropy = Math.min(16, renderer.capabilities.getMaxAnisotropy());
          return texture;
        })();
    const bedGeometry = new THREE.ShapeGeometry(plateShape);
    {
      const positions = bedGeometry.getAttribute("position");
      const uv = bedGeometry.getAttribute("uv");
      for (let i = 0; i < positions.count; i++) {
        uv.setXY(i,
          (positions.getX(i) + bedX / 2) / bedX,
          (positions.getY(i) + bedY / 2) / bedY);
      }
      uv.needsUpdate = true;
    }
    const bed = new THREE.Mesh(
      bedGeometry,
      new THREE.MeshStandardMaterial({
        color: bedTexture ? "#ffffff" : (PLATE_SURFACE[plateType]?.base || "#263342"),
        map: bedTexture, side: THREE.DoubleSide, roughness: 0.94,
      }),
    );
    scene.add(bed);
    // Make the fallback an actual thin three-dimensional build plate, not
    // a flat coloured reference grid. The geometry follows the full native
    // polygon, including unusual bed shapes, rather than a fixed 220mm STL.
    const plateDepth = Math.max(3, Math.min(6, Math.min(bedX, bedY) * 0.018));
    const plateBodyGeometry = new THREE.ExtrudeGeometry(plateShape, {
      depth: plateDepth - 0.5, bevelEnabled: true, bevelSegments: 2,
      bevelSize: Math.min(0.55, plateDepth * 0.12),
      bevelThickness: 0.25, curveSegments: 8,
    });
    const plateBody = new THREE.Mesh(plateBodyGeometry,
      new THREE.MeshStandardMaterial({
        color: useMakerVaultBed ? "#253544" : "#212831",
        metalness: 0.28, roughness: 0.68, side: THREE.DoubleSide,
      }));
    // Keep the extrusion's top slightly below the painted printable surface,
    // avoiding depth fighting with the branded texture and native art.
    plateBody.position.z = -plateDepth + 0.25;
    plateBody.renderOrder = -1;
    scene.add(plateBody);
    // A narrow illuminated edge strip gives the universal plate a visible
    // physical thickness in isometric views without altering build geometry.
    const rimGeometry = new THREE.ExtrudeGeometry(plateShape, {
      depth: 0.9, bevelEnabled: false, curveSegments: 8,
    });
    const plateRim = new THREE.Mesh(rimGeometry, new THREE.MeshStandardMaterial({
      color: useMakerVaultBed ? "#33aacf" : "#62798a",
      metalness: 0.38, roughness: 0.43, side: THREE.DoubleSide,
    }));
    plateRim.position.z = -1.5;
    plateRim.renderOrder = -1;
    scene.add(plateRim);
    let artworkTextureController = null;
    if (artworkPath) {
      const controller = new AbortController();
      artworkTextureController = controller;
      const loadArtwork = async (url, fallback = false) => {
        const response = await fetch(url, {
          credentials: "same-origin", signal: controller.signal,
        });
        if (!response.ok || Number(response.headers.get("Content-Length") || 0) > 512 * 1024)
          throw new Error("Official bed artwork unavailable.");
        const svgText = await response.text();
        if (svgText.length > 512 * 1024 ||
            !/^\\s*(?:<\\?xml[^>]*>\\s*)?<svg\\b/i.test(svgText))
          throw new Error("Official bed artwork must be an SVG.");
        // Keep the upstream vector markings, rasterised once onto the same
        // texture as the bed surface. Never render a second coplanar plate.
        const svg = svgText.replace(/<svg\\b/i, '<svg width="2048" height="2048"');
        const blobUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
        try {
          const artworkImage = new Image();
          await new Promise((resolve, reject) => {
            artworkImage.onload = resolve;
            artworkImage.onerror = () => reject(new Error("SVG image failed to decode."));
            artworkImage.src = blobUrl;
          });
          if (disposed || controller.signal.aborted) return;
          const canvas = bedTexture.image;
          const context = canvas?.getContext("2d");
          if (!context) throw new Error("Artwork canvas is unavailable.");
          context.clearRect(0, 0, canvas.width, canvas.height);
          context.fillStyle = PLATE_SURFACE[plateType]?.base || "#263342";
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.drawImage(artworkImage, 0, 0, canvas.width, canvas.height);
          bedTexture.needsUpdate = true;
          setNativeArtworkError(fallback
            ? "Profile artwork was unavailable; displaying bundled printer artwork." : "");
        } finally {
          URL.revokeObjectURL(blobUrl);
        }
      };
      void loadArtwork(artworkPath).catch(() => {
        if (disposed || controller.signal.aborted) return;
        if (profileArtwork && bundledArtwork && profileArtwork !== bundledArtwork) {
          void loadArtwork(bundledArtwork, true).catch(() => {
            if (!disposed) setNativeArtworkError("Official artwork is unavailable; the 3D plate remains usable.");
          });
        } else setNativeArtworkError("Official artwork is unavailable; the 3D plate remains usable.");
      });
    }
    // The native STL is strictly decorative: never add it to the editable
    // model collection or include it in slicing, collision or auto-arrange.
    const nativeBedModelUrl = /^\/api\/printing\/slicer\/profiles\/[0-9a-f-]{36}\/bed-model\/$/i.test(
      String(plate?.bed_model_url || "")
    ) ? plate.bed_model_url : null;
    let nativeBedMesh = null;
    const nativeBedController = new AbortController();
    if (showNativeArtwork && nativeBedModelUrl) {
      fetch(nativeBedModelUrl, { credentials: "same-origin", signal: nativeBedController.signal })
        .then(async response => {
          if (!response.ok || Number(response.headers.get("Content-Length") || 0) > 4 * 1024 * 1024)
            throw new Error("Native bed model unavailable.");
          const raw = await response.arrayBuffer();
          if (raw.byteLength > 4 * 1024 * 1024) throw new Error("Native bed model exceeds limit.");
          return raw;
        })
        .then(raw => {
          if (disposed) return;
          const geometry = new STLLoader().parse(raw);
          geometry.computeBoundingBox();
          const bounds = geometry.boundingBox;
          if (!bounds || bounds.isEmpty()) { geometry.dispose(); return; }
          // Native STL coordinates are in machine space. Preserve XY and move
          // the uppermost face below the actual printable surface at Z=0.
          const size = new THREE.Vector3();
          bounds.getSize(size);
          if (size.x > bedX * 1.5 || size.y > bedY * 1.5 ||
              !Number.isFinite(size.z) || size.z > 100) {
            geometry.dispose();
            return;
          }
          nativeBedMesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
            color: "#465968", metalness: 0.35, roughness: 0.78,
            side: THREE.DoubleSide,
          }));
          nativeBedMesh.position.set(-centerX, -centerY, -bounds.max.z - 0.55);
          nativeBedMesh.userData.decorativeBed = true;
          plateBody.visible = false;
          plateRim.visible = false;
          scene.add(nativeBedMesh);
        })
        .catch(() => { /* Missing/unavailable native bed mesh uses generated fallback geometry. */ });
    }
    // Millimetre-accurate 10 mm minor / 50 mm major divisions. Clip grid
    // lines to the native polygon, rather than drawing an oversized square.
    const inside = (x, y) => {
      let hit = false;
      for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
        const [xi, yi] = points[i], [xj, yj] = points[j];
        if ((yi > y) !== (yj > y) &&
            x < (xj - xi) * (y - yi) / (yj - yi) + xi) hit = !hit;
      }
      return hit;
    };
    const minor = [], major = [];
    const drawReferenceGrid = !showNativeArtwork;
    const step = 2;
    for (let x = -bedX / 2; x <= bedX / 2 + 1e-5; x += step) {
      const isGridLine = Math.abs(x / 10 - Math.round(x / 10)) < 1e-5;
      if (!isGridLine || !drawReferenceGrid) continue;
      const target = Math.abs(x / 50 - Math.round(x / 50)) < 1e-5 ? major : minor;
      for (let y = -bedY / 2; y < bedY / 2; y += step) {
        const yy = Math.min(y + step, bedY / 2);
        if (inside(x, (y + yy) / 2) && !(useMakerVaultBed &&
            (x + bedX / 2) / bedX > 0.34 && (x + bedX / 2) / bedX < 0.66 &&
            (y + bedY / 2) / bedY < 0.16)) target.push(x, y, 0.24, x, yy, 0.24);
      }
    }
    for (let y = -bedY / 2; y <= bedY / 2 + 1e-5; y += step) {
      const isGridLine = Math.abs(y / 10 - Math.round(y / 10)) < 1e-5;
      if (!isGridLine || !drawReferenceGrid) continue;
      const target = Math.abs(y / 50 - Math.round(y / 50)) < 1e-5 ? major : minor;
      for (let x = -bedX / 2; x < bedX / 2; x += step) {
        const xx = Math.min(x + step, bedX / 2);
        if (inside((x + xx) / 2, y) && !(useMakerVaultBed &&
            (y + bedY / 2) / bedY < 0.16 &&
            ((x + xx) / 2 + bedX / 2) / bedX > 0.34 &&
            ((x + xx) / 2 + bedX / 2) / bedX < 0.66)) target.push(x, y, 0.24, xx, y, 0.24);
      }
    }
    const gridLines = [minor, major].map((coords, index) => {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(coords, 3));
      const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({
        color: index ? 0x637d97 : 0x3c536b, transparent: true, opacity: index ? 0.22 : 0.10,
        depthWrite: false,
      }));
      scene.add(lines);
      return lines;
    });
    const boundary = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(points.map(([x, y]) => new THREE.Vector3(x, y, 0.5))),
      new THREE.LineBasicMaterial({ color: "#7dd3fc" }),
    );
    scene.add(boundary);
    const markings = [];
    const makeLabel = (message, x, y, width = 42) => {
      const canvas = document.createElement("canvas");
      canvas.width = 256; canvas.height = 80;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      // Fit long printer names inside the generated on-bed artwork instead
      // of cropping manufacturer/model strings against the canvas boundary.
      let fontSize = 39;
      ctx.font = "bold " + fontSize + "px sans-serif";
      while (fontSize > 15 && ctx.measureText(message).width > 236) {
        fontSize -= 2;
        ctx.font = "bold " + fontSize + "px sans-serif";
      }
      ctx.fillStyle = "#b3cada";
      ctx.textAlign = "center";
      ctx.fillText(message, 128, 52);
      const texture = new THREE.CanvasTexture(canvas);
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, width * 80 / 256),
        new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      mesh.position.set(x, y, 0.7);
      scene.add(mesh); markings.push(mesh);
    };
    // Negative Y is front in the same coordinate system used by the camera.
    if (showOrientationLabels) {
      makeLabel("FRONT · −Y", 0, -bedY / 2 + 8, Math.min(bedX * 0.28, 64));
      makeLabel("REAR · +Y", 0, bedY / 2 - 8, Math.min(bedX * 0.28, 64));
    }
    if (showAxisLabels) {
      makeLabel("X →", bedX / 2 - 19, -bedY / 2 + 16, 28);
      makeLabel("Y ↑", -bedX / 2 + 18, bedY / 2 - 17, 28);
    }
    // Label the native printer identity, not a guessed manufacturer logo.
    // A generic bed remains visibly distinct without impersonating OEM art.
    const machineName = String(printerLabel || "").trim().slice(0, 38);
    if (showMachineLabel && machineName) makeLabel(machineName, 0, bedY / 2 - 21, Math.min(bedX * 0.58, 125));
    if (showDimensionsLabel) makeLabel(pretty(bedX) + " × " + pretty(bedY) + " mm", 0, -bedY / 2 + 23,
      Math.min(bedX * 0.35, 82));

    const camera = new THREE.PerspectiveCamera(45, 1, Math.max(2, Math.min(bedX, bedY) * 0.015), Math.max(4000, Math.max(bedX, bedY) * 12));
    camera.up.set(0, 0, 1);
    camera.position.set(bedX * 1.0, -bedY * 1.3, Math.max(bedX, bedY) * 1.35);
    camera.lookAt(0, 0, 0);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    const transform = new TransformControls(camera, renderer.domElement);
    const orientationCube = new SlicerOrientationCube(camera, renderer);
    transform.setSpace("world");
    transform.setTranslationSnap(0.5);
    transform.setRotationSnap(THREE.MathUtils.degToRad(5));
    transform.showZ = false;
    scene.add(transform.getHelper());
    transform.addEventListener("dragging-changed", event => {
      controls.enabled = !event.value;
    });

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
      if (!canEdit || event.button > 0 || transform.dragging) return;
      rayFromPointer(event);
      const hits = raycaster.intersectObjects([...meshes.values()], false);
      if (!hits.length) {
        setSelected("");
        exitToolModeRef.current?.();
        return;
      }
      const target = hits[0].object;
      const location = new THREE.Vector3();
      if (!raycaster.ray.intersectPlane(bedPlane, location)) return;
      const id = target.userData.instanceId;
      setSelected(id);
      if (latestToolModeRef.current !== "select") return;
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
    transform.addEventListener("mouseUp", () => {
      const mesh = transform.object;
      if (!mesh) return;
      const current = latestObjectsRef.current;
      const selectedItem = current.find(item => item.instance_id === mesh.userData.instanceId);
      if (!selectedItem) return;
      const candidate = { ...selectedItem,
        x_mm: Math.round(mesh.position.x * 2) / 2,
        y_mm: Math.round(mesh.position.y * 2) / 2,
        rotation_deg: Math.round(THREE.MathUtils.radToDeg(mesh.rotation.z) / 5) * 5,
      };
      if (latestToolModeRef.current === "scale") {
        const xyz = [mesh.scale.x, mesh.scale.y, mesh.scale.z].map(axis =>
          Math.round(axis * 1000) / 10);
        if (xyz.some(axis => !Number.isFinite(axis) || axis < 5 || axis > 400)) {
          setError("Model scale must remain between 5% and 400% on every axis.");
          const original = selectedItem.scale_xyz_percent || [
            selectedItem.scale_percent, selectedItem.scale_percent, selectedItem.scale_percent,
          ];
          mesh.scale.set(...original.map(value => value / 100));
          return;
        }
        candidate.scale_percent = 100;
        candidate.scale_xyz_percent = xyz;
      }
      if (!validPlacement(candidate, current)) {
        mesh.position.set(selectedItem.x_mm, selectedItem.y_mm, 0);
        mesh.rotation.z = THREE.MathUtils.degToRad(selectedItem.rotation_deg);
        const original = selectedItem.scale_xyz_percent || [
          selectedItem.scale_percent, selectedItem.scale_percent, selectedItem.scale_percent,
        ];
        mesh.scale.set(...original.map(value => value / 100));
        setError("Model handle transform exceeds the plate or overlaps another object.");
        return;
      }
      setError("");
      latestOnChangeRef.current(current.map(item =>
        item.instance_id === selectedItem.instance_id ? candidate : item));
    });
    const orientationPointerDown = event => {
      if (event.button !== 0) return;
      const face = orientationCube.pick(event);
      if (face) {
        event.stopImmediatePropagation();
        event.preventDefault();
        setPlateCamera(face);
      }
    };
    renderer.domElement.addEventListener("pointerdown", orientationPointerDown, true);
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
      orientationCube.render();
    });
    sceneRef.current = { scene, meshes, transform, camera, controls, bedX, bedY };
    return () => {
      disposed = true;
      sceneRef.current = null;
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", orientationPointerDown, true);
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointermove", pointerMove);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      renderer.domElement.removeEventListener("pointercancel", pointerUp);
      renderer.setAnimationLoop(null);
      controls.dispose();
      orientationCube.dispose();
      transform.detach();
      scene.remove(transform.getHelper());
      transform.dispose();
      for (const mesh of meshes.values()) {
        scene.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      nativeBedController.abort();
      artworkTextureController?.abort();
      if (nativeBedMesh) {
        scene.remove(nativeBedMesh);
        nativeBedMesh.geometry.dispose();
        nativeBedMesh.material.dispose();
      }
      plateRim.geometry.dispose();
      plateRim.material.dispose();
      plateBody.geometry.dispose();
      plateBody.material.dispose();
      bed.geometry.dispose();
      bed.material.map?.dispose();
      bed.material.dispose();
      gridLines.forEach(line => {
        scene.remove(line);
        line.geometry.dispose();
        line.material.dispose();
      });
      markings.forEach(mesh => {
        scene.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.map?.dispose();
        mesh.material.dispose();
      });
      boundary.geometry.dispose();
      boundary.material.dispose();
      renderer.dispose();
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
    };
  }, [bedX, bedY, plate?.polygon_mm, plate?.bounds_mm, plateType, printerLabel,
    showNativeArtwork, showOrientationLabels, showMachineLabel, showDimensionsLabel, showAxisLabels, plate?.bed_model_url, plate?.artwork_url]);

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
            color: item.color || PALETTE[0], roughness: 0.72, metalness: 0.04, side: THREE.DoubleSide,
          }));
          mesh.userData.instanceId = item.instance_id;
          const latest = latestObjectsRef.current.find(row => row.instance_id === item.instance_id) || item;
          mesh.position.set(latest.x_mm, latest.y_mm, 0);
          mesh.rotation.z = latest.rotation_deg * Math.PI / 180;
          const xyz = latest.scale_xyz_percent || [latest.scale_percent, latest.scale_percent, latest.scale_percent];
          mesh.scale.set(xyz[0] / 100, xyz[1] / 100, xyz[2] / 100);
          state.meshes.set(item.instance_id, mesh);
          state.scene.add(mesh);
          if (latestToolModeRef.current !== "select" && item.instance_id === selectedInstanceId) {
            state.transform.setMode(latestToolModeRef.current === "move" ? "translate" :
              latestToolModeRef.current === "scale" ? "scale" : "rotate");
            state.transform.attach(mesh);
          }
        })
        .catch(err => { if (live && err.name !== "AbortError") setError(err.message || "STL preview failed."); });
    }
    return () => { live = false; controller.abort(); };
  }, [objectKey, sourceFiles, bedX, bedY, plate?.polygon_mm, plate?.bounds_mm, plateType, printerLabel,
    showNativeArtwork, showOrientationLabels, showMachineLabel, showDimensionsLabel, showAxisLabels, plate?.bed_model_url, plate?.artwork_url]);

  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    for (const item of objects) {
      const mesh = state.meshes.get(item.instance_id);
      if (!mesh) continue;
      mesh.position.set(item.x_mm, item.y_mm, 0);
      mesh.rotation.z = item.rotation_deg * Math.PI / 180;
      const xyz = item.scale_xyz_percent || [item.scale_percent, item.scale_percent, item.scale_percent];
      mesh.scale.set(xyz[0] / 100, xyz[1] / 100, xyz[2] / 100);
      // Position-only changes must never alter the displayed filament colour.
      mesh.material.color.set(item.color || PALETTE[0]);
      mesh.material.emissive.set(item.instance_id === selected ? "#164051" : "#000000");
      mesh.material.emissiveIntensity = item.instance_id === selected ? 0.18 : 0;
    }
    const selectedMesh = state.meshes.get(selected);
    if (canEdit && selectedMesh && (toolMode === "move" || toolMode === "rotate" || toolMode === "scale")) {
      state.transform.setMode(toolMode === "move" ? "translate" : toolMode === "scale" ? "scale" : "rotate");
      state.transform.showX = toolMode === "move" || toolMode === "scale";
      state.transform.showY = toolMode === "move" || toolMode === "scale";
      state.transform.showZ = toolMode === "rotate" || toolMode === "scale";
      state.transform.attach(selectedMesh);
    } else {
      state.transform.detach();
    }
  }, [objects, selected, toolMode, canEdit]);

  function setPlateCamera(view) {
    const state = sceneRef.current;
    if (!state) return;
    const { camera, controls, meshes } = state;
    const focus = new THREE.Vector3(0, 0, 0);
    let span = Math.max(80, Math.hypot(bedX, bedY) * 1.35);
    if (view === "selection") {
      const target = meshes.get(selected || chosen?.instance_id);
      if (target) {
        const box = new THREE.Box3().setFromObject(target);
        if (!box.isEmpty()) {
          box.getCenter(focus);
          const size = box.getSize(new THREE.Vector3());
          span = Math.max(35, size.length() * 2.3);
        }
      }
    }
    controls.target.copy(focus);
    camera.up.set(0, 0, 1);
    if (view === "top") {
      camera.position.copy(focus).add(new THREE.Vector3(0, -0.0001, span));
    } else if (view === "bottom") {
      camera.position.copy(focus).add(new THREE.Vector3(0, -0.0001, -span));
    } else if (view === "front") {
      camera.position.copy(focus).add(new THREE.Vector3(0, -span, span * 0.15));
    } else if (view === "rear") {
      camera.position.copy(focus).add(new THREE.Vector3(0, span, span * 0.15));
    } else if (view === "right") {
      camera.position.copy(focus).add(new THREE.Vector3(span, 0, span * 0.15));
    } else if (view === "left") {
      camera.position.copy(focus).add(new THREE.Vector3(-span, 0, span * 0.15));
    } else {
      camera.position.copy(focus).add(new THREE.Vector3(span * 0.7, -span, span * 0.85));
    }
    camera.lookAt(focus);
    controls.update();
  }

  return <section className="panel printingSection slicerPlatePanel" aria-labelledby="slicer-plate-heading">
    <div className="slicerPlateHeading">
      <h3 id="slicer-plate-heading">Visual build plate</h3>
      <button type="button" onClick={() => arrangeModels()} disabled={!canEdit || !objects.length || uploadBusy}>Auto-arrange models</button>
    </div>
    <div className="slicerPlateIdentity">
      <label htmlFor="slicer-plate-name">Plate name
        <input id="slicer-plate-name" type="text" value={plateLabel}
          maxLength={64} disabled={!canEdit}
          onChange={event => onPlateLabelChange?.(event.target.value)}
          onBlur={() => { if (!plateLabel.trim()) onPlateLabelChange?.("Plate 1"); }}
          placeholder="Plate 1" />
      </label>
      <span>Plate 1 of 1 · {PLATE_SURFACE[plateType]?.label || "Native default"} · {pretty(bedX)} × {pretty(bedY)} mm</span>
    </div>
    <p>Arrange models, change their size and position, and preview the build plate. Multiple models can be sliced together with an approved OrcaSlicer worker using one filament profile. Individual preview colours do not assign separate print materials.</p>
    <div className="slicerPlateWorkspace">
      <div className="slicerPlateCanvasColumn">
    <div className="slicerPlateCameraToolbar" role="toolbar" aria-label="Build-plate camera views">
      <button type="button" onClick={() => setPlateCamera("iso")} title="Isometric build-plate view">Isometric</button>
      <button type="button" onClick={() => setPlateCamera("top")} title="Top-down build-plate view">Top</button>
      <button type="button" onClick={() => setPlateCamera("front")} title="View the front of the printer build plate">Front</button>
      <button type="button" onClick={() => setPlateCamera("right")} title="View the right side of the printer build plate">Right</button>
      <button type="button" onClick={() => setPlateCamera("selection")} disabled={!chosen}
        title="Centre and zoom onto the currently selected model">Fit selected model</button>
    </div>
    <div ref={hostRef} className="slicerPlateCanvas" aria-label="Interactive three-dimensional model plate preview with a clickable six-face orientation cube in the top right" />

    <fieldset className="slicerPlateDisplayOptions">
      <legend>Build plate display</legend>
      <div className="slicerPlateDisplayOptionsRow">
        {(nativeBedArtwork(printerLabel, bedX, bedY) || plate?.artwork_url || plate?.bed_model_url) && <label>
          <input type="checkbox" checked={showNativeArtwork}
            onChange={event => {
              setNativeArtworkError("");
              setShowNativeArtwork(event.target.checked);
            }} />
          <span>Official bed artwork</span>
        </label>}
        <label><input type="checkbox" checked={showOrientationLabels}
          onChange={event => setShowOrientationLabels(event.target.checked)} />
          <span>Front / rear</span></label>
        <label><input type="checkbox" checked={showMachineLabel}
          onChange={event => setShowMachineLabel(event.target.checked)} />
          <span>Printer name</span></label>
        <label><input type="checkbox" checked={showDimensionsLabel}
          onChange={event => setShowDimensionsLabel(event.target.checked)} />
          <span>Dimensions</span></label>
        <label><input type="checkbox" checked={showAxisLabels}
          onChange={event => setShowAxisLabels(event.target.checked)} />
          <span>X / Y axes</span></label>
        <button type="button" onClick={() => {
          const anyVisible = showOrientationLabels || showMachineLabel ||
            showDimensionsLabel || showAxisLabels;
          setShowOrientationLabels(!anyVisible);
          setShowMachineLabel(!anyVisible);
          setShowDimensionsLabel(!anyVisible);
          setShowAxisLabels(!anyVisible);
        }}>
          {showOrientationLabels || showMachineLabel || showDimensionsLabel || showAxisLabels
            ? "Hide all labels" : "Show all labels"}
        </button>
      </div>
    </fieldset>
    {showNativeArtwork && nativeArtworkError && <p role="status" className="integrationError">{nativeArtworkError}</p>}
    {showNativeArtwork && (plate?.artwork_url || nativeBedArtwork(printerLabel, bedX, bedY)) &&
      !plate?.bed_model_url && <p className="slicerPlateHint">
        Official vector surface artwork on a 3D plate. This printer profile does not provide
        a manufacturer 3D bed model, so MakerVault generates the underlying plate geometry.
      </p>}
    <p className="slicerPlateHint"><strong>Selected surface:</strong> {PLATE_SURFACE[plateType]?.label || "Native default"} · Physical plate not detected. {!showNativeArtwork || !(plate?.artwork_url || plate?.bed_model_url || nativeBedArtwork(printerLabel, bedX, bedY)) ? "MakerVault 3D build plate." : ""} {showNativeArtwork && (plate?.artwork_url || nativeBedArtwork(printerLabel, bedX, bedY)) &&
      <small>Native artwork: {plate?.artwork_url ? "Imported official OrcaSlicer profile" : "OrcaSlicer v2.4.2"} (AGPL-3.0)</small>}</p>
    <p className="slicerPlateHint"><strong>Build plate volume:</strong> {pretty(bedX)} × {pretty(bedY)} mm (X × Y). Drag in 0.5 mm steps or enter coordinates below.</p>
    {arrangeNotice && <p role="status" className="slicerPlateHint">{arrangeNotice}</p>}
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
      {" · Plate ready to save as a draft or slice."}</p>}

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
      <label className="full">Add STL or 3MF files from your device
        <input type="file" accept=".stl,.3mf" multiple onChange={uploadFiles} disabled={!canEdit || uploadBusy || objects.length >= MAX_OBJECTS} />
      </label>
      <label className="full checkRow slicerPlateSaveImports"><input type="checkbox" checked={saveImports} onChange={event => setSaveImports(event.target.checked)} disabled={!canEdit || uploadBusy} />
        <span>Also save imported models to MakerVault Files</span>
      </label>
      <p className="full slicerPlateHint">3MF import loads geometry as one STL object per project (no native materials or editable part tree). Unchecked: imported meshes are retained privately for slicing and saved drafts, without appearing in MakerVault Files.</p>
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
      <button data-slicer-action="remove" type="button" disabled={!canEdit || !chosen} onClick={removeSelected}>Remove selected model</button>
      <button data-slicer-action="duplicate" type="button" disabled={!canEdit || !chosen || objects.length >= MAX_OBJECTS} onClick={duplicateSelected}>Duplicate selected</button>
    </div>}

    {objects.length > 0 && <div className="formGrid slicerPlateTransformFields">
      <label>X position (mm)
        <input data-slicer-field="x_mm" type="number" min={-10000} max={10000} step="0.5" value={chosen?.x_mm ?? 0}
          disabled={!canEdit} onChange={event => patch("x_mm", pretty(event.target.value))} />
      </label>
      <label>Y position (mm)
        <input type="number" min={-10000} max={10000} step="0.5" value={chosen?.y_mm ?? 0}
          disabled={!canEdit} onChange={event => patch("y_mm", pretty(event.target.value))} />
      </label>
      <div className="slicerTransformFieldWithReset">
        <label htmlFor="slicer-model-rotation">Rotation around Z (degrees)</label>
        <div className="slicerTransformInputRow">
          <input id="slicer-model-rotation" data-slicer-field="rotation_deg" type="number"
            min={-360} max={360} step="5" value={chosen?.rotation_deg ?? 0}
            disabled={!canEdit} onChange={event => patch("rotation_deg", pretty(event.target.value))} />
          <button type="button" title="Reset rotation to the model's imported orientation"
            disabled={!canEdit || !chosen || Number(chosen.rotation_deg || 0) === 0}
            onClick={() => applySelectedTransform({ rotation_deg: 0 },
              "Resetting the rotation would overlap another model or leave the build plate.")}>
            Reset
          </button>
        </div>
      </div>
      <div className="slicerTransformFieldWithReset">
        <label htmlFor="slicer-model-uniform-scale">Uniform scale (%)</label>
        <div className="slicerTransformInputRow">
          <input id="slicer-model-uniform-scale" data-slicer-field="scale_percent" type="number"
            min={5} max={400} step="5" value={chosen?.scale_percent ?? 100}
            disabled={!canEdit} onChange={event => patch("scale_percent", pretty(event.target.value))} />
          <button type="button" title="Restore 100% scale for all three axes"
            disabled={!canEdit || !chosen ||
              (Number(chosen.scale_percent ?? 100) === 100 &&
               (chosen.scale_xyz_percent || [100, 100, 100]).every(axis => Number(axis) === 100))}
            onClick={() => applySelectedTransform({
              scale_percent: 100, scale_xyz_percent: [100, 100, 100],
            }, "Resetting the scale would overlap another model or leave the build plate.")}>
            Reset
          </button>
        </div>
      </div>
      <fieldset className="slicerAxisScaling full">
        <legend>Independent axis scaling (%)</legend>
        {["X", "Y", "Z"].map((axis, index) => <label key={axis}>
          {axis} axis
          <input data-slicer-field={index === 0 ? "scale_xyz_percent" : undefined} type="number" min={5} max={400} step="1"
            value={chosen?.scale_xyz_percent?.[index] ?? chosen?.scale_percent ?? 100}
            disabled={!canEdit}
            onChange={event => {
              const current = chosen?.scale_xyz_percent || [
                chosen?.scale_percent || 100, chosen?.scale_percent || 100, chosen?.scale_percent || 100,
              ];
              const next = [...current];
              next[index] = pretty(event.target.value);
              patch("scale_xyz_percent", next);
            }} />
        </label>)}
      </fieldset>
      <label>Preview/material colour
        <input type="color" value={chosen?.color || PALETTE[0]} disabled={!canEdit}
          onChange={event => { onManualColorChange?.(chosen.instance_id); patch("color", event.target.value); }} />
      </label>
      <div className="settingsActions slicerModelActions">
        <button type="button" disabled={!canEdit} onClick={() => patch("rotation_deg", ((chosen.rotation_deg + 90) % 360))}>Rotate 90°</button>
        <button type="button" disabled={!canEdit || !chosen}
          onClick={() => applySelectedTransform({ x_mm: 0, y_mm: 0 },
            "Cannot centre this model without overlapping another model or leaving the build plate.")}>
          Centre selected
        </button>
        <button type="button" disabled={!canEdit || !chosen}
          onClick={() => applySelectedTransform({
            rotation_deg: 0, scale_percent: 100,
            scale_xyz_percent: [100, 100, 100],
          }, "Resetting the model would overlap another object or leave the plate.")}>
          Reset orientation / scale
        </button>
        <button data-slicer-action="arrange" type="button" disabled={!canEdit || !objects.length || uploadBusy}
          onClick={() => arrangeModels()}>Auto-arrange</button>
      </div>
    </div>}

        </div>
      </aside>
    </div>
    {footer && <div className="slicerPlateFooter">{footer}</div>}
  </section>;
}
