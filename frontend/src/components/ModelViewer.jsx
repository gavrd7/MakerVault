import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
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


function ThreeScene({ option, wireframe, showGrid, showAxes, onLoaded, onError, viewerRef }) {
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

    function fitCamera(root) {
      if (!root) return;
      const box = new THREE.Box3().setFromObject(root);
      if (box.isEmpty()) return;
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z, 1);
      const fov = THREE.MathUtils.degToRad(camera.fov);
      const distance = (maxDim / (2 * Math.tan(fov / 2))) * 1.55;
      const direction = new THREE.Vector3(1.15, -1.35, 0.9).normalize();
      camera.position.copy(center).add(direction.multiplyScalar(distance));
      camera.near = Math.max(distance / 1000, 0.01);
      camera.far = Math.max(distance * 100, 1000);
      camera.updateProjectionMatrix();
      controls.target.copy(center);
      controls.update();

      const gridSize = Math.max(Math.ceil(maxDim * 2 / 10) * 10, 50);
      grid.scale.setScalar(gridSize / 200);
      axes.scale.setScalar(Math.max(maxDim / 40, 0.5));
    }

    function addObject(root) {
      if (disposed) {
        disposeObject(root);
        return;
      }
      objectRoot = root;
      scene.add(root);
      setWireframe(root, wireframe);
      fitCamera(root);
      onLoaded?.();
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
      new ThreeMFLoader(manager).load(
        option.asset.file.url,
        group => addObject(group),
        undefined,
        error => {
          if (!disposed) onError?.(error?.message || "Could not load 3MF geometry.");
        },
      );
    }

    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();

    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });

    sceneRef.current = { scene, camera, renderer, controls, grid, axes, get object() { return objectRoot; }, fitCamera };
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

  return <div ref={mountRef} className="modelViewerCanvas" />;
}


export default function ModelViewerModal({ model, printers, canAnalyse, onClose, onChanged }) {
  const options = useMemo(() => modelOptions(model), [model]);
  const [selectedKey, setSelectedKey] = useState(options[0]?.key || "");
  const [wireframe, setWireframe] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [showAxes, setShowAxes] = useState(false);
  const [loadState, setLoadState] = useState("loading");
  const [error, setError] = useState("");
  const [analysing, setAnalysing] = useState(false);
  const [analysisOverride, setAnalysisOverride] = useState(null);
  const shellRef = useRef(null);
  const viewerRef = useRef(null);

  const option = options.find(item => item.key === selectedKey) || options[0];
  const storedAnalysis = option?.revision?.geometry_analysis;
  const analysisMatchesAsset = storedAnalysis && (
    !storedAnalysis.source_asset_id || storedAnalysis.source_asset_id === option?.asset?.file?.id
  );
  const analysis = analysisOverride || (analysisMatchesAsset ? storedAnalysis : null);

  useEffect(() => {
    setLoadState("loading");
    setError("");
    setAnalysisOverride(null);
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
  >
    {!options.length ? <div className="formError">Attach an STL or 3MF file to a revision before opening the 3D viewer.</div> :
      <div className="modelViewerLayout" ref={shellRef}>
        <section className="modelViewerStage">
          <div className="modelViewerToolbar">
            <select value={option?.key || ""} onChange={e => setSelectedKey(e.target.value)}>
              {options.map(item => <option value={item.key} key={item.key}>
                Rev {item.revision.version} · {item.asset.file.filename || item.asset.file.name}{item.asset.is_primary ? " · Primary" : ""}
              </option>)}
            </select>
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
              viewerRef={viewerRef}
              onLoaded={() => setLoadState("ready")}
              onError={message => { setLoadState("error"); setError(message); }}
            />
          </div>
          <small className="modelViewerHint">Drag to orbit · wheel/pinch to zoom · right-drag to pan</small>
        </section>

        <aside className="modelIntelligencePanel">
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

            {!!printers?.length && <div className="modelFitList">
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
            <p>MakerVault can calculate dimensions, geometry counts, surface area, approximate volume and build-volume fit without sending the model to an external service.</p>
          </div>}
        </aside>
      </div>}
  </Modal>;
}
