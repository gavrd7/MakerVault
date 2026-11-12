import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { threeMfGeometryToStl, MAX_3MF_IMPORT_BYTES } from "./slicer3mfGeometry";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import { createMakerVaultRotationGizmo } from "./slicerRotationGizmo";
import { SlicerOrientationCube } from "./slicerOrientationCube";
import SlicerUiIcon from "./SlicerUiIcon";
import { apiFetch } from "../api";
import { plateExtentWarning, plateFootprintsOverlap, autoArrangePlate, plateModelMeasurement,
  measurementDistance, measurementCircle, measurementFormat } from "./slicerPlateGeometry";
import { nativeBedArtwork } from "./slicerNativePlateArt";
import { detectMeshMeasurement, formatDetectedMeasurement } from "./slicerAutoMeasure";
import { evaluateAutoOrient, AUTO_ORIENT_GOALS } from "./slicerAutoOrient";
import { splitDisconnectedMesh } from "./slicerSplitObjects";
import { executeSolidOperation } from "./slicerSolidOperations";
import { PRIMITIVE_TYPES, createPrimitiveMesh, createPrimitiveStl } from "./slicerPrimitives";
import { validateStackPlacement } from "./slicerStacking";
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
  if (!ctx) return null;
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
    // The supplied SVG embeds a small raster image including its light-grey
    // backing. Only the icon is reused. Erase the icon's edge-connected
    // backdrop, then typeset the lettering at native canvas resolution so
    // neither an opaque patch nor rasterised text fringes cover the bed.
    const iconCanvas = document.createElement("canvas");
    iconCanvas.width = 140;
    iconCanvas.height = 156;
    const iconCtx = iconCanvas.getContext("2d", { willReadFrequently: true });
    if (!iconCtx) return;
    iconCtx.drawImage(logo, 0, 0, 70, 78, 0, 0, 140, 156);
    const bitmap = iconCtx.getImageData(0, 0, 140, 156);
    const w = bitmap.width, h = bitmap.height, pixels = bitmap.data;
    const sample = (x, y) => Array.from(pixels.slice((y * w + x) * 4, (y * w + x) * 4 + 3));
    // Use the corners to derive the image's actual background colour.
    const corners = [sample(0, 0), sample(w - 1, 0),
      sample(0, h - 1), sample(w - 1, h - 1)];
    const background = [0, 1, 2].map(channel =>
      corners.reduce((sum, rgb) => sum + rgb[channel], 0) / corners.length);
    const colourDistance = index => Math.sqrt(
      (pixels[index] - background[0]) ** 2 +
      (pixels[index + 1] - background[1]) ** 2 +
      (pixels[index + 2] - background[2]) ** 2);
    const seen = new Uint8Array(w * h);
    const queue = [];
    const enqueue = (x, y) => {
      if (x < 0 || y < 0 || x >= w || y >= h) return;
      const index = y * w + x;
      if (seen[index] || colourDistance(index * 4) > 72) return;
      seen[index] = 1;
      queue.push(index);
    };
    for (let x = 0; x < w; x++) { enqueue(x, 0); enqueue(x, h - 1); }
    for (let y = 0; y < h; y++) { enqueue(0, y); enqueue(w - 1, y); }
    for (let pointer = 0; pointer < queue.length; pointer++) {
      const index = queue[pointer];
      const x = index % w, y = Math.floor(index / w);
      pixels[index * 4 + 3] = 0;
      enqueue(x - 1, y); enqueue(x + 1, y);
      enqueue(x, y - 1); enqueue(x, y + 1);
    }
    iconCtx.putImageData(bitmap, 0, 0);
    ctx.save();
    ctx.globalAlpha = 0.94;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(iconCanvas, 371, 890, 78, 87);
    // Canvas text is resolution-independent and sits directly on the bed.
    // Keep the colour split from the official wordmark without its raster
    // anti-aliasing/background artefacts.
    const labelStart = 451, labelTop = 933, availableWidth = 199;
    let font = 39;
    ctx.font = "700 " + font + "px system-ui, sans-serif";
    while (font > 20 && ctx.measureText("MakerVault").width > availableWidth) {
      font -= 1;
      ctx.font = "700 " + font + "px system-ui, sans-serif";
    }
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#d4e2ed";
    ctx.fillText("Maker", labelStart, labelTop);
    ctx.fillStyle = "#49b9e8";
    ctx.fillText("Vault", labelStart + ctx.measureText("Maker").width, labelTop);
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
    x_mm: (index % 4) * 25, y_mm: Math.floor(index / 4) * 25, z_mm: 0,
    rotation_deg: 0, rotation_xyz_deg: [0, 0], scale_percent: 100, scale_xyz_percent: [100, 100, 100],
    color: PALETTE[index % PALETTE.length],
  };
}

function positionOrientedMesh(mesh, item) {
  const [rx, ry] = item.rotation_xyz_deg || [0, 0];
  mesh.rotation.set(THREE.MathUtils.degToRad(rx), THREE.MathUtils.degToRad(ry),
    THREE.MathUtils.degToRad(item.rotation_deg || 0), "XYZ");
  const xyz = item.scale_xyz_percent || [item.scale_percent, item.scale_percent, item.scale_percent];
  mesh.scale.set(...xyz.map(v => v / 100));
  mesh.position.set(item.x_mm, item.y_mm, 0);
  // Exact vertex minimum, not the tilted cuboid approximation. Cache the
  // expensive mesh scan by orientation and scale so dragging X/Y remains fast.
  const pose = [rx, ry, item.rotation_deg || 0, ...xyz].join(":");
  if (mesh.userData.bedPose !== pose) {
    mesh.updateMatrix();
    const positions = mesh.geometry.getAttribute("position");
    const e = mesh.matrix.elements;
    let minZ = Infinity;
    if (positions) {
      for (let i = 0; i < positions.count; i++) {
        const z = e[2] * positions.getX(i) + e[6] * positions.getY(i) + e[10] * positions.getZ(i);
        if (z < minZ) minZ = z;
      }
    }
    mesh.userData.bedPose = pose;
    mesh.userData.bedZOffset = Number.isFinite(minZ) ? -minZ : 0;
  }
  mesh.position.z = mesh.userData.bedZOffset + Number(item.z_mm || 0);
  mesh.updateMatrix();
}

function pretty(value) {
  return Math.round(Number(value) * 100) / 100;
}

// These values are dimensionless geometry proxies, not minutes, grams or
// probabilities. Show their actual magnitude alongside a true delta from
// the best analysed pose. A zero baseline has no meaningful percent change.
function orientationComparison(metricValue) {
  if (!metricValue) return <span className="slicerOrientDelta isNeutral">—</span>;
  const value = Number(metricValue.absolute);
  const proxy = value === 0 ? "0" : Number(value.toPrecision(4)).toString();
  const percent = metricValue.percent;
  // All four proxies are costs: a smaller value is preferable.
  // The comparison is with the best value PER metric, not the first card.
  const tied = percent !== null && percent === 0;
  const deltaClass = percent === null ? "isNeutral" : tied ? "isBetter" : "isWorse";
  const deltaText = percent === null ? "↑ from zero baseline" :
    tied ? "✓ Best / tied" : "↑ +" + percent + "% worse";
  return <>
    <span className="slicerOrientProxy">{proxy}</span>
    <span className={"slicerOrientDelta " + deltaClass}>{deltaText}</span>
  </>;
}

export default function SlicerPlateEditor({
  files = [], objects = [], onChange, onPrimaryChange, plate = null, plateType = "default",
  plateLabel = "Plate 1", onPlateLabelChange, printerLabel = "",
  canEdit = false, onFilesUploaded, defaultColor = null, onManualColorChange, footer = null,
  selectedInstanceId = null, onSelectedInstanceChange, selectedInstanceIds = [], onSelectModel, toolMode = "select",
  autoOrientGoal = "balanced", autoOrientRequest = 0, splitRequest = 0, solidRequest = null,
  measurementVisible = false, measureMode = "distance", measureUnit = "mm", measureSnapMode = "auto", measureClearVersion = 0,
  onMeasurePinPlaced,
  localAssets = [], onLocalAssetsChange, onExitToolMode, onPlateIssuesChange, toolbar = null,
}) {
  const hostRef = useRef(null);
  const sceneRef = useRef(null);
  const latestObjectsRef = useRef(objects);
  const latestOnChangeRef = useRef(onChange);
  const latestToolModeRef = useRef(toolMode);
  const measurePinPlacedRef = useRef(onMeasurePinPlaced);
  measurePinPlacedRef.current = onMeasurePinPlaced;
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
  const [showNativeArtwork, setShowNativeArtwork] = useState(true);
  const [undersidePlateMode, setUndersidePlateMode] = useState("auto");
  const undersidePlateModeRef = useRef(undersidePlateMode);
  undersidePlateModeRef.current = undersidePlateMode;
  const [nativeArtworkError, setNativeArtworkError] = useState("");
  const [showOrientationLabels, setShowOrientationLabels] = useState(false);
  const [showMachineLabel, setShowMachineLabel] = useState(false);
  const [showDimensionsLabel, setShowDimensionsLabel] = useState(false);
  const [showAxisLabels, setShowAxisLabels] = useState(false);
  const selected = selectedInstanceId === null ? localSelected : selectedInstanceId;
  const selection = selectedInstanceIds.length ? selectedInstanceIds : (selected ? [selected] : []);
  const selectionRef = useRef(selection);
  selectionRef.current = selection;
  const onSelectModelRef = useRef(onSelectModel);
  onSelectModelRef.current = onSelectModel;
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
  const [measurePoints, setMeasurePoints] = useState([]);
  const [detectedFeature, setDetectedFeature] = useState(null);
  const [autoOrientAnalysis, setAutoOrientAnalysis] = useState(null);
  const [autoOrientChoice, setAutoOrientChoice] = useState(0);
  const [autoOrientBusy, setAutoOrientBusy] = useState(false);
  const [autoOrientModalOpen, setAutoOrientModalOpen] = useState(false);
  const [splitPreview, setSplitPreview] = useState(null);
  const [splitBusy, setSplitBusy] = useState(false);
  const [splitError, setSplitError] = useState("");
  const [solidDialog, setSolidDialog] = useState(null);
  const [solidPreview, setSolidPreview] = useState(null);
  const [solidBusy, setSolidBusy] = useState(false);
  const [solidError, setSolidError] = useState("");
  const [solidOptions, setSolidOptions] = useState({wall: 2, radius: 3, x_mm: 0, y_mm: 0, cutHeight: 5, cutAxis: "z", keep: "both", booleanMode: "union", secondId: "", primitiveType: "box", width: 20, depth: 20, height: 20, z_mm: 10});
  // An applied result must always correspond to the options actually shown.
  useEffect(() => { setSolidPreview(null); }, [solidOptions]);
  const [measureOverlayExpanded, setMeasureOverlayExpanded] = useState(false);
  const [transformOverlayExpanded, setTransformOverlayExpanded] = useState(false);
  const [liveRotation, setLiveRotation] = useState(null);
  const [groupDeltaX, setGroupDeltaX] = useState(0);
  const [groupDeltaY, setGroupDeltaY] = useState(0);
  const [groupRotation, setGroupRotation] = useState(0);
  const latestMeasurementRef = useRef({ active: false, mode: "distance" });
  latestMeasurementRef.current = { active: measurementVisible, mode: measureMode, snapMode: measureSnapMode };
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
  const selectedMeasurement = chosen ? plateModelMeasurement(chosen, dimensions[chosen.instance_id]) : null;
  const pinDistance = measurePoints.length === 2 && measureMode === "distance"
    ? measurementDistance(measurePoints[0].point, measurePoints[1].point) : null;
  const pinCircle = measurePoints.length === 3 && measureMode === "circle"
    ? measurementCircle(...measurePoints.map(pin => pin.point)) : null;
  const objectKey = objects.map(item => item.instance_id + ":" + item.asset_id).join("|");
  const extentWarnings = objects.map((item, index) => ({
    id: item.instance_id,
    label: sourceFiles.find(file => String(file.id) === item.asset_id)?.name || "Model " + (index + 1),
    message: dimensions[item.instance_id]
      ? plateExtentWarning(item, dimensions[item.instance_id], bedX, bedY) : "",
  })).filter(row => row.message);
  const overlapWarnings = objects.flatMap((item, index) => objects.slice(index + 1)
    .filter(other => {
      const first = Number(item.z_mm || 0), second = Number(other.z_mm || 0);
      const h1 = plateModelMeasurement(item, dimensions[item.instance_id])?.height;
      const h2 = plateModelMeasurement(other, dimensions[other.instance_id])?.height;
      if (h1 != null && h2 != null &&
        (first >= second + h2 - 0.1 || second >= first + h1 - 0.1)) return false;
      return plateFootprintsOverlap(item, dimensions[item.instance_id],
        other, dimensions[other.instance_id], 0) === true;
    })
    .map(other => ({
      id: item.instance_id + ":" + other.instance_id,
      message: (sourceFiles.find(file => String(file.id) === item.asset_id)?.name || "Model " + (index + 1)) +
        " overlaps " + (sourceFiles.find(file => String(file.id) === other.asset_id)?.name || "another model"),
    })));

  // Warnings deliberately do not block editing. They DO gate all new slices,
  // including Quick slice, until the models have been separated.
  const dimensionWarnings = objects.filter(item => !dimensions[item.instance_id]).map(item => ({
    id: item.instance_id, message: "A model is still loading its dimensions.",
  }));
  const plateIssues = [...dimensionWarnings, ...extentWarnings, ...overlapWarnings];
  const conflictIds = new Set(overlapWarnings.flatMap(row => row.id.split(":")));
  const issueSignature = JSON.stringify(objects);
  const issueKey = JSON.stringify(plateIssues.map(row => [row.id, row.message]));
  useEffect(() => {
    onPlateIssuesChange?.({ signature: issueSignature, issues: plateIssues });
  }, [issueSignature, issueKey, onPlateIssuesChange]);

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
    if (!own || plateExtentWarning(candidate, own, bedX, bedY)) return false;
    if (!items.some(item => Number(item.instance_id === candidate.instance_id
      ? candidate.z_mm || 0 : item.z_mm || 0) > 0)) return true;
    const state = sceneRef.current;
    const mesh = state?.meshes.get(candidate.instance_id);
    if (!mesh) return false;
    const previous = items.find(item => item.instance_id === candidate.instance_id);
    positionOrientedMesh(mesh, candidate);
    const verdict = validateStackPlacement(
      items.map(row => row.instance_id === candidate.instance_id ? candidate : row),
      state.meshes, candidate.instance_id, bedX, bedY, true);
    if (previous) positionOrientedMesh(mesh, previous);
    if (!verdict.valid) setError(verdict.reason);
    return verdict.valid;
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
    if (field === "z_mm" && (!Number.isFinite(value) || value < 0 || value > 1000)) {
      setError("Model elevation must be between 0 and 1000 mm.");
      return;
    }
    if (field === "scale_xyz_percent") {
      if (!Array.isArray(value) || value.length !== 3 ||
          value.some(axis => !Number.isFinite(axis) || axis < 5 || axis > 400)) {
        setError("Each axis scale must be between 5% and 400%.");
        return;
      }
      candidate.scale_percent = 100;
    }
    if (["x_mm", "y_mm", "z_mm", "rotation_deg", "rotation_xyz_deg", "scale_percent", "scale_xyz_percent"].includes(field) &&
        !validPlacement(candidate, objects)) {
      setError(Number(candidate.z_mm || 0) > 0 || objects.some(item => Number(item.z_mm || 0) > 0)
        ? "Move rejected: models must have a continuous contact path to the bed without intersecting."
        : "This transform overlaps another model, exceeds the build plate, or has dimensions still loading.");
      return;
    }
    setError("");
    onChange(objects.map(item => item.instance_id === chosen.instance_id ? candidate : item));
  }

  useEffect(() => {
    setAutoOrientAnalysis(null);
    setAutoOrientChoice(0);
  }, [selected, toolMode, objects.length, chosen?.rotation_deg,
    chosen?.rotation_xyz_deg?.[0], chosen?.rotation_xyz_deg?.[1],
    chosen?.scale_percent, chosen?.scale_xyz_percent?.[0],
    chosen?.scale_xyz_percent?.[1], chosen?.scale_xyz_percent?.[2],
    chosen?.x_mm, chosen?.y_mm]);

  const analyseOrientations = () => {
    if (!chosen || !canEdit || autoOrientBusy) return;
    const mesh = sceneRef.current?.meshes.get(chosen.instance_id);
    if (!mesh) {
      setAutoOrientAnalysis({ error: "The model mesh is still loading. Try again when it appears on the plate." });
      return;
    }
    setAutoOrientBusy(true);
    setAutoOrientAnalysis(null);
    // Yield to the browser to render progress before bounded mesh analysis.
    requestAnimationFrame(() => {
      try {
        const result = evaluateAutoOrient(mesh.geometry, chosen, bedX, bedY,
          objects, dimensionsRef.current);
        setAutoOrientAnalysis(result);
        setAutoOrientChoice(0);
      } catch (error) {
        setAutoOrientAnalysis({ error: error.message || "Unable to evaluate model orientations." });
      } finally {
        setAutoOrientBusy(false);
      }
    });
  };

  const applyAutoOrientation = () => {
    const candidate = autoOrientAnalysis?.choices?.[autoOrientGoal]?.[autoOrientChoice];
    if (!chosen || !candidate || !canEdit) return;
    applySelectedTransform(candidate.orientation,
      "The suggested orientation no longer fits the build plate. Move other models and analyse again.");
    setAutoOrientAnalysis(null);
    setAutoOrientModalOpen(false);
    exitToolModeRef.current?.();
  };

  // The toolbar owns the goal. Opening comparison never commits a transform.
  useEffect(() => {
    if (!autoOrientRequest) return;
    setAutoOrientModalOpen(true);
    setAutoOrientChoice(0);
    analyseOrientations();
  }, [autoOrientRequest]);

  // Preview the selected pose as a translucent duplicate beside the solid
  // original. The ghost is display-only and never changes objects or exports.
  useEffect(() => {
    if (!autoOrientModalOpen || !chosen) return undefined;
    const state = sceneRef.current;
    const original = state?.meshes.get(chosen.instance_id);
    const candidate = autoOrientAnalysis?.choices?.[autoOrientGoal]?.[autoOrientChoice];
    if (!state || !original || !candidate) return undefined;
    const ghost = new THREE.Mesh(original.geometry, new THREE.MeshBasicMaterial({
      color: "#89d9ff", transparent: true, opacity: 0.3,
      depthWrite: false, side: THREE.DoubleSide,
    }));
    ghost.userData.isOrientationPreview = true;
    positionOrientedMesh(ghost, { ...chosen, ...candidate.orientation });
    ghost.renderOrder = 8;
    state.scene.add(ghost);
    return () => {
      state.scene.remove(ghost);
      ghost.material.dispose();
    };
  }, [autoOrientModalOpen, autoOrientAnalysis, autoOrientGoal, autoOrientChoice,
    chosen?.instance_id, chosen?.x_mm, chosen?.y_mm]);

  useEffect(() => {
    if (!solidRequest?.id || !canEdit) return;
    const item = objects.find(row => row.instance_id === selected) || objects[0];
    const mesh = item && sceneRef.current?.meshes.get(item.instance_id);
    setSolidError("");
    setSolidPreview(null);
    if (!mesh && solidRequest.kind !== "primitive") {
      setSolidError("Select a loaded STL model to edit.");
      return;
    }
    mesh?.updateMatrixWorld(true);
    const box = mesh ? new THREE.Box3().setFromObject(mesh) :
      new THREE.Box3(new THREE.Vector3(-10,-10,0),new THREE.Vector3(10,10,20));
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    setSolidOptions({
      wall: pretty(Math.max(0.4, Math.min(size.x,size.y,size.z)*0.08)),
      radius: pretty(Math.max(0.5,Math.min(size.x,size.y)/10)),
      x_mm: pretty(center.x), y_mm: pretty(center.y),
      cutHeight: pretty((box.min.z+box.max.z)/2), cutAxis: "z",
      keep: "both", booleanMode: "union",
      secondId: objects.find(row => row.instance_id!==item?.instance_id)?.instance_id || "",
      primitiveType:"box", width:20,depth:20,height:20,z_mm:pretty(center.z),
    });
    setSolidDialog({kind:solidRequest.kind,id:item?.instance_id || null,name:
      solidRequest.kind === "primitive" ? "Primitive" :
      sourceFiles.find(file => String(file.id)===String(item?.asset_id))?.name || "Model"});
  }, [solidRequest?.id]);

  // Results are previewed as translucent, independent STL ghosts. None of
  // the source geometry or its saved coordinates is mutated before Apply.
  useEffect(() => {
    if (!solidPreview) return undefined;
    const state=sceneRef.current;
    if (!state) return undefined;
    const originals=[solidDialog?.id,solidPreview.secondId].filter(Boolean)
      .map(id=>state.meshes.get(id)).filter(Boolean);
    const visibility=originals.map(mesh=>mesh.visible);
    originals.forEach(mesh=>{mesh.visible=false;});
    const overlays=[];
    for (const [index,part] of solidPreview.parts.entries()) {
      const geom=new STLLoader().parse(part.buffer);
      const mesh=new THREE.Mesh(geom,new THREE.MeshStandardMaterial({
        color: PALETTE[(index+2)%PALETTE.length], transparent:true,
        opacity:0.8, roughness:0.75, side:THREE.DoubleSide,
      }));
      mesh.position.set(part.x_mm,part.y_mm,part.z_mm);
      mesh.userData.solidPreview=true;
      state.scene.add(mesh);overlays.push(mesh);
    }
    return () => {
      originals.forEach((mesh,index)=>{mesh.visible=visibility[index];});
      overlays.forEach(mesh=>{state.scene.remove(mesh);mesh.geometry.dispose();mesh.material.dispose();});
    };
  }, [solidPreview]);

  async function previewSolid() {
    if (!solidDialog || solidBusy) return;
    setSolidBusy(true);setSolidPreview(null);setSolidError("");
    try {
      // Allow React to render the busy state before potentially costly CSG.
      await new Promise(resolve=>setTimeout(resolve,0));
      const state=sceneRef.current;
      const target=state?.meshes.get(solidDialog.id);
      const second=solidDialog.kind==="boolean" ? state?.meshes.get(solidOptions.secondId) : null;
      if (!target && solidDialog.kind !== "primitive")
        throw new Error("Selected model is not loaded.");
      if (solidDialog.kind==="boolean" && (!second || second===target))
        throw new Error("Choose a different model for this Boolean operation.");
      let parts;
      if (solidDialog.kind==="primitive") {
        parts=[createPrimitiveStl(solidOptions)];
      } else if (solidDialog.kind==="negative") {
        const tool=createPrimitiveMesh(solidOptions,[
          Number(solidOptions.x_mm),Number(solidOptions.y_mm),
          Number(solidOptions.z_mm)-Number(solidOptions.height)/2,
        ]);
        try {
          parts=executeSolidOperation("boolean",target,{booleanMode:"difference"},tool);
        } finally {tool.geometry.dispose();tool.material.dispose();}
      } else {
        parts=executeSolidOperation(solidDialog.kind,target,solidOptions,second);
      }
      if (objects.length-(solidDialog.kind==="primitive"?0:1)-(second?1:0)+parts.length>MAX_OBJECTS)
        throw new Error("The result would exceed the 12-object build plate limit.");
      setSolidPreview({parts,secondId:second ? solidOptions.secondId : null});
    } catch(error) {
      setSolidError(error.message || "The model could not be edited. Original meshes are unchanged.");
    } finally {setSolidBusy(false);}
  }
  async function applySolid() {
    if (!solidDialog || !solidPreview || solidBusy) return;
    const selectedObject=objects.find(row=>row.instance_id===solidDialog.id);
    if (!selectedObject && solidDialog.kind!=="primitive") {
      setSolidError("Selection changed. Reopen the mesh operation.");return;
    }
    setSolidBusy(true);setSolidError("");
    try {
      const created=[];
      for(const [index,part] of solidPreview.parts.entries()) {
        const filename=solidDialog.name.replace(/\.stl$/i,"").slice(0,72) +
          " - " + solidDialog.kind + (solidPreview.parts.length>1?"-"+(index+1):"") + ".stl";
        const file=new File([part.buffer],filename,{type:"model/stl"});
        const form=new FormData();form.append("file",file);
        const result=await apiFetch("/api/printing/slicer/meshes/temporary/",{
          method:"POST",body:form,
        });
        const id=String(result?.asset_id||"");
        if(!id) throw new Error("MakerVault did not return a validated STL identifier.");
        created.push({id,name:filename,file,part});
      }
      const remaining=objects.filter(row=>solidDialog.kind==="primitive" ||
        (row.instance_id!==solidDialog.id && row.instance_id!==solidPreview.secondId));
      const additions=created.map(({id,part},index)=>({
        ...selectedObject,
        ...newPlateInstance(id,objects.length+index),
        x_mm:pretty(part.x_mm),y_mm:pretty(part.y_mm),z_mm:pretty(part.z_mm),
        color:PALETTE[(index+2)%PALETTE.length],
        assembly_id:null,
      }));
      if (solidDialog.kind==="primitive") {
        pendingArrangeRef.current=true;
        additions.forEach(item=>pendingAddIdsRef.current.add(item.instance_id));
        onChange([...remaining,...additions]);
      } else if (solidDialog.kind==="cut" && additions.length>1) {
        const dims={...dimensionsRef.current};
        additions.forEach((item,i)=>{const p=created[i].part;
          dims[item.instance_id]={width:p.width,depth:p.depth,height:p.height};item.z_mm=0;});
        const arranged=autoArrangePlate([...remaining,...additions],dims,bedX,bedY,5);
        if (arranged.error) throw new Error(arranged.error +
          " Use 'Keep top' or 'Keep bottom' to make a smaller result.");
        onChange(arranged.objects);
      } else {
        onChange([...remaining,...additions]);
      }
      onLocalAssetsChange?.(current=>[...current,...created.map(({id,name,file})=>({
        id,category:"mesh",name,filename:name,url:URL.createObjectURL(file),localOnly:true,
      }))]);
      setSelected(additions[0]?.instance_id||"");
      setArrangeNotice(solidDialog.kind+" completed. Source models remain saved; Undo restores this plate.");
      setSolidPreview(null);setSolidDialog(null);
    } catch(error) {
      setSolidError((error.message||"Mesh operation failed.")+" No partial replacement was applied.");
    } finally {setSolidBusy(false);}
  }

  // Preview only: the loaded model stays intact until every replacement STL
  // has passed the same private, server-side validation used by normal imports.
  useEffect(() => {
    if (!splitRequest || !chosen || !canEdit) return undefined;
    const mesh = sceneRef.current?.meshes.get(chosen.instance_id);
    setSplitError("");
    if (!mesh) {
      setSplitError("The selected STL is still loading. Try Split when it appears on the plate.");
      return undefined;
    }
    try {
      const analysis = splitDisconnectedMesh(mesh, MAX_OBJECTS - objects.length + 1);
      if (!analysis.parts.length) {
        setSplitError(analysis.message);
        setSplitPreview(null);
      } else {
        const source = sourceFiles.find(file => String(file.id) === String(chosen.asset_id));
        setSplitPreview({
          id: chosen.instance_id, name: source?.name || source?.filename || "Model",
          parts: analysis.parts,
        });
      }
    } catch (error) {
      setSplitError(error.message || "Could not inspect the selected STL.");
      setSplitPreview(null);
    }
    return undefined;
  }, [splitRequest]);

  // Show split components in independent colours without altering the draft.
  useEffect(() => {
    if (!splitPreview) return undefined;
    const state = sceneRef.current;
    const original = state?.meshes.get(splitPreview.id);
    if (!state || !original) return undefined;
    const overlays = [];
    const oldVisibility = original.visible;
    original.visible = false;
    for (const [index, part] of splitPreview.parts.entries()) {
      const geometry = new STLLoader().parse(part.buffer);
      const ghost = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
        color: PALETTE[index % PALETTE.length], transparent: true,
        opacity: 0.78, depthWrite: true, side: THREE.DoubleSide,
      }));
      ghost.position.set(part.x_mm, part.y_mm, 0);
      ghost.userData.splitPreview = true;
      overlays.push(ghost);
      state.scene.add(ghost);
    }
    return () => {
      original.visible = oldVisibility;
      overlays.forEach(ghost => {
        state.scene.remove(ghost);
        ghost.geometry.dispose();
        ghost.material.dispose();
      });
    };
  }, [splitPreview]);

  async function applySplit() {
    if (!splitPreview || splitBusy || !canEdit) return;
    const selectedObject = objects.find(item => item.instance_id === splitPreview.id);
    if (!selectedObject) {
      setSplitError("The selected object changed. Reopen Split to inspect the current model.");
      return;
    }
    const remaining = objects.filter(item => item.instance_id !== splitPreview.id);
    const drafts = splitPreview.parts.map((part, i) => ({
      ...selectedObject, ...newPlateInstance("pending:" + i, objects.length + i),
      x_mm: pretty(part.x_mm), y_mm: pretty(part.y_mm),
      color: PALETTE[i % PALETTE.length],
    }));
    const knownDimensions = { ...dimensionsRef.current };
    for (const [index, part] of splitPreview.parts.entries()) {
      knownDimensions[drafts[index].instance_id] = {
        width: part.width, depth: part.depth, height: part.height,
      };
    }
    // Arrange before uploading. Never replace the original if all pieces do
    // not fit on the bed together with the remaining objects.
    const packed = autoArrangePlate([...remaining, ...drafts], knownDimensions, bedX, bedY, 5);
    if (packed.error) {
      setSplitError(packed.error + " The original model has not been changed.");
      return;
    }
    setSplitBusy(true);
    setSplitError("");
    const created = [];
    try {
      for (const [index, part] of splitPreview.parts.entries()) {
        const name = splitPreview.name.replace(/\.stl$/i, "").slice(0, 85) +
          " - part " + (index + 1) + ".stl";
        const file = new File([part.buffer], name, { type: "model/stl" });
        const form = new FormData();
        form.append("file", file);
        const result = await apiFetch("/api/printing/slicer/meshes/temporary/", {
          method: "POST", body: form,
        });
        const id = String(result?.asset_id || "");
        if (!id) throw new Error("MakerVault did not return an STL input identifier.");
        created.push({ id, name, file });
      }
      const next = packed.objects.map(item => {
        const index = drafts.findIndex(draft => draft.instance_id === item.instance_id);
        return index === -1 ? item : { ...item, asset_id: created[index].id };
      });
      onLocalAssetsChange?.(current => [...current, ...created.map(part => ({
        id: part.id, category: "mesh", name: part.name, filename: part.name,
        url: URL.createObjectURL(part.file), localOnly: true,
      }))]);
      onChange(next);
      setSelected(drafts[0]?.instance_id || "");
      setArrangeNotice(created.length + " independent objects created and arranged. Use Undo to restore the original assembly.");
      setSplitPreview(null);
    } catch (error) {
      // No plate mutation: any accepted temporary uploads remain private and
      // unreferenced; no partial set of pieces is introduced into the draft.
      setSplitError((error.message || "Split upload failed.") + " The original model was not changed.");
    } finally {
      setSplitBusy(false);
    }
  }

  function transformGroup(dx = 0, dy = 0, angle = 0) {
    if (!canEdit || selection.length < 2) return;
    const members = objects.filter(row => selection.includes(row.instance_id));
    const others = objects.filter(row => !selection.includes(row.instance_id));
    const centerX = members.reduce((sum, row) => sum + Number(row.x_mm), 0) / members.length;
    const centerY = members.reduce((sum, row) => sum + Number(row.y_mm), 0) / members.length;
    const theta = THREE.MathUtils.degToRad(angle), cos = Math.cos(theta), sin = Math.sin(theta);
    const moved = members.map(row => {
      const x = row.x_mm - centerX, y = row.y_mm - centerY;
      return {
        ...row,
        x_mm: pretty(centerX + x * cos - y * sin + dx),
        y_mm: pretty(centerY + x * sin + y * cos + dy),
        rotation_deg: pretty(((Number(row.rotation_deg || 0) + angle + 180) % 360 + 360) % 360 - 180),
      };
    });
    const invalid = moved.some(item => {
      const d = dimensionsRef.current[item.instance_id];
      return !d || plateExtentWarning(item, d, bedX, bedY);
    });
    if (invalid) {
      setError("Group transform would leave the build plate. No changes were applied.");
      return;
    }
    const byId = new Map(moved.map(row => [row.instance_id, row]));
    onChange(objects.map(row => byId.get(row.instance_id) || row));
    setGroupDeltaX(0); setGroupDeltaY(0); setGroupRotation(0);
    setError("");
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
        map: bedTexture, side: THREE.DoubleSide, roughness: 0.97,
        metalness: 0.0,
        polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
      }),
    );
    scene.add(bed);
    // Separate the printable sheet (Z=0) from the *underlying* machine bed.
    // The supporting chassis extends beyond the print surface and has a
    // recessed top: no nearly-coplanar faces or interpenetrating rims.
    const plateDepth = Math.max(5, Math.min(9, Math.min(bedX, bedY) * 0.028));
    const plateBodyGeometry = new THREE.ExtrudeGeometry(plateShape, {
      depth: plateDepth - 2.5,
      bevelEnabled: true, bevelSegments: 3,
      bevelSize: 0.7, bevelThickness: 0.35, curveSegments: 8,
    });
    const plateBody = new THREE.Mesh(plateBodyGeometry, [
      new THREE.MeshStandardMaterial({
        color: "#25313d", metalness: 0.18, roughness: 0.8,
        side: THREE.FrontSide,
      }),
      new THREE.MeshStandardMaterial({
        color: "#18212b", metalness: 0.24, roughness: 0.73,
        side: THREE.FrontSide,
      }),
    ]);
    plateBody.scale.set(1.035, 1.035, 1);
    plateBody.position.z = -plateDepth;
    plateBody.renderOrder = -2;
    scene.add(plateBody);

    // Thin removable print sheet, narrower than its supporting chassis.
    // Its upper face stops 0.6 mm below the textured printable surface.
    const rimGeometry = new THREE.ExtrudeGeometry(plateShape, {
      depth: 1.15,
      bevelEnabled: true,
      bevelSegments: 2, bevelSize: 0.16, bevelThickness: 0.15,
      curveSegments: 8,
    });
    const plateRim = new THREE.Mesh(rimGeometry, [
      new THREE.MeshStandardMaterial({
        color: useMakerVaultBed ? "#3a5365" : "#424b52",
        metalness: 0.3, roughness: 0.77,
      }),
      new THREE.MeshStandardMaterial({
        color: useMakerVaultBed ? "#2b4555" : "#333a42",
        metalness: 0.25, roughness: 0.74,
      }),
    ]);
    plateRim.position.z = -2.1;
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
            !/^\s*(?:<\?xml[^>]*>\s*)?<svg\b/i.test(svgText))
          throw new Error("Official bed artwork must be an SVG.");
        // Keep the upstream vector markings rasterised once onto the same bed.
        const svg = svgText.replace(/<svg\b/i, '<svg width="2048" height="2048"');
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
        if (inside(x, (y + yy) / 2)) target.push(x, y, 0.24, x, yy, 0.24);
      }
    }
    for (let y = -bedY / 2; y <= bedY / 2 + 1e-5; y += step) {
      const isGridLine = Math.abs(y / 10 - Math.round(y / 10)) < 1e-5;
      if (!isGridLine || !drawReferenceGrid) continue;
      const target = Math.abs(y / 50 - Math.round(y / 50)) < 1e-5 ? major : minor;
      for (let x = -bedX / 2; x < bedX / 2; x += step) {
        const xx = Math.min(x + step, bedX / 2);
        if (inside((x + xx) / 2, y)) target.push(x, y, 0.24, xx, y, 0.24);
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
    const rotationGizmo = createMakerVaultRotationGizmo(scene);
    const orientationCube = new SlicerOrientationCube(camera, renderer);
    transform.setSpace("world");
    transform.setTranslationSnap(0.5);
    // Rotation normally settles on 45° detents. Hold Shift for 5° precision.
    transform.setRotationSnap(THREE.MathUtils.degToRad(45));
    const onRotationKeyChange = event => {
      transform.setRotationSnap(THREE.MathUtils.degToRad(event.shiftKey ? 5 : 45));
    };
    window.addEventListener("keydown", onRotationKeyChange);
    window.addEventListener("keyup", onRotationKeyChange);
    const formatAngle = radians => {
      const degrees = THREE.MathUtils.radToDeg(radians);
      return Math.round(degrees * 10) / 10;
    };
    transform.addEventListener("objectChange", () => {
      if (!transform.object || latestToolModeRef.current !== "rotate") return;
      const r = transform.object.rotation;
      setLiveRotation({ x: formatAngle(r.x), y: formatAngle(r.y), z: formatAngle(r.z),
        axis: transform.axis || "" });
    });
    transform.showZ = false;
    scene.add(transform.getHelper());
    transform.addEventListener("dragging-changed", event => {
      controls.enabled = !event.value;
    });

    const meshes = new Map();
    // The helper is owned by the selected instance, never by its STL asset.
    // This keeps two copies of the same model independently selectable and
    // prevents the highlight from changing filament/preview colours.
    let selectionOutline = null;
    function setSelectionOutline(mesh) {
      if (selectionOutline?.userData?.target === mesh) return;
      if (selectionOutline) {
        scene.remove(selectionOutline);
        selectionOutline.geometry.dispose();
        selectionOutline.material.dispose();
        selectionOutline = null;
      }
      if (!mesh) return;
      selectionOutline = new THREE.BoxHelper(mesh, 0x39d9ff);
      selectionOutline.userData.target = mesh;
      selectionOutline.material.depthTest = false;
      selectionOutline.material.transparent = true;
      selectionOutline.material.opacity = 0.96;
      selectionOutline.renderOrder = 90;
      scene.add(selectionOutline);
      selectionOutline.update();
    }
    const measurementOverlay = new THREE.Group();
    scene.add(measurementOverlay);
    const raycaster = new THREE.Raycaster();
    const bedPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    let dragging = null;
    let rotationPointerId = null;
    let lastRotationPreview = null;

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
      // Direct hit testing against MakerVault's larger rotation handles
      // happens before ordinary model selection and plate dragging.
      if (latestToolModeRef.current === "rotate" && rotationGizmo.group.visible) {
        const axis = rotationGizmo.pick(raycaster.ray);
        if (axis && rotationGizmo.begin(axis, raycaster.ray)) {
          rotationPointerId = event.pointerId;
          lastRotationPreview = null;
          controls.enabled = false;
          renderer.domElement.setPointerCapture?.(event.pointerId);
          event.preventDefault();
          event.stopPropagation();
          return;
        }
      }
      const hits = raycaster.intersectObjects([...meshes.values()], false);
      if (latestMeasurementRef.current.active) {
        if (!hits.length) return;
        const hit = hits[0];
        const target = hit.object;
        if (latestMeasurementRef.current.mode === "detect") {
          const tolerance = Math.min(2.5, Math.max(0.2,
            hit.distance * 6 / Math.max(320, renderer.domElement.clientHeight)));
          const result = detectMeshMeasurement(target, hit, tolerance);
          setSelected(target.userData.instanceId);
          setMeasurePoints([]);
          setDetectedFeature(result);
          measurePinPlacedRef.current?.();
          event.preventDefault();
          return;
        }
        setDetectedFeature(null);
        const world = hit.point.clone();
        let snap = "Surface";
        let edgeLength = null;
        // STL is triangulated, so prefer a nearby real triangle vertex or
        // straight mesh edge. Never claim that an arbitrary triangle is a
        // recognised CAD circle or a fitted cylinder.
        if (hit.face && latestMeasurementRef.current.snapMode !== "surface") {
          const position = target.geometry.getAttribute("position");
          if (position) {
            target.updateMatrixWorld(true);
            const vertices = [hit.face.a, hit.face.b, hit.face.c].map(index =>
              new THREE.Vector3().fromBufferAttribute(position, index)
                .applyMatrix4(target.matrixWorld));
            const closestVertex = vertices.reduce((best, point) =>
              point.distanceTo(hit.point) < best.distanceTo(hit.point) ? point : best,
            vertices[0]);
            const vertexDistance = closestVertex.distanceTo(hit.point);
            const tolerance = Math.min(2, Math.max(0.15, hit.distance * 5 / Math.max(320, renderer.domElement.clientHeight)));
            if (latestMeasurementRef.current.snapMode !== "edge" && vertexDistance <= tolerance) {
              world.copy(closestVertex);
              snap = "Vertex";
            } else {
              let bestEdge = null, distance = Infinity, bestEdgeLength = null;
              for (let i = 0; i < 3; i++) {
                const a = vertices[i], b = vertices[(i + 1) % 3];
                const point = new THREE.Line3(a, b).closestPointToPoint(hit.point, true,
                  new THREE.Vector3());
                const candidate = point.distanceTo(hit.point);
                if (candidate < distance) {
                  distance = candidate;
                  bestEdge = point;
                  bestEdgeLength = a.distanceTo(b);
                }
              }
              if (latestMeasurementRef.current.snapMode !== "vertex" && distance <= tolerance && bestEdge) {
                world.copy(bestEdge);
                snap = "Triangle edge";
                edgeLength = bestEdgeLength;
              }
            }
          }
        }
        const pin = { point: [world.x, world.y, world.z],
          instanceId: target.userData.instanceId, snap, edgeLength };
        setSelected(target.userData.instanceId);
        measurePinPlacedRef.current?.();
        setMeasurePoints(current => {
          const max = latestMeasurementRef.current.mode === "circle" ? 3 : 2;
          return current.length >= max ? [pin] : [...current, pin];
        });
        event.preventDefault();
        return;
      }
      if (!hits.length) {
        setSelected("");
        exitToolModeRef.current?.();
        return;
      }
      const target = hits[0].object;
      if (latestToolModeRef.current === "lay_face") {
        const hit = hits[0];
        const current = latestObjectsRef.current;
        const selectedItem = current.find(item => item.instance_id === target.userData.instanceId);
        if (!selectedItem || !hit.face) return;
        target.updateMatrixWorld(true);
        const normal = hit.face.normal.clone().applyNormalMatrix(
          new THREE.Matrix3().getNormalMatrix(target.matrixWorld)).normalize();
        if (normal.lengthSq() < 0.9) return;
        const align = new THREE.Quaternion().setFromUnitVectors(normal,
          new THREE.Vector3(0, 0, -1));
        const orientation = new THREE.Euler().setFromQuaternion(
          align.multiply(target.quaternion), "XYZ");
        const candidate = {
          ...selectedItem,
          rotation_xyz_deg: [orientation.x, orientation.y].map(v =>
            Math.round(THREE.MathUtils.radToDeg(v) * 1000) / 1000),
          rotation_deg: Math.round(THREE.MathUtils.radToDeg(orientation.z) * 1000) / 1000,
        };
        setSelected(selectedItem.instance_id);
        if (!validPlacement(candidate, current)) {
          setError("That face orientation exceeds the plate or overlaps another model. Move or auto-arrange models and try again.");
          return;
        }
        setError("");
        latestOnChangeRef.current(current.map(item =>
          item.instance_id === selectedItem.instance_id ? candidate : item));
        exitToolModeRef.current?.();
        event.preventDefault();
        return;
      }
      const location = new THREE.Vector3();
      if (!raycaster.ray.intersectPlane(bedPlane, location)) return;
      const id = target.userData.instanceId;
      const additive = event.ctrlKey || event.metaKey || event.shiftKey;
      if (onSelectModelRef.current) onSelectModelRef.current(id, additive);
      else setSelected(id);
      if (additive || selectionRef.current.length > 1) return;
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
      if (rotationPointerId === event.pointerId && rotationGizmo.dragging) {
        rayFromPointer(event);
        const angle = rotationGizmo.drag(raycaster.ray, event.shiftKey, event.timeStamp);
        if (angle && (lastRotationPreview !== angle.delta || event.shiftKey)) {
          lastRotationPreview = angle.delta;
          // Re-seat the preview mesh on Z=0 as it tilts. The STL and saved
          // instance remain untouched until pointer-up passes placement checks.
          const mesh = rotationGizmo.activeMesh;
          const model = latestObjectsRef.current.find(row =>
            row.instance_id === mesh?.userData.instanceId);
          if (mesh && model) positionOrientedMesh(mesh, {
            ...model, rotation_xyz_deg: [angle.x, angle.y], rotation_deg: angle.z,
          });
          setLiveRotation(angle);
        }
        event.preventDefault();
        return;
      }
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
      if (rotationPointerId === event.pointerId) {
        const cancelled = event.type === "pointercancel";
        rotationPointerId = null;
        lastRotationPreview = null;
        const operation = rotationGizmo.end();
        controls.enabled = true;
        setLiveRotation(null);
        if (renderer.domElement.hasPointerCapture?.(event.pointerId))
          renderer.domElement.releasePointerCapture(event.pointerId);
        if (operation?.mesh) {
          const mesh = operation.mesh;
          const current = latestObjectsRef.current;
          const original = current.find(item => item.instance_id === mesh.userData.instanceId);
          if (original) {
            if (cancelled) {
              positionOrientedMesh(mesh, original);
              rotationGizmo.update(mesh);
              return;
            }
            const candidate = {
              ...original,
              rotation_xyz_deg: [mesh.rotation.x, mesh.rotation.y].map(value =>
                Math.round(THREE.MathUtils.radToDeg(value) * 1000) / 1000),
              rotation_deg: Math.round(THREE.MathUtils.radToDeg(mesh.rotation.z) * 1000) / 1000,
            };
            if (!validPlacement(candidate, current)) {
              positionOrientedMesh(mesh, original);
              setError("Rotation would extend past the build plate or overlap another object. The original orientation was restored.");
            } else {
              setError("");
              latestOnChangeRef.current(current.map(item =>
                item.instance_id === original.instance_id ? candidate : item));
            }
          }
        }
        rotationGizmo.update(operation?.mesh);
        event.preventDefault();
        return;
      }
      if (!dragging || dragging.pointerId !== event.pointerId) return;
      dragging = null;
      controls.enabled = true;
      if (renderer.domElement.hasPointerCapture?.(event.pointerId)) {
        renderer.domElement.releasePointerCapture(event.pointerId);
      }
    }
    transform.addEventListener("mouseUp", () => {
      setLiveRotation(null);
      const mesh = transform.object;
      if (!mesh) return;
      const current = latestObjectsRef.current;
      const selectedItem = current.find(item => item.instance_id === mesh.userData.instanceId);
      if (!selectedItem) return;
      const candidate = { ...selectedItem,
        x_mm: Math.round(mesh.position.x * 2) / 2,
        y_mm: Math.round(mesh.position.y * 2) / 2,
        z_mm: Math.max(0, pretty(mesh.position.z - (mesh.userData.bedZOffset || 0))),
        rotation_deg: Math.round(THREE.MathUtils.radToDeg(mesh.rotation.z) * 1000) / 1000,
        rotation_xyz_deg: [mesh.rotation.x, mesh.rotation.y].map(v =>
          Math.round(THREE.MathUtils.radToDeg(v) * 1000) / 1000),
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
        positionOrientedMesh(mesh, selectedItem);
        setError("Move rejected: model is unsupported, intersects another model or exceeds the plate.");
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
    const cancelRotationOnEscape = event => {
      if (event.key === "Escape" && rotationPointerId !== null) {
        pointerUp({ type: "pointercancel", pointerId: rotationPointerId,
          preventDefault: () => {} });
        event.preventDefault();
      }
    };
    window.addEventListener("keydown", cancelRotationOnEscape);
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
    // Both the generated bed and an optional native decorative STL must
    // become translucent beneath the surface. Changing only the print sheet
    // leaves the opaque chassis in front of the model from underneath.
    let lastBedAppearance = "";
    const updateBedAppearance = () => {
      const mode = undersidePlateModeRef.current;
      const translucent = mode === "transparent" ||
        (mode === "auto" && camera.position.z < -0.5);
      const key = mode + ":" + translucent + ":" + Boolean(nativeBedMesh);
      if (key === lastBedAppearance) return;
      lastBedAppearance = key;
      const setMaterial = (material, opacity) => {
        material.transparent = translucent;
        material.opacity = translucent ? opacity : 1;
        material.depthWrite = !translucent;
        material.needsUpdate = true;
      };
      const setMaterials = (mesh, opacity) => {
        for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material])
          setMaterial(material, opacity);
      };
      setMaterials(bed, 0.22);
      setMaterials(plateBody, 0.12);
      setMaterials(plateRim, 0.18);
      if (nativeBedMesh) setMaterials(nativeBedMesh, 0.12);
      // Reference grid and labels must not obscure the underside model.
      for (const line of gridLines) line.visible = !translucent;
      for (const mark of markings) mark.visible = !translucent;
      boundary.visible = !translucent;
    };
    renderer.setAnimationLoop(() => {
      controls.update();
      updateBedAppearance();
      // Update continuously during gizmo and pointer drags, which can happen
      // between React object-state commits.
      selectionOutline?.update();
      renderer.render(scene, camera);
      orientationCube.render();
    });
    sceneRef.current = { scene, meshes, transform, rotationGizmo, camera, controls, bedX, bedY,
      measurementOverlay, setSelectionOutline };
    return () => {
      disposed = true;
      sceneRef.current = null;
      observer.disconnect();
      window.removeEventListener("keydown", cancelRotationOnEscape);
      renderer.domElement.removeEventListener("pointerdown", orientationPointerDown, true);
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointermove", pointerMove);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      renderer.domElement.removeEventListener("pointercancel", pointerUp);
      renderer.setAnimationLoop(null);
      window.removeEventListener("keydown", onRotationKeyChange);
      window.removeEventListener("keyup", onRotationKeyChange);
      controls.dispose();
      orientationCube.dispose();
      transform.detach();
      scene.remove(transform.getHelper());
      transform.dispose();
      rotationGizmo.dispose();
      setSelectionOutline(null);
      for (const item of [...measurementOverlay.children]) {
        measurementOverlay.remove(item);
        item.geometry?.dispose();
        item.material?.map?.dispose();
        item.material?.dispose();
      }
      scene.remove(measurementOverlay);
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
      plateRim.material.forEach(material => material.dispose());
      plateBody.geometry.dispose();
      plateBody.material.forEach(material => material.dispose());
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
            height: box.max.z - box.min.z,
          } }));
          const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
            color: item.color || PALETTE[0], roughness: 0.72, metalness: 0.04, side: THREE.DoubleSide,
          }));
          mesh.userData.instanceId = item.instance_id;
          const latest = latestObjectsRef.current.find(row => row.instance_id === item.instance_id) || item;
          positionOrientedMesh(mesh, latest);
          state.meshes.set(item.instance_id, mesh);
          state.scene.add(mesh);
          if (latestToolModeRef.current !== "select" && item.instance_id === selectedInstanceId &&
              ["move", "scale"].includes(latestToolModeRef.current)) {
            state.transform.setMode(latestToolModeRef.current === "move" ? "translate" : "scale");
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
      positionOrientedMesh(mesh, item);
      // Position-only changes must never alter the displayed filament colour.
      mesh.material.color.set(item.color || PALETTE[0]);
      mesh.material.emissive.set(conflictIds.has(item.instance_id) ? "#e84a53" :
        selection.includes(item.instance_id) ? "#168ab4" : "#000000");
      mesh.material.emissiveIntensity = conflictIds.has(item.instance_id) ? 0.72 :
        selection.includes(item.instance_id) ? 0.32 : 0;
    }
    const selectedMesh = state.meshes.get(selected);
    state.setSelectionOutline(selectedMesh || null);
    const singleEditable = canEdit && selectedMesh && selection.length < 2;
    if (singleEditable && toolMode === "rotate") {
      state.transform.detach();
      state.rotationGizmo?.update(selectedMesh);
    } else {
      state.rotationGizmo?.update(null);
      if (singleEditable && (toolMode === "move" || toolMode === "scale")) {
        state.transform.setMode(toolMode === "move" ? "translate" : "scale");
        state.transform.showX = true;
        state.transform.showY = true;
        state.transform.showZ = toolMode === "move" || toolMode === "scale";
        state.transform.setSpace("world");
        state.transform.setSize(1);
        state.transform.attach(selectedMesh);
      } else {
        state.transform.detach();
      }
    }
  }, [objects, selected, selectedInstanceIds, toolMode, canEdit, dimensions, issueKey]);

  // Measured world points would become stale after a model is transformed.
  // Clear them rather than presenting a measurement for old geometry.
  useEffect(() => { setMeasurePoints([]); setDetectedFeature(null); }, [objects, measureMode, measureClearVersion]);
  useEffect(() => {
    if (!measurementVisible) { setMeasurePoints([]); setDetectedFeature(null); }
  }, [measurementVisible]);
  useEffect(() => {
    const state = sceneRef.current;
    if (!state?.measurementOverlay) return;
    const overlay = state.measurementOverlay;
    for (const item of [...overlay.children]) {
      overlay.remove(item);
      item.geometry?.dispose();
      item.material?.map?.dispose();
      item.material?.dispose();
    }
    if (!measurementVisible) return;
    const points = measurePoints.map(pin => new THREE.Vector3(...pin.point));
    if (detectedFeature?.point && detectedFeature?.value != null) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(1.65, 10, 8),
        new THREE.MeshBasicMaterial({ color: "#facc15", depthTest: false }));
      marker.position.set(...detectedFeature.point);
      marker.renderOrder = 101;
      overlay.add(marker);
      if (detectedFeature.kind === "face" && detectedFeature.highlightPositions?.length >= 9) {
        // A temporary overlay made from the very triangles contributing to the
        // measured area. It does not alter the STL or printable object colour.
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position",
          new THREE.Float32BufferAttribute(detectedFeature.highlightPositions, 3));
        geometry.computeVertexNormals();
        const material = new THREE.MeshBasicMaterial({
          color: "#facc15", side: THREE.DoubleSide, transparent: true,
          opacity: 0.38, depthTest: true, depthWrite: false,
          polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
        });
        const highlight = new THREE.Mesh(geometry, material);
        highlight.renderOrder = 95;
        overlay.add(highlight);
      }
      if (detectedFeature.kind === "edge" && detectedFeature.start && detectedFeature.end) {
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(...detectedFeature.start),
          new THREE.Vector3(...detectedFeature.end),
        ]), new THREE.LineBasicMaterial({ color: "#facc15", depthTest: false }));
        line.renderOrder = 100;
        overlay.add(line);
      }
    }
    for (const point of points) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(1.65, 10, 8),
        new THREE.MeshBasicMaterial({ color: "#facc15", depthTest: false }));
      marker.position.copy(point);
      marker.renderOrder = 101;
      overlay.add(marker);
    }
    if (points.length >= 2) {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: "#facc15", depthTest: false }));
      line.renderOrder = 100;
      overlay.add(line);
    }
    // Label completed measurements in 3D rather than forcing the user to read
    // the details panel. Labels are display-only and never exported to STL/G-code.
    const distance = points.length === 2 && measureMode === "distance"
      ? measurementDistance(measurePoints[0].point, measurePoints[1].point) : null;
    const circle = points.length === 3 && measureMode === "circle"
      ? measurementCircle(...measurePoints.map(pin => pin.point)) : null;
    const caption = detectedFeature?.value != null
      ? formatDetectedMeasurement(detectedFeature, measureUnit)
      : distance !== null ? measurementFormat(distance, measureUnit)
      : circle ? "Ø " + measurementFormat(circle.diameter, measureUnit) : "";
    if (caption) {
      const canvas = document.createElement("canvas");
      canvas.width = 512; canvas.height = 96;
      const context = canvas.getContext("2d");
      if (context) {
        context.fillStyle = "rgba(10, 23, 37, 0.9)";
        context.fillRect(0, 0, 512, 96);
        context.font = "bold 38px sans-serif";
        context.fillStyle = "#fff5b5";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(caption, 256, 48, 490);
        const texture = new THREE.CanvasTexture(canvas);
        const label = new THREE.Sprite(new THREE.SpriteMaterial({
          map: texture, depthTest: false, transparent: true,
        }));
        const labelPoints = detectedFeature?.point && detectedFeature?.value != null
          ? [new THREE.Vector3(...detectedFeature.point)] : points;
        const middle = labelPoints.reduce((result, point) => result.add(point),
          new THREE.Vector3()).divideScalar(labelPoints.length);
        label.position.copy(middle).add(new THREE.Vector3(0, 0, 5));
        label.scale.set(37, 7, 1);
        label.renderOrder = 102;
        overlay.add(label);
      }
    }
  }, [measurePoints, detectedFeature, measurementVisible, measureUnit, measureMode]);

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
    <div className="slicerPlateWorkspace">
      <div className="slicerPlateCanvasColumn">
    {toolbar && <div className="slicerPlateEditingToolbar">{toolbar}</div>}
    <div className="slicerPlateCameraToolbar" role="toolbar" aria-label="Build-plate camera views">
      <button type="button" onClick={() => setPlateCamera("iso")} title="Isometric build-plate view">Isometric</button>
      <button type="button" onClick={() => setPlateCamera("top")} title="Top-down build-plate view">Top</button>
      <button type="button" onClick={() => setPlateCamera("front")} title="View the front of the printer build plate">Front</button>
      <button type="button" onClick={() => setPlateCamera("right")} title="View the right side of the printer build plate">Right</button>
      <button data-slicer-action="focus" type="button" onClick={() => setPlateCamera("selection")} disabled={!chosen}
        title="Centre and zoom onto the currently selected model">Fit selected model</button>

    </div>
    <div className="slicerPlateCanvasViewport">
      <div ref={hostRef} className="slicerPlateCanvas"
        aria-label="Interactive three-dimensional model plate preview with a clickable six-face orientation cube in the top right" />
      {selection.length > 1 && <aside className="slicerViewportMeasurement slicerViewportTransform"
        aria-label="Multi-model assembly controls">
        <div className="slicerViewportMeasurementHeader"><strong>{selection.length} models selected</strong></div>
        <p className="slicerViewportMeasurementHint">Move or rotate the selected models together.
          Each part keeps its original mesh and relative offset.</p>
        <div className="slicerViewportTransformGrid">
          <label>Move X (mm)<input type="number" step="0.5" value={groupDeltaX}
            onChange={event => setGroupDeltaX(Number(event.target.value))} /></label>
          <label>Move Y (mm)<input type="number" step="0.5" value={groupDeltaY}
            onChange={event => setGroupDeltaY(Number(event.target.value))} /></label>
          <label>Rotate Z (°)<input type="number" step="5" value={groupRotation}
            onChange={event => setGroupRotation(Number(event.target.value))} /></label>
        </div>
        <button type="button" disabled={!canEdit || ![groupDeltaX, groupDeltaY, groupRotation].every(Number.isFinite)}
          onClick={() => transformGroup(groupDeltaX, groupDeltaY, groupRotation)}>Apply group transform</button>
      </aside>}
      {selection.length <= 1 && ["move", "rotate", "scale"].includes(toolMode) && chosen && <aside
        className="slicerViewportMeasurement slicerViewportTransform"
        aria-label={toolMode === "move" ? "On-plate position controls" : toolMode === "rotate" ? "On-plate rotation controls" : "On-plate scale controls"}>
        <div className="slicerViewportMeasurementHeader">
          <strong>{toolMode === "move" ? "Move · mm" : toolMode === "rotate" ? "Rotate · degrees" : "Scale · %"}</strong>
          {toolMode !== "move" && <button type="button" aria-expanded={transformOverlayExpanded}
            onClick={() => setTransformOverlayExpanded(open => !open)}>
            {transformOverlayExpanded ? "Less" : "Details"}
          </button>}
        </div>
        <div className="slicerViewportMeasurementModel">{sourceFiles.find(file =>
          String(file.id) === String(chosen.asset_id))?.name || "Selected model"}</div>
        {toolMode === "move" ? <>
          <div className="slicerViewportTransformGrid">
            {["X", "Y", "Z"].map((axis, index) => <label key={axis}>{axis} (mm)
              <input type="number" step="0.5" min={index === 2 ? 0 : -10000}
                max={index === 2 ? 1000 : 10000}
                value={index === 0 ? chosen.x_mm : index === 1 ? chosen.y_mm :
                  pretty(Number(chosen.z_mm || 0) + (selectedMeasurement?.height || 0) / 2)}
                disabled={!canEdit} onChange={event => {
                  const number = Number(event.target.value);
                  if (!Number.isFinite(number)) return;
                  if (index < 2) patch(index === 0 ? "x_mm" : "y_mm", number);
                  else patch("z_mm", pretty(number - (selectedMeasurement?.height || 0) / 2));
                }} /></label>)}
          </div>
          <button type="button" className="slicerTransformQuickAction" disabled={!canEdit}
            onClick={() => applySelectedTransform({ x_mm: 0, y_mm: 0 },
              "The model cannot be centred without leaving the bed or overlapping another model.")}>
            <SlicerUiIcon name="center" /> <span>Centre model</span>
          </button>
        </> : toolMode === "rotate" ? <>
          <div className="slicerViewportTransformGrid">
            {["X", "Y", "Z"].map((axis, index) => <label key={axis}>{axis} (°)
              <input type="number" step="5" value={liveRotation
                ? [liveRotation.x, liveRotation.y, liveRotation.z][index]
                : index === 2 ? chosen.rotation_deg : chosen.rotation_xyz_deg?.[index] || 0} disabled={!canEdit}
                onChange={event => {
                  const next = Number(event.target.value);
                  if (!Number.isFinite(next)) return;
                  if (index === 2) patch("rotation_deg", next);
                  else {
                    const rotations = [...(chosen.rotation_xyz_deg || [0, 0])];
                    rotations[index] = next;
                    patch("rotation_xyz_deg", rotations);
                  }
                }} /></label>)}
          </div>
          {liveRotation && <div className="slicerTransformDragAngle" role="status" aria-live="off">
            {liveRotation.axis || "Rotation"} · X {liveRotation.x}° · Y {liveRotation.y}° · Z {liveRotation.z}°
          </div>}
          <button type="button" className="slicerTransformQuickAction" disabled={!canEdit}
            onClick={() => applySelectedTransform({
              rotation_deg: 0, rotation_xyz_deg: [0, 0],
            }, "Reset rotation would collide with another model or leave the plate.")}>
            <SlicerUiIcon name="rotate" /> <span>Reset rotation</span>
          </button>
          {transformOverlayExpanded && <small className="slicerViewportMeasurementHint">
            Drag a coloured ring or its labelled grip to rotate about X, Y or Z. Major marks show 45° detents; move slowly for 1° precision or move quickly for 5°/45° detents. Shift holds 1° precision.
          </small>}
        </> : <>
          <label className="slicerViewportScaleUniform">Uniform scale (%)
            <input type="number" min="5" max="400" step="5"
              value={chosen.scale_percent ?? 100} disabled={!canEdit}
              onChange={event => {
                const value = Number(event.target.value);
                if (!Number.isFinite(value) || value < 5 || value > 400) return;
                applySelectedTransform({
                  scale_percent: value, scale_xyz_percent: [value, value, value],
                }, "Scaling uniformly would overlap another model or leave the build plate.");
              }} />
          </label>
          <div className="slicerViewportTransformGrid">
            {["X", "Y", "Z"].map((axis, index) => <label key={axis}>{axis} (%)
              <input type="number" min="5" max="400" step="1"
                value={chosen.scale_xyz_percent?.[index] ?? chosen.scale_percent ?? 100}
                disabled={!canEdit} onChange={event => {
                  const value = Number(event.target.value);
                  if (!Number.isFinite(value) || value < 5 || value > 400) return;
                  const next = [...(chosen.scale_xyz_percent || [chosen.scale_percent, chosen.scale_percent, chosen.scale_percent])];
                  next[index] = value;
                  patch("scale_xyz_percent", next);
                }} /></label>)}
          </div>
          <button type="button" className="slicerTransformQuickAction" disabled={!canEdit}
            onClick={() => applySelectedTransform({
              scale_percent: 100, scale_xyz_percent: [100, 100, 100],
            }, "Resetting scale would overlap another object or leave the plate.")}>
            <SlicerUiIcon name="scale" /> <span>Reset scale</span>
          </button>
          {transformOverlayExpanded && <small className="slicerViewportMeasurementHint">
            Change all dimensions together with uniform scale, or edit X, Y and Z separately.
            Scale is restricted to 5–400% per axis.
          </small>}
        </>}
      </aside>}
      {selection.length <= 1 && measurementVisible && chosen && <aside className="slicerViewportMeasurement" aria-label="On-plate measurements">
        <div className="slicerViewportMeasurementHeader">
          <strong>Measure · {measureUnit === "mm" ? "mm" : "in"}</strong>
          <button type="button" aria-expanded={measureOverlayExpanded}
            onClick={() => setMeasureOverlayExpanded(current => !current)}>
            {measureOverlayExpanded ? "Less" : "Details"}
          </button>
        </div>
        <div className="slicerViewportMeasurementModel" title={
          sourceFiles.find(file => String(file.id) === String(chosen.asset_id))?.name || "Selected model"
        }>
          {sourceFiles.find(file => String(file.id) === String(chosen.asset_id))?.name || "Selected model"}
        </div>
        {selectedMeasurement ? <div className="slicerViewportMeasurementDimensions">
          <span>X {measurementFormat(selectedMeasurement.width, measureUnit)}</span>
          <span>Y {measurementFormat(selectedMeasurement.depth, measureUnit)}</span>
          <span>Z {measurementFormat(selectedMeasurement.height, measureUnit)}</span>
        </div> : <small>Loading STL dimensions…</small>}
        <div className="slicerViewportMeasurementReadout" role="status" aria-live="polite">
          {measureMode === "detect" && (detectedFeature ? <div>
            <strong>{detectedFeature.label}</strong>
            {detectedFeature.value != null && <span>{formatDetectedMeasurement(detectedFeature, measureUnit)}</span>}
            {detectedFeature.triangles != null && <span>{detectedFeature.triangles} connected triangles</span>}
          </div> : <span>Click an edge or planar face to inspect it</span>)}
          {pinDistance !== null ? <strong>Distance: {measurementFormat(pinDistance, measureUnit)}</strong>
            : measureMode === "distance" ? <span>{measurePoints.length}/2 distance pins</span> : null}
          {measureMode === "circle" && (pinCircle ?
            <div><strong>Ø {measurementFormat(pinCircle.diameter, measureUnit)}</strong>
              <span>Radius {measurementFormat(pinCircle.radius, measureUnit)}</span>
              <span>Circumference {measurementFormat(pinCircle.circumference, measureUnit)}</span>
            </div> : <span>{measurePoints.length}/3 circle pins
              {measurePoints.length === 3 ? " · Collinear points" : ""}</span>)}
        </div>
        {measureOverlayExpanded && <>
          {selectedMeasurement && <div className="slicerViewportMeasurementBounds">
            <span>X: {measurementFormat(selectedMeasurement.minX, measureUnit)} to {measurementFormat(selectedMeasurement.maxX, measureUnit)}</span>
            <span>Y: {measurementFormat(selectedMeasurement.minY, measureUnit)} to {measurementFormat(selectedMeasurement.maxY, measureUnit)}</span>
          </div>}
          {measurePoints.map((pin, index) => <div className="slicerViewportMeasurementPin" key={index}>
            {index + 1}. {pin.snap} · X {measurementFormat(pin.point[0], measureUnit)},
            Y {measurementFormat(pin.point[1], measureUnit)},
            Z {measurementFormat(pin.point[2], measureUnit)}
            {pin.edgeLength != null && <> · Edge {measurementFormat(pin.edgeLength, measureUnit)}</>}
          </div>)}
        </>}
        <small className="slicerViewportMeasurementHint">
          {measureMode === "detect" ? "Click a mesh edge or face to detect a measurable feature" :
            <>Click the model to {measureMode === "circle" ? "set three circle points" : "place two pins"}</>}.
          Options are in the Measure toolbar.
        </small>
      </aside>}
    </div>

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
      <label className="slicerBedVisibilityControl">Build plate
        <select aria-label="Build plate visibility" value={undersidePlateMode}
          onChange={event => setUndersidePlateMode(event.target.value)}>
          <option value="auto">Auto (see through from below)</option>
          <option value="opaque">Always opaque</option>
          <option value="transparent">Always transparent</option>
        </select>
      </label>
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
      Separate the highlighted models before slicing. Saving a draft remains available.
    </div>}

    {objects.length > 0 && <p role="status" className="slicerPlateHint">{objects.length} model{objects.length === 1 ? "" : "s"} on the plate
      {plateIssues.length ? " · Draft can be saved; slicing blocked until conflicts are fixed." : " · Plate ready to save as a draft or slice."}</p>}

      </div>
      <aside className="slicerPlateControls" aria-label="Build plate controls">
        <div className="slicerPlateControlsGroup" data-slicer-add-models>
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

    {measurementVisible && chosen && <section className="slicerPlateMeasurement" role="region"
      aria-label="Selected model measurements">
      <h5>Measure geometry</h5>
      <p className="slicerPlateHint">Choose measurement mode, units and Clear pins from the expandable
        Measure toolbar above the plate. A compact live readout is also shown at the top-left of the viewport.</p>
      <p className="slicerPlateHint">{measureMode === "detect"
        ? "Click near a sharp mesh edge or on a connected planar patch to measure it. Complex curved and densely triangulated meshes may not expose a clear feature."
        : <>Click {measureMode === "circle" ? "three" : "two"} places on a model surface to drop measurement pins.
          Snapping follows the toolbar selection and refers to STL triangle geometry, not original CAD edges.
          Orbit the model to reach other faces. Clicking again after completion starts a new measurement.</>}</p>
      {measureMode === "detect" && detectedFeature && <div role="status" className="slicerMeasurementResult">
        <strong>{detectedFeature.label}</strong>
        {detectedFeature.value != null && <p>{formatDetectedMeasurement(detectedFeature, measureUnit)}</p>}
        <small>Mesh-based estimate, not a CAD feature or a certified dimension.</small>
      </div>}
      {measurePoints.length > 0 && <div role="status" className="slicerMeasurementResult">
        {measurePoints.map((pin, index) => <div key={index}>
          Pin {index + 1} · {pin.snap} · X {measurementFormat(pin.point[0], measureUnit)},
          Y {measurementFormat(pin.point[1], measureUnit)},
          Z {measurementFormat(pin.point[2], measureUnit)}
          {pin.edgeLength != null && <small> · Triangle segment length: {measurementFormat(pin.edgeLength, measureUnit)}</small>}
        </div>)}
        {pinDistance !== null && <strong>3D distance: {measurementFormat(pinDistance, measureUnit)}</strong>}
        {measureMode === "circle" && measurePoints.length === 3 &&
          (pinCircle ? <div><strong>Circle diameter: {measurementFormat(pinCircle.diameter, measureUnit)}</strong>
            <span> · Radius: {measurementFormat(pinCircle.radius, measureUnit)}</span>
            <span> · Circumference: {measurementFormat(pinCircle.circumference, measureUnit)}</span>
          </div> : <div>Three collinear or nearly coincident points cannot define a circle.</div>)}
      </div>}
      {measureMode === "circle" && <p className="slicerPlateHint">
        Three-point circle is a geometric construction, not automatic detection of a
        true circular hole or cylindrical face in a triangulated STL.
      </p>}
      <h5>Selected model bounding box</h5>
      {selectedMeasurement ? <>
        <dl className="slicerMeasurementGrid">
          <div><dt>X envelope</dt><dd>{measurementFormat(selectedMeasurement.width, measureUnit)}</dd></div>
          <div><dt>Y envelope</dt><dd>{measurementFormat(selectedMeasurement.depth, measureUnit)}</dd></div>
          <div><dt>Model height</dt><dd>{measurementFormat(selectedMeasurement.height, measureUnit)}</dd></div>
          <div><dt>Centre X / Y</dt><dd>{measurementFormat(chosen.x_mm, measureUnit)} / {measurementFormat(chosen.y_mm, measureUnit)}</dd></div>
          <div><dt>X bounds</dt><dd>{measurementFormat(selectedMeasurement.minX, measureUnit)} to {measurementFormat(selectedMeasurement.maxX, measureUnit)}</dd></div>
          <div><dt>Y bounds</dt><dd>{measurementFormat(selectedMeasurement.minY, measureUnit)} to {measurementFormat(selectedMeasurement.maxY, measureUnit)}</dd></div>
        </dl>
        <p className="slicerPlateHint">Read-only STL bounding-box estimate, accounting for X/Y/Z scaling and Z rotation.
          X/Y are relative to the plate centre. This is not face-to-face measurement,
          the exact occupied outline, or a print-clearance certification.</p>
      </> : <p role="status">Measuring the selected STL preview…</p>}
    </section>}

    {solidDialog && createPortal(
      <div className="slicerAutoOrientModalBackdrop" role="presentation"
        onMouseDown={event=>{if(event.target===event.currentTarget&&!solidBusy){
          setSolidPreview(null);setSolidDialog(null);
        }}}>
        <section className="slicerAutoOrientPanel slicerAutoOrientModal slicerSolidModal"
          role="dialog" aria-modal="true" aria-label={solidDialog.kind+" model geometry"}>
          <header className="slicerAutoOrientModalHeader">
            <div><h3>{solidDialog.kind==="boolean"?"Mesh Boolean":
              solidDialog.kind[0].toUpperCase()+solidDialog.kind.slice(1)} model</h3>
              <p className="slicerPlateHint">{solidDialog.name}</p></div>
            <button type="button" disabled={solidBusy} aria-label="Close mesh editor"
              onClick={()=>{setSolidPreview(null);setSolidDialog(null);}}>✕</button>
          </header>
          {["primitive","negative"].includes(solidDialog.kind) && <>
            <label>Shape
              <select value={solidOptions.primitiveType} onChange={event=>
                setSolidOptions(v=>({...v,primitiveType:event.target.value}))}>
                {PRIMITIVE_TYPES.map(type=><option key={type} value={type}>
                  {type[0].toUpperCase()+type.slice(1)}</option>)}
              </select></label>
            <div className="slicerSolidGrid">
              {["width","depth","height"].map((field,index)=><label key={field}>
                {["Width X","Depth Y","Height Z"][index]} (mm)
                <input type="number" min="0.5" max="500" step="0.5"
                  value={solidOptions[field]} onChange={event=>
                    setSolidOptions(v=>({...v,[field]:event.target.value}))}/></label>)}
            </div>
            {solidDialog.kind==="negative" && <>
              <div className="slicerSolidGrid">
                {["x_mm","y_mm","z_mm"].map((field,index)=><label key={field}>
                  {["X centre","Y centre","Z centre"][index]} (mm)
                  <input type="number" step="0.5" value={solidOptions[field]}
                    onChange={event=>setSolidOptions(v=>({...v,[field]:event.target.value}))}/></label>)}
              </div>
              <p className="slicerPlateHint">Subtract this shape from the selected model.
                The original stays intact until the result has been previewed and validated.
                This changes mesh geometry, not native print settings.</p>
            </>}
            {solidDialog.kind==="primitive" && <p className="slicerPlateHint">
              Creates a real STL primitive, then automatically arranges it on the plate.
              Move, rotate, scale, duplicate or use it in a Boolean operation like any model.</p>}
          </>}
          {solidDialog.kind==="hollow" && <>
            <label>Approximate wall thickness (mm)
              <input type="number" min="0.4" step="0.5" value={solidOptions.wall}
                onChange={event=>setSolidOptions(v=>({...v,wall:event.target.value}))}/></label>
            <p className="slicerPlateHint">Creates an internal cavity from a scaled copy of the STL.
              Wall thickness varies on curved or irregular shapes. It is not a true normal-offset hollow.
              Add drain/vent holes separately using Drill if required.</p>
          </>}
          {solidDialog.kind==="drill" && <div className="slicerSolidGrid">
            <label>Hole radius (mm)<input type="number" min="0.2" step="0.5"
              value={solidOptions.radius}
              onChange={event=>setSolidOptions(v=>({...v,radius:event.target.value}))}/></label>
            <label>Centre X (mm)<input type="number" step="0.5" value={solidOptions.x_mm}
              onChange={event=>setSolidOptions(v=>({...v,x_mm:event.target.value}))}/></label>
            <label>Centre Y (mm)<input type="number" step="0.5" value={solidOptions.y_mm}
              onChange={event=>setSolidOptions(v=>({...v,y_mm:event.target.value}))}/></label>
            <p className="slicerPlateHint">Drills a vertical through-hole along Z.</p>
          </div>}
          {solidDialog.kind==="cut" && <>
            <label>Cut plane axis
              <select value={solidOptions.cutAxis} onChange={event=>{
                const axis=event.target.value;
                const target=sceneRef.current?.meshes.get(solidDialog.id);
                const box=target ? new THREE.Box3().setFromObject(target) : null;
                setSolidOptions(v=>({...v,cutAxis:axis,
                  cutHeight:box ? pretty((box.min[axis]+box.max[axis])/2) : v.cutHeight}));
              }}>
                <option value="z">Z · horizontal</option>
                <option value="x">X · vertical</option>
                <option value="y">Y · vertical</option>
              </select></label>
            <label>Cut plane position (mm)
              <input type="number" step="0.5" value={solidOptions.cutHeight}
                onChange={event=>setSolidOptions(v=>({...v,cutHeight:event.target.value}))}/></label>
            <label>Keep pieces
              <select value={solidOptions.keep} onChange={event=>setSolidOptions(v=>({...v,keep:event.target.value}))}>
                <option value="both">Both pieces</option><option value="top">Top only</option>
                <option value="bottom">Bottom only</option>
              </select></label>
          </>}
          {solidDialog.kind==="boolean" && <>
            <label>Second object
              <select value={solidOptions.secondId} onChange={event=>setSolidOptions(v=>({...v,secondId:event.target.value}))}>
                {objects.filter(row=>row.instance_id!==solidDialog.id).map((row,index)=>
                  <option key={row.instance_id} value={row.instance_id}>
                    {index+1}. {sourceFiles.find(file=>String(file.id)===String(row.asset_id))?.name||"Model"}
                  </option>)}
              </select></label>
            <label>Operation
              <select value={solidOptions.booleanMode}
                onChange={event=>setSolidOptions(v=>({...v,booleanMode:event.target.value}))}>
                <option value="union">Union · combine solids</option>
                <option value="difference">Difference · subtract second model</option>
                <option value="intersection">Intersection · common volume</option>
              </select></label>
          </>}
          <p className="slicerPlateHint">Only closed watertight STL meshes are supported. Mesh editing
            runs locally within a bounded triangle/memory budget. Preview first; the originals
            remain unchanged until all replacement STLs are privately validated.</p>
          {solidPreview && <div className="slicerSolidResult" role="status">
            <strong>Preview ready: {solidPreview.parts.length} solid{solidPreview.parts.length===1?"":"s"}</strong>
            {solidPreview.parts.map((p,i)=><span key={i}>{p.triangles.toLocaleString()} triangles ·
              {p.width.toFixed(1)} × {p.depth.toFixed(1)} × {p.height.toFixed(1)} mm</span>)}
          </div>}
          {solidError && <p className="integrationError" role="alert">{solidError}</p>}
          <footer className="slicerAutoOrientModalActions">
            <button type="button" disabled={solidBusy} onClick={()=>{setSolidPreview(null);setSolidDialog(null);}}>Cancel</button>
            <button type="button" disabled={solidBusy} onClick={previewSolid}>
              {solidBusy?"Processing…":"Preview result"}</button>
            <button type="button" disabled={!solidPreview||solidBusy} onClick={applySolid}>
              {solidBusy?"Saving…":"Apply mesh edit"}</button>
          </footer>
        </section>
      </div>,document.body
    )}
    {splitPreview && createPortal(
      <div className="slicerAutoOrientModalBackdrop" role="presentation"
        onMouseDown={event => {
          if (event.target === event.currentTarget && !splitBusy) setSplitPreview(null);
        }}>
        <section className="slicerAutoOrientPanel slicerAutoOrientModal" role="dialog" aria-modal="true"
          aria-label="Split disconnected objects">
          <header className="slicerAutoOrientModalHeader">
            <div><h3>Split into objects</h3>
              <p className="slicerPlateHint">{splitPreview.name}</p></div>
            <button type="button" disabled={splitBusy} aria-label="Cancel split"
              onClick={() => setSplitPreview(null)}>✕</button>
          </header>
          <p>{splitPreview.parts.length} disconnected components detected. Each colour on the
            build plate represents one resulting object. The original remains unchanged until you confirm.</p>
          <div className="slicerSplitParts" role="list" aria-label="Detected parts">
            {splitPreview.parts.map((part, i) => <div role="listitem" key={i}>
              <span className="slicerSplitSwatch" style={{ background: PALETTE[i % PALETTE.length] }} />
              <div><strong>Part {i + 1}</strong><small>{part.triangles.toLocaleString()} triangles ·
                {part.width.toFixed(1)} × {part.depth.toFixed(1)} × {part.height.toFixed(1)} mm</small></div>
            </div>)}
          </div>
          <p className="slicerPlateHint">Each part will be saved as a private, independently editable STL
            and arranged on the plate with 5 mm clearance. Existing per-object print settings are retained.
            Original rotations and scale are baked into the resulting geometry; all parts rest on the build plate.
            Connected or intersecting geometry cannot be separated by this operation.</p>
          {splitError && <p role="alert" className="integrationError">{splitError}</p>}
          <footer className="slicerAutoOrientModalActions">
            <button type="button" disabled={splitBusy} onClick={() => setSplitPreview(null)}>Cancel</button>
            <button type="button" disabled={splitBusy} onClick={applySplit}>
              {splitBusy ? "Creating objects…" : "Split into " + splitPreview.parts.length + " objects"}
            </button>
          </footer>
        </section>
      </div>, document.body
    )}
    {splitError && !splitPreview && <p role="alert" className="integrationError">{splitError}</p>}
    {autoOrientModalOpen && createPortal(
      <div className="slicerAutoOrientModalBackdrop" role="presentation"
        onMouseDown={event => { if (event.target === event.currentTarget) setAutoOrientModalOpen(false); }}>
        <section className="slicerAutoOrientPanel slicerAutoOrientModal" role="dialog" aria-modal="true"
          aria-label="Compare model orientations">
          <header className="slicerAutoOrientModalHeader">
            <div><h3>Compare orientations</h3>
              <p className="slicerPlateHint">Review suggestions for {AUTO_ORIENT_GOALS[autoOrientGoal] || "your chosen goal"}.</p>
            </div>
            <button type="button" onClick={() => setAutoOrientModalOpen(false)} aria-label="Close comparison">✕</button>
          </header>
          {autoOrientBusy && <p role="status">Comparing mesh orientations…</p>}
          {autoOrientAnalysis?.error && <p role="alert" className="integrationError">{autoOrientAnalysis.error}</p>}
          {autoOrientAnalysis?.choices?.[autoOrientGoal] && <>
            <p className="slicerPlateHint">{autoOrientAnalysis.faceSamples.toLocaleString()}
              {autoOrientAnalysis.approximate ? " sampled" : ""} mesh faces analysed.</p>
            <div className="slicerAutoOrientChoices" role="group" aria-label="Suggested orientations">
              {autoOrientAnalysis.choices[autoOrientGoal].slice(0, 3).map((option, rank) =>
                <button key={option.index} type="button"
                  className={autoOrientChoice === rank ? "isActive" : ""}
                  aria-pressed={autoOrientChoice === rank}
                  onMouseEnter={() => setAutoOrientChoice(rank)}
                  onFocus={() => setAutoOrientChoice(rank)}
                  onClick={() => setAutoOrientChoice(rank)}>
                  <strong>{rank === 0 ? "Recommended" : "Alternative " + rank}</strong>
                  <span>{option.label}</span>
                  <small>Height {option.metrics.height.toFixed(1)} mm</small>
                </button>)}
            </div>
            {(() => {
              const option = autoOrientAnalysis.choices[autoOrientGoal][autoOrientChoice];
              const metrics = option?.metrics, relative = option?.relative;
              if (!metrics || !relative) return null;
              return <>
                <p className="slicerPlateHint">The blue ghost on the plate shows the proposed orientation while the solid model remains unchanged.</p>
                <dl className="slicerAutoOrientMetrics">
                  <div><dt>Print-time proxy</dt><dd>{orientationComparison(relative.time)}</dd></div>
                  <div><dt>Extra material proxy</dt><dd>{orientationComparison(relative.material)}</dd></div>
                  <div><dt>Support-risk proxy</dt><dd>{orientationComparison(relative.support)}</dd></div>
                  <div><dt>Failure-risk proxy</dt><dd>{orientationComparison(relative.failure)}</dd></div>
                  <div><dt>Bed-contact area estimate</dt><dd>{metrics.contactArea.toFixed(1)} mm²</dd></div>
                  <div><dt>Print height</dt><dd>{metrics.height.toFixed(1)} mm</dd></div>
                </dl>
              </>;
            })()}
            <p className="slicerPlateHint">{autoOrientAnalysis.warning} Lower is better for all four proxy metrics. Green means best or tied; red means worse than the best analysed pose for that metric. These comparisons are not print-success probabilities.</p>
          </>}
          <footer className="slicerAutoOrientModalActions">
            <button type="button" onClick={() => setAutoOrientModalOpen(false)}>Cancel</button>
            <button type="button" disabled={!canEdit || !autoOrientAnalysis?.choices?.[autoOrientGoal]?.[autoOrientChoice]}
              onClick={applyAutoOrientation}>Apply orientation</button>
          </footer>
        </section>
      </div>, document.body
    )}

    {objects.length > 0 && <div className="formGrid slicerPlateTransformFields">
      <label>X position (mm)
        <input data-slicer-field="x_mm" type="number" min={-10000} max={10000} step="0.5" value={chosen?.x_mm ?? 0}
          disabled={!canEdit} onChange={event => patch("x_mm", pretty(event.target.value))} />
      </label>
      <label>Y position (mm)
        <input type="number" min={-10000} max={10000} step="0.5" value={chosen?.y_mm ?? 0}
          disabled={!canEdit} onChange={event => patch("y_mm", pretty(event.target.value))} />
      </label>
      <label>Z centre (mm)
        <input data-slicer-field="z_mm" type="number" min={0} max={1000} step="0.5"
          value={pretty(Number(chosen?.z_mm || 0) + (selectedMeasurement?.height || 0) / 2)}
          disabled={!canEdit} onChange={event =>
            patch("z_mm", pretty(Number(event.target.value) - (selectedMeasurement?.height || 0) / 2))} />
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
        <button data-slicer-action="center" type="button" disabled={!canEdit || !chosen}
          onClick={() => applySelectedTransform({ x_mm: 0, y_mm: 0 },
            "Cannot centre this model without overlapping another model or leaving the build plate.")}>
          Centre selected
        </button>
        <button type="button" disabled={!canEdit || !chosen}
          onClick={() => applySelectedTransform({
            rotation_deg: 0, rotation_xyz_deg: [0, 0], scale_percent: 100,
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
