/**
 * MakerVault's rotation overlay: the same direct-manipulation affordances users
 * expect from a desktop slicer, but with our own restrained axis colours,
 * 45-degree detents, visible grab tabs and degree markers.
 *
 * The geometry is presentation only. The host editor owns collision validation,
 * undo history and STL transforms. Nothing is changed on the model during idle.
 */
import * as THREE from "three";

const AXES = [
  { name: "X", vector: new THREE.Vector3(1, 0, 0), hex: 0xf47679 },
  { name: "Y", vector: new THREE.Vector3(0, 1, 0), hex: 0x5cdfa3 },
  { name: "Z", vector: new THREE.Vector3(0, 0, 1), hex: 0x72bcff },
];
const ORIGIN = new THREE.Vector3();
const TWO_PI = Math.PI * 2;
const BASE = new THREE.Vector3(1, 0, 0);

function basisFor(axis) {
  const u = Math.abs(axis.z) > 0.5
    ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, 1);
  const v = new THREE.Vector3().crossVectors(axis, u).normalize();
  return { u, v };
}
function ringPoint(axis, angle, radius) {
  const { u, v } = basisFor(axis);
  return u.multiplyScalar(Math.cos(angle) * radius)
    .addScaledVector(v, Math.sin(angle) * radius);
}
function makeLine(points, colour, opacity = 1) {
  return new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({
      color: colour, transparent: true, opacity,
      depthTest: false, depthWrite: false,
    }),
  );
}
function axisLabel(text, colour) {
  const canvas = document.createElement("canvas");
  canvas.width = 96; canvas.height = 96;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, 96, 96);
  context.fillStyle = "#132231";
  context.beginPath(); context.arc(48, 48, 37, 0, TWO_PI); context.fill();
  context.strokeStyle = "#" + colour.toString(16).padStart(6, "0");
  context.lineWidth = 5;
  context.stroke();
  context.font = "bold 48px sans-serif";
  context.fillStyle = "#f0f8ff";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 48, 51);
  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({
    map: texture, transparent: true, depthTest: false, depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.renderOrder = 110;
  return sprite;
}
function disposeObject(node) {
  node.traverse(child => {
    child.geometry?.dispose?.();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of materials) {
      material?.map?.dispose?.();
      material?.dispose?.();
    }
  });
}

/**
 * Keep the mouse projection independent of camera position: a ray is cast
 * against the actual selected local-axis plane through the gizmo centre.
 */
export function dragAngleFromRay(ray, center, normal, originDirection, previous = 0) {
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, center);
  const hit = ray.intersectPlane(plane, new THREE.Vector3());
  if (!hit) return previous;
  const direction = hit.sub(center);
  if (direction.lengthSq() < 1e-5) return previous;
  direction.normalize();
  const cross = new THREE.Vector3().crossVectors(originDirection, direction);
  return Math.atan2(cross.dot(normal), originDirection.dot(direction));
}
export function unwrapRotationDelta(current, previous) {
  let delta = current - previous;
  if (delta > Math.PI) delta -= TWO_PI;
  if (delta < -Math.PI) delta += TWO_PI;
  return delta;
}
export function snapRotationDegrees(degrees, shift = false, speed = 0) {
  if (!Number.isFinite(degrees)) return 0;
  // Fine handling stays at 1° while the pointer moves slowly or is held.
  // Quicker gestures progressively use larger detents, rather than locking
  // every drag to 45°. Shift explicitly requests 1° precision at any speed.
  if (shift || speed < 75) return Math.round(degrees);
  if (speed < 230) return Math.round(degrees / 5) * 5;
  // A fast flick attracts the handle to a nearby 45° stop, but does not
  // unexpectedly jump to 0° when the user passes through e.g. 17°.
  const nearestDetent = Math.round(degrees / 45) * 45;
  return Math.abs(degrees - nearestDetent) <= 10
    ? nearestDetent : Math.round(degrees / 5) * 5;
}

export function createMakerVaultRotationGizmo(scene) {
  const group = new THREE.Group();
  group.name = "MakerVaultRotationGizmo";
  group.visible = false;
  group.renderOrder = 98;
  scene.add(group);
  const hitTargets = [];
  const rings = new Map();
  let activeMesh = null, activeAxis = null, dragState = null;
  let radius = 25;
  const angleCanvas = document.createElement("canvas");
  angleCanvas.width = 256; angleCanvas.height = 88;
  const angleContext = angleCanvas.getContext("2d");
  const angleTexture = new THREE.CanvasTexture(angleCanvas);
  const angleBadge = new THREE.Sprite(new THREE.SpriteMaterial({
    map: angleTexture, transparent: true, depthTest: false, depthWrite: false,
  }));
  angleBadge.name = "MakerVaultRotationAngle";
  angleBadge.scale.set(0.86, 0.3, 1);
  angleBadge.position.set(0, 0, 1.35);
  angleBadge.renderOrder = 120;
  angleBadge.visible = false;
  group.add(angleBadge);
  let activeArc = null;
  const raycaster = new THREE.Raycaster();
  raycaster.params.Line.threshold = 3;

  for (const axis of AXES) {
    const ring = new THREE.Group();
    ring.name = "Rotation-" + axis.name;
    ring.userData.axis = axis.name;
    // A full low-profile rim, with 45-degree major marks and 15-degree minor
    // marks, makes the direction and snapping detents self-explanatory.
    const curve = new THREE.EllipseCurve(0, 0, 1, 1, 0, TWO_PI, false);
    const linePoints = curve.getPoints(128).map(p =>
      ringPoint(axis.vector, Math.atan2(p.y, p.x), 1));
    const rim = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(linePoints),
      new THREE.LineBasicMaterial({
        color: axis.hex, transparent: true, opacity: 0.9,
        depthTest: false, depthWrite: false,
      }),
    );
    rim.renderOrder = 100;
    ring.add(rim);
    const segments = [];
    for (let degree = 0; degree < 360; degree += 15) {
      const radians = THREE.MathUtils.degToRad(degree);
      const major = degree % 45 === 0;
      segments.push(ringPoint(axis.vector, radians, major ? 0.92 : 0.96));
      segments.push(ringPoint(axis.vector, radians, major ? 1.08 : 1.04));
    }
    const tickMarks = makeLine(segments, axis.hex, 0.7);
    tickMarks.renderOrder = 101;
    ring.add(tickMarks);
    // Visible capsule grips, distinct from Three.js concentric rings.
    for (const angle of [0, Math.PI]) {
      const position = ringPoint(axis.vector, angle, 1);
      const grip = new THREE.Mesh(
        new THREE.SphereGeometry(0.074, 12, 8),
        new THREE.MeshBasicMaterial({
          color: axis.hex, depthTest: false, depthWrite: false,
        }),
      );
      grip.name = "MakerVaultRotationGrip-" + axis.name;
      grip.position.copy(position);
      grip.renderOrder = 105;
      grip.userData.axis = axis.name;
      ring.add(grip);
      hitTargets.push(grip);
    }
    const label = axisLabel(axis.name, axis.hex);
    label.position.copy(ringPoint(axis.vector, Math.PI / 4, 1.17));
    label.scale.set(0.24, 0.24, 1);
    ring.add(label);
    // Wider invisible pick tube than the visual line, easier for touch/mouse.
    const pickup = new THREE.Mesh(
      new THREE.TorusGeometry(1, 0.085, 8, 96),
      new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide }),
    );
    pickup.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axis.vector);
    pickup.userData.axis = axis.name;
    ring.add(pickup);
    hitTargets.push(pickup);
    rings.set(axis.name, ring);
    group.add(ring);
  }

  function update(mesh) {
    if (dragState) return;
    activeMesh = mesh || null;
    group.visible = !!mesh;
    if (!mesh) return;
    mesh.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(mesh);
    if (bounds.isEmpty()) { group.visible = false; return; }
    const size = bounds.getSize(new THREE.Vector3());
    radius = THREE.MathUtils.clamp(Math.max(size.x, size.y, size.z) * 0.65, 9, 95);
    group.position.copy(bounds.getCenter(new THREE.Vector3()));
    group.quaternion.copy(mesh.getWorldQuaternion(new THREE.Quaternion()));
    group.scale.setScalar(radius);
    group.updateMatrixWorld(true);
  }
  function pick(ray) {
    if (!group.visible || !activeMesh || dragState) return null;
    raycaster.ray.copy(ray);
    const hit = raycaster.intersectObjects(hitTargets, false)[0];
    if (!hit) return null;
    return hit.object.userData.axis;
  }
  function begin(axisName, ray) {
    if (!activeMesh || dragState) return false;
    const axis = AXES.find(entry => entry.name === axisName);
    if (!axis) return false;
    const normal = axis.vector.clone().applyQuaternion(group.quaternion).normalize();
    const origin = ray.intersectPlane(
      new THREE.Plane().setFromNormalAndCoplanarPoint(normal, group.position),
      new THREE.Vector3());
    if (!origin || origin.distanceToSquared(group.position) < 1e-5) return false;
    const startDirection = origin.sub(group.position).normalize();
    dragState = {
      axisName, normal, startDirection,
      startQuaternion: activeMesh.quaternion.clone(),
      startEuler: activeMesh.rotation.clone(),
      mesh: activeMesh,
      lastAngle: 0,
      lastRaw: 0,
      accumulated: 0,
      lastTimestamp: null,
    };
    activeAxis = axisName;
    angleBadge.visible = true;
    if (angleContext) {
      angleContext.clearRect(0, 0, 256, 88);
      angleContext.fillStyle = "#14293a";
      angleContext.fillRect(0, 0, 256, 88);
      angleContext.fillStyle = "#e2f7ff";
      angleContext.font = "bold 42px sans-serif";
      angleContext.fillText(axisName + " 0°", 24, 57);
      angleTexture.needsUpdate = true;
    }
    for (const [name, ring] of rings) ring.children[0].material.opacity = name === axisName ? 1 : 0.16;
    return true;
  }
  function drag(ray, shift = false, timestamp = null) {
    if (!dragState) return null;
    const raw = dragAngleFromRay(ray, group.position,
      dragState.normal, dragState.startDirection, dragState.lastRaw);
    const motionRadians = unwrapRotationDelta(raw, dragState.lastRaw);
    dragState.accumulated += motionRadians;
    dragState.lastRaw = raw;
    const elapsed = Number.isFinite(timestamp) && dragState.lastTimestamp !== null
      ? Math.max(1, timestamp - dragState.lastTimestamp) : 100;
    if (Number.isFinite(timestamp)) dragState.lastTimestamp = timestamp;
    const speed = Math.abs(THREE.MathUtils.radToDeg(motionRadians)) * 1000 / elapsed;
    const degrees = snapRotationDegrees(THREE.MathUtils.radToDeg(dragState.accumulated), shift, speed);
    dragState.lastAngle = THREE.MathUtils.degToRad(degrees);
    if (activeArc) {
      group.remove(activeArc);
      activeArc.geometry.dispose();
      activeArc.material.dispose();
      activeArc = null;
    }
    if (Math.abs(degrees) > 0.1) {
      const axisVector = AXES.find(entry => entry.name === dragState.axisName).vector;
      const segments = Math.max(2, Math.ceil(Math.abs(degrees) / 5));
      const arcPoints = [];
      for (let i = 0; i <= segments; i++) {
        arcPoints.push(ringPoint(axisVector, dragState.lastAngle * i / segments, 1.02));
      }
      activeArc = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(arcPoints),
        new THREE.LineBasicMaterial({
          color: 0xffffff, depthTest: false, depthWrite: false,
        }),
      );
      activeArc.renderOrder = 115;
      group.add(activeArc);
      angleBadge.position.copy(ringPoint(axisVector, dragState.lastAngle, 1.38));
    }
    if (angleContext) {
      angleContext.clearRect(0, 0, 256, 88);
      angleContext.fillStyle = "#14293a";
      angleContext.fillRect(0, 0, 256, 88);
      angleContext.strokeStyle = "#67cfff";
      angleContext.strokeRect(2, 2, 252, 84);
      angleContext.fillStyle = "#f2fbff";
      angleContext.font = "bold 42px sans-serif";
      angleContext.fillText(dragState.axisName + " " + degrees + "°", 18, 56);
      angleTexture.needsUpdate = true;
    }
    const axis = AXES.find(entry => entry.name === dragState.axisName);
    const quaternion = new THREE.Quaternion().setFromAxisAngle(axis.vector, dragState.lastAngle);
    dragState.mesh.quaternion.copy(dragState.startQuaternion).multiply(quaternion);
    dragState.mesh.updateMatrixWorld(true);
    const euler = dragState.mesh.rotation;
    return {
      axis: dragState.axisName,
      delta: degrees,
      x: Math.round(THREE.MathUtils.radToDeg(euler.x) * 10) / 10,
      y: Math.round(THREE.MathUtils.radToDeg(euler.y) * 10) / 10,
      z: Math.round(THREE.MathUtils.radToDeg(euler.z) * 10) / 10,
    };
  }
  function end() {
    const state = dragState;
    dragState = null;
    activeAxis = null;
    angleBadge.visible = false;
    if (activeArc) {
      group.remove(activeArc);
      activeArc.geometry.dispose();
      activeArc.material.dispose();
      activeArc = null;
    }
    for (const ring of rings.values()) ring.children[0].material.opacity = 0.9;
    return state;
  }
  function dispose() {
    group.removeFromParent();
    disposeObject(group);
  }
  return { group, update, pick, begin, drag, end, dispose, get dragging() { return !!dragState; },
    get activeAxis() { return activeAxis; }, get activeMesh() { return activeMesh; } };
}
