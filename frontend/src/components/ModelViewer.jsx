import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
import * as fflate from "three/examples/jsm/libs/fflate.module.js";
import { apiFetch } from "../api";
import { Badge, Modal } from "./Common";


function fileExtension(asset) {
  const filename = asset?.file?.filename || asset?.file?.name || asset?.file?.url || "";
  const match = String(filename).toLowerCase().match(/(\.stl|\.3mf)(?:$|\?)/);
  return match ? match[1] : "";
}


function modelOptions(model) {
  const rows = [];
  for (const revision of model?.revisions || []) {
    for (const asset of revision.assets || []) {
      const extension = fileExtension(asset);
      if (!extension || !asset.file?.url) continue;
      rows.push({
        key: revision.id + ":" + asset.id,
        revision,
        asset,
        extension,
        score: (asset.is_primary ? 100 : 0) + (asset.role === "model" ? 20 : asset.role === "slicer" ? 10 : 0),
      });
    }
  }
  return rows.sort((a, b) => b.score - a.score);
}


function disposeObject(root) {
  if (!root) return;
  root.traverse(child => {
    if (child.geometry) child.geometry.dispose?.();
    if (child.material) {
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach(material => {
        for (const value of Object.values(material)) {
          if (value && typeof value === "object" && value.isTexture) value.dispose?.();
        }
        material.dispose?.();
      });
    }
  });
}


function setWireframe(root, enabled) {
  if (!root) return;
  root.traverse(child => {
    if (!child.isMesh || !child.material) return;
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    materials.forEach(material => {
      if ("wireframe" in material) {
        material.wireframe = enabled;
        material.needsUpdate = true;
      }
    });
  });
}


function fitSummary(analysis, printer) {
  const dims = analysis?.dimensions_mm;
  const build = printer?.build_volume;
  if (!dims || !build?.x || !build?.y || !build?.z) return { status: "unknown", label: "Build volume unknown" };
  const values = [dims.x, dims.y, dims.z, build.x, build.y, build.z].map(Number);
  if (values.some(value => !Number.isFinite(value) || value <= 0)) return { status: "unknown", label: "Build volume unknown" };

  const direct = dims.x <= build.x && dims.y <= build.y && dims.z <= build.z;
  const rotatedXY = dims.y <= build.x && dims.x <= build.y && dims.z <= build.z;
  if (direct) return { status: "fit", label: "Fits current orientation" };
  if (rotatedXY) return { status: "fit", label: "Fits with XY rotation" };
  return { status: "no", label: "Too large in current Z orientation" };
}


function stat(value, suffix = "") {
  if (value == null || value === "") return "—";
  return String(value) + suffix;
}


function slicerDisplay(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join(", ") || "—";
  if (value == null || value === "") return "—";
  return String(value);
}


function humaniseSlicerKey(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, letter => letter.toUpperCase());
}



function threeMfLocalName(value) {
  return String(value || "").split(":").pop().toLowerCase();
}


function threeMfAttr(element, name) {
  const target = String(name).toLowerCase();
  for (const attribute of Array.from(element?.attributes || [])) {
    if (threeMfLocalName(attribute.name) === target) return attribute.value;
  }
  return "";
}


function threeMfChildren(element, name) {
  const target = String(name).toLowerCase();
  return Array.from(element?.children || []).filter(child => threeMfLocalName(child.tagName) === target);
}


function threeMfTransform(value) {
  const values = String(value || "").trim().split(/\s+/).map(Number);
  if (values.length !== 12 || values.some(item => !Number.isFinite(item))) return new THREE.Matrix4();
  const [m00,m01,m02,m10,m11,m12,m20,m21,m22,m30,m31,m32] = values;
  return new THREE.Matrix4().set(
    m00, m10, m20, m30,
    m01, m11, m21, m31,
    m02, m12, m22, m32,
    0,   0,   0,   1,
  );
}


function threeMfUnitScale(value) {
  return {
    micron: 0.001,
    millimeter: 1,
    centimeter: 10,
    inch: 25.4,
    foot: 304.8,
    meter: 1000,
  }[String(value || "millimeter").toLowerCase()] || 1;
}


function threeMfHasVisibleMesh(root) {
  let found = false;
  root?.traverse?.(child => {
    if (child.isMesh && child.geometry?.attributes?.position?.count) found = true;
  });
  return found;
}


function parseProduction3mf(buffer, projectOnly = false) {
  const archive = fflate.unzipSync(new Uint8Array(buffer));
  const decoder = new TextDecoder();
  const documents = new Map();

  for (const [rawPath, bytes] of Object.entries(archive)) {
    const path = String(rawPath).replace(/^\/+/, "");
    if (!path.toLowerCase().endsWith(".model")) continue;
    const xml = new DOMParser().parseFromString(decoder.decode(bytes), "application/xml");
    if (xml.querySelector("parsererror")) continue;
    const root = xml.documentElement;
    const objects = new Map();
    const resources = threeMfChildren(root, "resources")[0];
    for (const object of threeMfChildren(resources, "object")) {
      const id = threeMfAttr(object, "id");
      if (id) objects.set(id, object);
    }
    documents.set(path, {
      path,
      root,
      objects,
      scale: threeMfUnitScale(threeMfAttr(root, "unit")),
    });
  }

  if (!documents.size) throw new Error("No readable 3MF model documents were found.");

  const projectSettingsBytes = archive["Metadata/project_settings.config"] || archive["metadata/project_settings.config"];
  let projectSettings = {};
  if (projectSettingsBytes) {
    try { projectSettings = JSON.parse(decoder.decode(projectSettingsBytes)); } catch { projectSettings = {}; }
  }
  const filamentColours = Array.isArray(projectSettings.filament_colour)
    ? projectSettings.filament_colour
    : Array.isArray(projectSettings.default_filament_colour)
      ? projectSettings.default_filament_colour
      : [];

  const objectExtruders = new Map();
  const objectNames = new Map();
  const plateMembershipQueues = new Map();
  const projectPlates = [];
  const modelSettingsBytes = archive["Metadata/model_settings.config"] || archive["metadata/model_settings.config"];
  if (projectOnly && !modelSettingsBytes) return null;
  if (modelSettingsBytes) {
    const settingsXml = new DOMParser().parseFromString(decoder.decode(modelSettingsBytes), "application/xml");

    function metadataMap(element) {
      const values = {};
      for (const child of Array.from(element?.children || [])) {
        if (threeMfLocalName(child.tagName) !== "metadata") continue;
        const key = child.getAttribute("key") || child.getAttribute("name");
        const value = child.getAttribute("value") ?? child.textContent?.trim();
        if (key && value != null) values[key] = value;
      }
      return values;
    }

    for (const child of Array.from(settingsXml.documentElement?.children || [])) {
      const kind = threeMfLocalName(child.tagName);
      if (kind === "object") {
        const id = child.getAttribute("id");
        const metadata = metadataMap(child);
        const extruder = Number(metadata.extruder) || 0;
        if (id && extruder) objectExtruders.set(id, extruder);
        if (id && metadata.name) objectNames.set(id, metadata.name);
        continue;
      }
      if (kind !== "plate") continue;

      const metadata = metadataMap(child);
      const plateId = String(metadata.plater_id || metadata.index || projectPlates.length + 1);
      const instances = [];
      for (const instance of Array.from(child.children || [])) {
        if (threeMfLocalName(instance.tagName) !== "model_instance") continue;
        const instanceMetadata = metadataMap(instance);
        const objectId = String(instanceMetadata.object_id || "");
        if (!objectId) continue;
        instances.push({
          objectId,
          instanceId: String(instanceMetadata.instance_id || ""),
          identifyId: String(instanceMetadata.identify_id || ""),
        });
        const queue = plateMembershipQueues.get(objectId) || [];
        queue.push(plateId);
        plateMembershipQueues.set(objectId, queue);
      }
      projectPlates.push({
        id: plateId,
        name: String(metadata.plater_name || ""),
        bedType: String(metadata.bed_type || ""),
        objectCount: instances.length,
        instances,
      });
    }
  }

  function colourForExtruder(extruder) {
    const raw = filamentColours[Math.max(0, Number(extruder || 1) - 1)];
    try {
      return raw ? new THREE.Color(String(raw).slice(0, 7)) : new THREE.Color(0x8fa9c2);
    } catch {
      return new THREE.Color(0x8fa9c2);
    }
  }

  function paintState(value) {
    const text = String(value || "").trim();
    if (!text || text.length > 2) return 0;
    const nibbles = text.toUpperCase().split("").reverse().map(char => parseInt(char, 16));
    if (nibbles.some(value => !Number.isFinite(value))) return 0;
    const token = nibbles[0];
    if ((token & 3) !== 0) return 0;
    const state = token >> 2;
    if (state < 3) return state;
    return 3 + (nibbles[1] || 0);
  }

  function meshFromObject(object, scale, inheritedExtruder) {
    const meshElement = threeMfChildren(object, "mesh")[0];
    if (!meshElement) return null;
    const verticesElement = threeMfChildren(meshElement, "vertices")[0];
    const trianglesElement = threeMfChildren(meshElement, "triangles")[0];
    if (!verticesElement || !trianglesElement) return null;

    const vertices = threeMfChildren(verticesElement, "vertex").map(vertex => [
      Number(threeMfAttr(vertex, "x")) * scale,
      Number(threeMfAttr(vertex, "y")) * scale,
      Number(threeMfAttr(vertex, "z")) * scale,
    ]);
    const positions = [];
    const colours = [];
    let hasPaint = false;
    const baseExtruder = objectExtruders.get(threeMfAttr(object, "id")) || inheritedExtruder || 1;

    for (const triangle of threeMfChildren(trianglesElement, "triangle")) {
      const ids = ["v1","v2","v3"].map(key => Number(threeMfAttr(triangle, key)));
      if (ids.some(id => !Number.isInteger(id) || !vertices[id])) continue;
      const painted = paintState(threeMfAttr(triangle, "paint_color") || threeMfAttr(triangle, "mmu_segmentation"));
      const extruder = painted || baseExtruder;
      const colour = colourForExtruder(extruder);
      if (painted) hasPaint = true;
      for (const id of ids) {
        positions.push(...vertices[id]);
        colours.push(colour.r, colour.g, colour.b);
      }
    }
    if (!positions.length) return null;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    if (hasPaint || filamentColours.length) geometry.setAttribute("color", new THREE.Float32BufferAttribute(colours, 3));
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({
      color: hasPaint || filamentColours.length ? 0xffffff : colourForExtruder(baseExtruder),
      vertexColors: hasPaint || filamentColours.length,
      roughness: 0.7,
      metalness: 0.03,
      side: THREE.DoubleSide,
    });
    return new THREE.Mesh(geometry, material);
  }

  function resolvePath(currentPath, referencedPath) {
    if (!referencedPath) return currentPath;
    const clean = String(referencedPath).replace(/^\/+/, "");
    if (documents.has(clean)) return clean;
    const base = currentPath.split("/").slice(0, -1);
    for (const part of clean.split("/")) {
      if (!part || part === ".") continue;
      if (part === "..") base.pop();
      else base.push(part);
    }
    const joined = base.join("/");
    return documents.has(joined) ? joined : clean;
  }

  const group = new THREE.Group();
  const mainPath = documents.has("3D/3dmodel.model") ? "3D/3dmodel.model" : documents.keys().next().value;

  function addObject(path, objectId, matrix, inheritedExtruder, plateId = "", rootObjectId = "", stack = new Set()) {
    const key = path + "#" + objectId;
    if (stack.has(key)) return;
    const document = documents.get(path);
    const object = document?.objects.get(String(objectId));
    if (!document || !object) return;
    const nextStack = new Set(stack);
    nextStack.add(key);
    const objectExtruder = objectExtruders.get(String(objectId)) || inheritedExtruder || 1;
    const topObjectId = String(rootObjectId || objectId);

    const mesh = meshFromObject(object, document.scale, objectExtruder);
    if (mesh) {
      mesh.applyMatrix4(matrix);
      mesh.userData.plateId = String(plateId || "");
      mesh.userData.objectId = topObjectId;
      mesh.userData.objectName = objectNames.get(topObjectId) || "";
      mesh.userData.extruder = objectExtruder;
      group.add(mesh);
    }

    const components = threeMfChildren(object, "components")[0];
    for (const component of threeMfChildren(components, "component")) {
      const componentPath = resolvePath(path, threeMfAttr(component, "path"));
      const componentMatrix = matrix.clone().multiply(threeMfTransform(threeMfAttr(component, "transform")));
      addObject(
        componentPath,
        threeMfAttr(component, "objectid"),
        componentMatrix,
        objectExtruder,
        plateId,
        topObjectId,
        nextStack,
      );
    }
  }

  const main = documents.get(mainPath);
  const build = threeMfChildren(main?.root, "build")[0];
  const items = threeMfChildren(build, "item");
  for (const item of items) {
    const objectId = String(threeMfAttr(item, "objectid"));
    const queue = plateMembershipQueues.get(objectId) || [];
    const plateId = queue.length ? queue.shift() : "";
    addObject(mainPath, objectId, threeMfTransform(threeMfAttr(item, "transform")), 1, plateId, objectId);
  }

  // Production/Bambu projects can keep all printable meshes in child model
  // documents while the root build is intentionally sparse. Fall back to the
  // child meshes rather than presenting a blank viewer.
  if (!threeMfHasVisibleMesh(group)) {
    for (const [path, document] of documents) {
      for (const [objectId, object] of document.objects) {
        if (!threeMfChildren(object, "mesh")[0]) continue;
        const mesh = meshFromObject(object, document.scale, objectExtruders.get(objectId) || 1);
        if (mesh) {
          mesh.userData.objectId = String(objectId);
          mesh.userData.objectName = objectNames.get(String(objectId)) || "";
          mesh.userData.extruder = objectExtruders.get(String(objectId)) || 1;
          group.add(mesh);
        }
      }
    }
  }

  if (!threeMfHasVisibleMesh(group)) throw new Error("The 3MF package contains no renderable mesh geometry.");
  group.userData.projectStructure = modelSettingsBytes ? {
    plates: projectPlates,
    materialSlots: filamentColours.map((colour, index) => ({ slot: index + 1, colour: String(colour || "") })),
  } : null;
  return group;
}


function ThreeScene({ option, wireframe, showGrid, showAxes, selectedPlate, onLoaded, onError, viewerRef }) {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || !option?.asset?.file?.url) return undefined;

    let disposed = false;
    let objectRoot = null;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0c1118);

    const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100000);
    camera.up.set(0, 0, 1);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.replaceChildren(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;

    const ambient = new THREE.HemisphereLight(0xffffff, 0x334155, 2.3);
    scene.add(ambient);
    const key = new THREE.DirectionalLight(0xffffff, 2.8);
    key.position.set(4, -5, 7);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x9ec5ff, 1.2);
    fill.position.set(-4, 2, 3);
    scene.add(fill);

    const grid = new THREE.GridHelper(200, 20, 0x526174, 0x263241);
    grid.rotation.x = Math.PI / 2;
    grid.visible = showGrid;
    scene.add(grid);

    const axes = new THREE.AxesHelper(40);
    axes.visible = showAxes;
    scene.add(axes);

    function resize() {
      if (!mount.clientWidth || !mount.clientHeight) return;
      renderer.setSize(mount.clientWidth, mount.clientHeight, false);
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
    }

    function visibleBounds(root) {
      const box = new THREE.Box3();
      root?.traverse?.(child => {
        if (child.isMesh && child.visible !== false && child.geometry?.attributes?.position?.count) {
          box.expandByObject(child);
        }
      });
      return box;
    }

    function fitCamera(root) {
      if (!root) return;
      const box = visibleBounds(root);
      if (box.isEmpty()) return;
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z, 1);

      // Frame against both viewport dimensions. Using only the vertical FOV
      // can crop or visually offset wide/multi-object 3MF projects.
      const verticalFov = THREE.MathUtils.degToRad(camera.fov);
      const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * Math.max(camera.aspect, 0.01));
      const verticalDistance = size.z / (2 * Math.tan(verticalFov / 2));
      const horizontalSpan = Math.hypot(size.x, size.y);
      const horizontalDistance = horizontalSpan / (2 * Math.tan(horizontalFov / 2));
      const distance = Math.max(verticalDistance, horizontalDistance, maxDim * 0.72, 1) * 1.35;
      const direction = new THREE.Vector3(1.15, -1.35, 0.9).normalize();

      camera.position.copy(center).add(direction.multiplyScalar(distance));
      camera.near = Math.max(distance / 1000, 0.01);
      camera.far = Math.max(distance * 100, 1000);
      camera.updateProjectionMatrix();
      controls.target.copy(center);
      controls.update();

      const gridSize = Math.max(Math.ceil(maxDim * 2 / 10) * 10, 50);
      grid.position.set(center.x, center.y, Math.min(box.min.z, 0));
      grid.scale.setScalar(gridSize / 200);
      axes.position.set(center.x, center.y, Math.min(box.min.z, 0));
      axes.scale.setScalar(Math.max(maxDim / 40, 0.5));
    }

    function applyPlateFilter(root, plateId) {
      if (!root) return;
      const wanted = String(plateId || "all");
      let tagged = 0;
      let visible = 0;
      root.traverse?.(child => {
        if (!child.isMesh) return;
        const meshPlate = String(child.userData?.plateId || "");
        if (meshPlate) tagged += 1;
        child.visible = wanted === "all" || (meshPlate && meshPlate === wanted);
        if (child.visible) visible += 1;
      });
      // Never turn a model blank if a third-party 3MF uses a plate mapping we
      // do not yet understand. In that case retain the complete project view.
      if (wanted !== "all" && (!tagged || !visible)) {
        root.traverse?.(child => { if (child.isMesh) child.visible = true; });
        return false;
      }
      return true;
    }

    function addObject(root) {
      if (disposed) {
        disposeObject(root);
        return;
      }
      objectRoot = root;
      scene.add(root);
      setWireframe(root, wireframe);
      applyPlateFilter(root, selectedPlate);
      fitCamera(root);
      onLoaded?.(root.userData?.projectStructure || null);
    }

    const manager = new THREE.LoadingManager();
    manager.onError = () => {
      if (!disposed) onError?.("MakerVault could not load this model into the 3D viewer.");
    };

    if (option.extension === ".stl") {
      new STLLoader(manager).load(
        option.asset.file.url,
        geometry => {
          geometry.computeVertexNormals();
          const material = new THREE.MeshStandardMaterial({
            color: 0x8fa9c2,
            roughness: 0.7,
            metalness: 0.03,
          });
          addObject(new THREE.Mesh(geometry, material));
        },
        undefined,
        error => {
          if (!disposed) onError?.(error?.message || "Could not load STL geometry.");
        },
      );
    } else {
      fetch(option.asset.file.url, { credentials: "same-origin" })
        .then(response => {
          if (!response.ok) throw new Error("Could not load 3MF geometry.");
          return response.arrayBuffer();
        })
        .then(data => {
          if (disposed) return;
          let group = null;
          // Bambu/Orca project 3MFs carry plate/material semantics outside the
          // core 3MF model. Prefer MakerVault's project-aware parser for those
          // packages so meshes can be filtered by build plate and coloured by
          // their stored filament assignments.
          try {
            group = parseProduction3mf(data, true);
          } catch {
            group = null;
          }
          if (!threeMfHasVisibleMesh(group)) {
            try {
              group = new ThreeMFLoader(manager).parse(data);
            } catch {
              group = null;
            }
          }
          if (!threeMfHasVisibleMesh(group)) group = parseProduction3mf(data);
          addObject(group);
        })
        .catch(error => {
          if (!disposed) onError?.(error?.message || "Could not load 3MF geometry.");
        });
    }

    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();

    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });

    sceneRef.current = { scene, camera, renderer, controls, grid, axes, get object() { return objectRoot; }, fitCamera, applyPlateFilter };
    if (viewerRef) viewerRef.current = sceneRef.current;

    return () => {
      disposed = true;
      observer.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      disposeObject(objectRoot);
      renderer.dispose();
      mount.replaceChildren();
      sceneRef.current = null;
      if (viewerRef) viewerRef.current = null;
    };
  }, [option?.key]);

  useEffect(() => {
    const state = sceneRef.current;
    if (state) setWireframe(state.object, wireframe);
  }, [wireframe]);

  useEffect(() => {
    if (sceneRef.current) sceneRef.current.grid.visible = showGrid;
  }, [showGrid]);

  useEffect(() => {
    if (sceneRef.current) sceneRef.current.axes.visible = showAxes;
  }, [showAxes]);

  useEffect(() => {
    const state = sceneRef.current;
    if (!state?.object || !state.applyPlateFilter) return;
    state.applyPlateFilter(state.object, selectedPlate);
    state.fitCamera(state.object);
  }, [selectedPlate]);

  return <div ref={mountRef} className="modelViewerCanvas" />;
}



export function isViewableModelFile(file) {
  const filename = file?.filename || file?.name || file?.url || "";
  return /\.(stl|3mf)(?:$|\?)/i.test(String(filename)) && Boolean(file?.url);
}


export function ModelThumbnail({ file, className = "" }) {
  const hostRef = useRef(null);
  const [src, setSrc] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !isViewableModelFile(file)) return undefined;

    let disposed = false;
    let started = false;
    let objectUrl = "";
    const controller = new AbortController();

    async function buildThumbnail() {
      if (started) return;
      started = true;
      let root = null;
      let renderer = null;
      try {
        const response = await fetch(file.url, {
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Could not load model preview.");
        const data = await response.arrayBuffer();
        const extension = String(file.filename || file.name || file.url || "").toLowerCase().includes(".3mf") ? ".3mf" : ".stl";

        if (extension === ".stl") {
          const geometry = new STLLoader().parse(data);
          geometry.computeVertexNormals();
          root = new THREE.Mesh(
            geometry,
            new THREE.MeshStandardMaterial({ color: 0x8fa9c2, roughness: 0.72, metalness: 0.03 }),
          );
        } else {
          root = new ThreeMFLoader().parse(data);
        }

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x111820);
        scene.add(new THREE.HemisphereLight(0xffffff, 0x334155, 2.4));
        const key = new THREE.DirectionalLight(0xffffff, 2.8);
        key.position.set(4, -5, 7);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0x9ec5ff, 1.1);
        fill.position.set(-4, 2, 3);
        scene.add(fill);
        scene.add(root);

        const box = new THREE.Box3().setFromObject(root);
        if (box.isEmpty()) throw new Error("Model preview has no visible geometry.");
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z, 1);
        const camera = new THREE.PerspectiveCamera(40, 1.5, 0.01, 100000);
        camera.up.set(0, 0, 1);
        const distance = (maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2))) * 1.7;
        const direction = new THREE.Vector3(1.15, -1.35, 0.9).normalize();
        camera.position.copy(center).add(direction.multiplyScalar(distance));
        camera.lookAt(center);
        camera.near = Math.max(distance / 1000, 0.01);
        camera.far = Math.max(distance * 100, 1000);
        camera.updateProjectionMatrix();

        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
        renderer.setPixelRatio(1);
        renderer.setSize(180, 120, false);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.render(scene, camera);

        const blob = await new Promise(resolve => renderer.domElement.toBlob(resolve, "image/webp", 0.82));
        if (!blob) throw new Error("Could not create model thumbnail.");
        objectUrl = URL.createObjectURL(blob);
        if (!disposed) setSrc(objectUrl);
      } catch (error) {
        if (!disposed && error?.name !== "AbortError") setFailed(true);
      } finally {
        disposeObject(root);
        renderer?.dispose();
        renderer?.forceContextLoss?.();
      }
    }

    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        observer.disconnect();
        buildThumbnail();
      }
    }, { rootMargin: "160px" });
    observer.observe(host);

    return () => {
      disposed = true;
      controller.abort();
      observer.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file?.id, file?.url, file?.filename]);

  const extension = (file?.filename?.split(".").pop() || "3D").slice(0, 5).toUpperCase();
  return <div ref={hostRef} className={"modelFileThumbnail " + className}>
    {src ? <img src={src} alt="" /> : <span>{failed ? extension : "3D"}</span>}
  </div>;
}


export function FileModelViewerModal({ file, onClose }) {
  const model = useMemo(() => ({
    id: "file:" + file.id,
    name: file.name || file.filename || "3D file",
    revisions: [{
      id: "file-revision:" + file.id,
      version: file.version || "Current",
      geometry_analysis: null,
      assets: [{
        id: "file-asset:" + file.id,
        role: file.category === "slicer" ? "slicer" : "model",
        is_primary: true,
        file,
      }],
    }],
  }), [file]);

  return <ModelViewerModal
    model={model}
    printers={[]}
    canAnalyse={false}
    viewerOnly
    onClose={onClose}
  />;
}


export default function ModelViewerModal({ model, printers, canAnalyse, onClose, onChanged, initialAssetId = "", viewerOnly = false }) {
  const options = useMemo(() => modelOptions(model), [model]);
  const initialKey = options.find(item => item.asset?.id === initialAssetId)?.key || options[0]?.key || "";
  const [selectedKey, setSelectedKey] = useState(initialKey);
  const [wireframe, setWireframe] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [showAxes, setShowAxes] = useState(false);
  const [loadState, setLoadState] = useState("loading");
  const [error, setError] = useState("");
  const [analysing, setAnalysing] = useState(false);
  const [analysisOverride, setAnalysisOverride] = useState(null);
  const [selectedPlate, setSelectedPlate] = useState("all");
  const [viewerProject, setViewerProject] = useState(null);
  const shellRef = useRef(null);
  const viewerRef = useRef(null);

  const option = options.find(item => item.key === selectedKey) || options[0];
  const storedAnalysis = option?.revision?.geometry_analysis;
  const analysisMatchesAsset = storedAnalysis && (
    !storedAnalysis.source_asset_id || storedAnalysis.source_asset_id === option?.asset?.file?.id
  );
  const analysis = analysisOverride || (analysisMatchesAsset ? storedAnalysis : null);
  const projectPlates = analysis?.project_structure?.plates?.length
    ? analysis.project_structure.plates.map((plate, index) => ({
        id: String(plate.id || index + 1),
        name: plate.name || "",
        objectCount: plate.object_count ?? plate.objectCount ?? 0,
        materialSlots: plate.material_slots || plate.materialSlots || [],
      }))
    : (viewerProject?.plates || []);

  useEffect(() => {
    setLoadState("loading");
    setError("");
    setAnalysisOverride(null);
    setSelectedPlate("all");
    setViewerProject(null);
  }, [option?.key]);

  async function analyse() {
    if (!option) return;
    setAnalysing(true); setError("");
    try {
      const result = await apiFetch(
        "/api/printing/models/" + model.id + "/revisions/" + option.revision.id + "/analyse/",
        { method: "POST", body: { file_asset_id: option.asset.file.id } },
      );
      setAnalysisOverride(result.analysis);
      await onChanged?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalysing(false);
    }
  }

  function resetView() {
    const state = viewerRef.current;
    if (state?.object) state.fitCamera(state.object);
  }

  async function fullscreen() {
    try {
      if (!document.fullscreenElement) await shellRef.current?.requestFullscreen?.();
      else await document.exitFullscreen?.();
    } catch (err) {
      setError(err.message || "Fullscreen mode is unavailable.");
    }
  }

  return <Modal
    title={"3D Viewer · " + model.name}
    subtitle="Interactive local viewer for MakerVault STL and 3MF revisions."
    onClose={onClose}
    wide
    className="modelViewerModal"
  >
    {!options.length ? <div className="formError">Attach an STL or 3MF file to a revision before opening the 3D viewer.</div> :
      <div className={"modelViewerLayout" + (viewerOnly ? " modelViewerLayoutSolo" : "")} ref={shellRef}>
        <section className="modelViewerStage">
          <div className="modelViewerToolbar">
            <select value={option?.key || ""} onChange={e => setSelectedKey(e.target.value)}>
              {options.map(item => <option value={item.key} key={item.key}>
                Rev {item.revision.version} · {item.asset.file.filename || item.asset.file.name}{item.asset.is_primary ? " · Primary" : ""}
              </option>)}
            </select>
            {projectPlates.length > 1 && <select
              className="modelPlateSelect"
              value={selectedPlate}
              onChange={e => setSelectedPlate(e.target.value)}
              aria-label="Build plate"
            >
              <option value="all">All plates</option>
              {projectPlates.map((plate, index) => <option key={plate.id || index} value={String(plate.id || index + 1)}>
                Plate {plate.id || index + 1}{plate.name ? " · " + plate.name : ""} · {plate.objectCount || 0} object{plate.objectCount === 1 ? "" : "s"}
              </option>)}
            </select>}
            <button type="button" onClick={resetView}>Reset view</button>
            <button type="button" className={wireframe ? "active" : ""} onClick={() => setWireframe(value => !value)}>Wireframe</button>
            <button type="button" className={showGrid ? "active" : ""} onClick={() => setShowGrid(value => !value)}>Grid</button>
            <button type="button" className={showAxes ? "active" : ""} onClick={() => setShowAxes(value => !value)}>Axes</button>
            <button type="button" onClick={fullscreen}>Fullscreen</button>
          </div>
          <div className="modelViewerCanvasShell">
            {loadState === "loading" && <div className="modelViewerLoading">Loading model…</div>}
            <ThreeScene
              option={option}
              wireframe={wireframe}
              showGrid={showGrid}
              showAxes={showAxes}
              selectedPlate={selectedPlate}
              viewerRef={viewerRef}
              onLoaded={project => { setLoadState("ready"); if (project?.plates?.length) setViewerProject(project); }}
              onError={message => { setLoadState("error"); setError(message); }}
            />
          </div>
          <small className="modelViewerHint">Drag to orbit · wheel/pinch to zoom · right-drag to pan</small>
        </section>

        {!viewerOnly && <aside className="modelIntelligencePanel">
          <div className="modelIntelligenceHead">
            <div><strong>Model intelligence</strong><small>{analysis ? "Geometry analysed by MakerVault" : "No analysis for this file yet"}</small></div>
            {canAnalyse && <button type="button" onClick={analyse} disabled={analysing}>{analysing ? "Analysing…" : analysis ? "Re-analyse" : "Analyse"}</button>}
          </div>

          {error && <div className="formError">{error}</div>}

          {analysis ? <>
            <div className="modelIntelligenceStats">
              <article><span>Size X</span><strong>{stat(analysis.dimensions_mm?.x, " mm")}</strong></article>
              <article><span>Size Y</span><strong>{stat(analysis.dimensions_mm?.y, " mm")}</strong></article>
              <article><span>Size Z</span><strong>{stat(analysis.dimensions_mm?.z, " mm")}</strong></article>
              <article><span>Triangles</span><strong>{Number(analysis.triangle_count || 0).toLocaleString()}</strong></article>
              <article><span>Vertices</span><strong>{Number(analysis.vertex_count || 0).toLocaleString()}</strong></article>
              <article><span>Volume</span><strong>{analysis.volume_cm3 != null ? analysis.volume_cm3 + " cm³" : "—"}</strong></article>
            </div>

            <div className="modelIntelligenceMeta">
              <span><b>Format:</b> {(analysis.format || "").toUpperCase()} {analysis.encoding ? "· " + analysis.encoding : ""}</span>
              <span><b>Source units:</b> {analysis.source_units || "unknown"}</span>
              <span><b>Complexity:</b> {analysis.complexity || "unknown"}</span>
              <span><b>Surface:</b> {analysis.surface_area_mm2 != null ? Number(analysis.surface_area_mm2).toLocaleString() + " mm²" : "—"}</span>
            </div>

            {analysis.project_structure?.detected && <section className="modelProjectStructure">
              <div className="modelSlicerMetadataHead">
                <div>
                  <strong>3MF project structure</strong>
                  <small>Slicer project layout stored inside this package.</small>
                </div>
                <div className="modelProjectBadges">
                  {analysis.project_structure.multi_plate && <Badge tone="accent">{analysis.project_structure.plate_count} plates</Badge>}
                  {analysis.project_structure.multicolour && <Badge tone="accent">Multicolour</Badge>}
                </div>
              </div>

              <div className="modelProjectSummary">
                <article><span>Build plates</span><strong>{analysis.project_structure.plate_count || "—"}</strong></article>
                <article><span>Project objects</span><strong>{analysis.project_structure.object_count || "—"}</strong></article>
                <article><span>Material slots</span><strong>{analysis.project_structure.materials?.length || "—"}</strong></article>
                <article><span>Painted facets</span><strong>{Number(analysis.project_structure.painted_facets || 0).toLocaleString()}</strong></article>
              </div>

              {!!analysis.project_structure.plates?.length && <div className="modelProjectPlates">
                {analysis.project_structure.plates.map((plate, index) => {
                  const plateId = String(plate.id || index + 1);
                  const materialSlots = plate.material_slots || [];
                  return <button
                    type="button"
                    key={plateId}
                    className={selectedPlate === plateId ? "active" : ""}
                    onClick={() => setSelectedPlate(current => current === plateId ? "all" : plateId)}
                    title={"Show Plate " + plateId + " in the 3D viewer"}
                  >
                    <div>
                      <span>Plate {plateId}</span>
                      <strong>{plate.name || (plate.object_count + " object" + (plate.object_count === 1 ? "" : "s"))}</strong>
                    </div>
                    <small>
                      {plate.bed_type || ""}
                      {materialSlots.length ? ((plate.bed_type ? " · " : "") + "slots " + materialSlots.join(", ")) : ""}
                    </small>
                  </button>;
                })}
              </div>}

              {!!analysis.project_structure.materials?.length && <details className="modelProjectMaterials">
                <summary>{analysis.project_structure.materials.length} material slot{analysis.project_structure.materials.length === 1 ? "" : "s"}</summary>
                <div>
                  {analysis.project_structure.materials.map(material => <article key={material.slot} className={material.used ? "used" : ""}>
                    <i style={{ background: material.colour || "#8fa9c2" }} />
                    <div><strong>Slot {material.slot}{material.type ? " · " + material.type : ""}</strong><small>{material.profile || material.colour || "No stored profile"}</small></div>
                  </article>)}
                </div>
              </details>}

              {analysis.project_structure.note && <small className="modelSlicerNote">{analysis.project_structure.note}</small>}
            </section>}

            {analysis.project_structure?.multi_plate && <div className="settingsCallout">
              <strong>Multi-plate project</strong>
              <p>Orientation and owned-printer fit are not shown for the combined project because each build plate needs to be evaluated independently. Geometry totals above describe the stored meshes, not one printable plate.</p>
            </div>}

            {(analysis.mesh_quality || (!analysis.project_structure?.multi_plate && analysis.orientation)) && <section className="modelPrintability">
              <div className="modelPrintabilityHead">
                <strong>Printability estimate</strong>
                {analysis.mesh_quality?.checked && <Badge tone={analysis.mesh_quality.watertight ? "good" : "danger"}>
                  {analysis.mesh_quality.status === "watertight" ? "Watertight" :
                    analysis.mesh_quality.status === "non_manifold" ? "Non-manifold" :
                    analysis.mesh_quality.status === "degenerate" ? "Degenerate geometry" : "Open mesh"}
                </Badge>}
                {analysis.mesh_quality && !analysis.mesh_quality.checked && <Badge>Topology unchecked</Badge>}
              </div>

              {analysis.mesh_quality && <div className="modelPrintabilityGrid">
                <article>
                  <span>Boundary edges</span>
                  <strong>{analysis.mesh_quality.boundary_edges == null ? "—" : Number(analysis.mesh_quality.boundary_edges).toLocaleString()}</strong>
                </article>
                <article>
                  <span>Non-manifold</span>
                  <strong>{analysis.mesh_quality.non_manifold_edges == null ? "—" : Number(analysis.mesh_quality.non_manifold_edges).toLocaleString()}</strong>
                </article>
                <article>
                  <span>Degenerate faces</span>
                  <strong>{analysis.mesh_quality.degenerate_triangles == null ? "—" : Number(analysis.mesh_quality.degenerate_triangles).toLocaleString()}</strong>
                </article>
              </div>}

              {!analysis.project_structure?.multi_plate && analysis.orientation?.recommended && <div className="modelOrientationCard">
                <div>
                  <span>Suggested axis-aligned orientation</span>
                  <strong>{analysis.orientation.recommended.label}</strong>
                  <small>
                    {analysis.orientation.recommended.support_risk_pct}% support-risk surface ·
                    {" "}{Number(analysis.orientation.recommended.bed_contact_area_mm2 || 0).toLocaleString()} mm² bed contact ·
                    {" "}{analysis.orientation.recommended.height_mm} mm high
                  </small>
                </div>
                {!analysis.orientation.recommended_is_current && analysis.orientation.current && <div className="modelOrientationCompare">
                  <span>Current</span>
                  <strong>{analysis.orientation.current.support_risk_pct}%</strong>
                  <small>support-risk surface</small>
                </div>}
              </div>}

              {!analysis.project_structure?.multi_plate && analysis.orientation?.candidates?.length > 0 && <details className="modelOrientationDetails">
                <summary>Compare all 6 axis orientations</summary>
                <div>
                  {analysis.orientation.candidates.map(candidate => <div key={candidate.key}>
                    <span>{candidate.label}</span>
                    <strong>{candidate.support_risk_pct}%</strong>
                    <small>{candidate.bed_contact_area_mm2} mm² contact · {candidate.height_mm} mm high</small>
                  </div>)}
                </div>
              </details>}

              {!analysis.project_structure?.multi_plate && analysis.orientation?.note && <small className="modelPrintabilityNote">{analysis.orientation.note}</small>}
            </section>}

            {analysis.slicer_metadata?.detected && <section className="modelSlicerMetadata">
              <div className="modelSlicerMetadataHead">
                <div>
                  <strong>Slicer metadata</strong>
                  <small>Read from settings stored inside this 3MF package.</small>
                </div>
                <Badge tone="accent">{analysis.slicer_metadata.application || "3MF slicer data"}</Badge>
              </div>

              <div className="modelSlicerProfiles">
                {analysis.slicer_metadata.profiles?.printer && <article>
                  <span>Printer profile</span>
                  <strong>{slicerDisplay(analysis.slicer_metadata.profiles.printer)}</strong>
                </article>}
                {analysis.slicer_metadata.profiles?.print && <article>
                  <span>Print profile</span>
                  <strong>{slicerDisplay(analysis.slicer_metadata.profiles.print)}</strong>
                </article>}
                {analysis.slicer_metadata.profiles?.filament && <article>
                  <span>Filament profile</span>
                  <strong>{slicerDisplay(analysis.slicer_metadata.profiles.filament)}</strong>
                </article>}
              </div>

              {!!Object.keys(analysis.slicer_metadata.settings || {}).length && <div className="modelSlicerSettings">
                {Object.entries(analysis.slicer_metadata.settings).map(([key, value]) => <article key={key}>
                  <span>{humaniseSlicerKey(key)}</span>
                  <strong>{key.endsWith("_mm") && typeof value === "number" ? value + " mm" : key === "supports_enabled" ? (value ? "Enabled" : "Disabled") : slicerDisplay(value)}</strong>
                </article>)}
              </div>}

              {!!analysis.slicer_metadata.metadata_files?.length && <details className="modelSlicerSources">
                <summary>{analysis.slicer_metadata.metadata_files.length} slicer metadata file{analysis.slicer_metadata.metadata_files.length === 1 ? "" : "s"} detected</summary>
                <div>{analysis.slicer_metadata.metadata_files.map(name => <code key={name}>{name}</code>)}</div>
              </details>}

              {analysis.slicer_metadata.note && <small className="modelSlicerNote">{analysis.slicer_metadata.note}</small>}
            </section>}

            {!!printers?.length && !analysis.project_structure?.multi_plate && <div className="modelFitList">
              <strong>Owned printer fit</strong>
              {printers.map(printer => {
                const fit = fitSummary(analysis, printer);
                return <div key={printer.id}>
                  <span>{printer.name}</span>
                  <Badge tone={fit.status === "fit" ? "good" : fit.status === "no" ? "danger" : undefined}>{fit.label}</Badge>
                </div>;
              })}
            </div>}

            {!!analysis.warnings?.length && <div className="settingsCallout">
              <strong>Analysis notes</strong>
              {analysis.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
            </div>}
          </> : <div className="modelIntelligenceEmpty">
            <strong>Analyse this revision</strong>
            <p>MakerVault can calculate dimensions, mesh health, support-risk orientation, geometry counts, surface area, approximate volume and build-volume fit locally. Compatible 3MF files can also expose the slicer profiles and settings saved inside the package.</p>
          </div>}
        </aside>}
      </div>}
  </Modal>;
}
