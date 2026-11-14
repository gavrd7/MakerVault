/**
 * Read-only geometry heuristics for the first Auto-orient iteration.
 *
 * These are NOT slicing estimates. Accurate print time/material/support volume
 * requires slicing each candidate with the chosen native printer/process/
 * filament profiles. We deliberately expose dimensionless relative proxies
 * rather than fabricated minutes/grams or a success probability.
 */
import * as THREE from "three";
import { plateEnvelope, plateFootprintsOverlap } from "./slicerPlateGeometry.js";

const MAX_FACES = 9500;
const MAX_CANDIDATES = 15;
const DOWN = new THREE.Vector3(0, 0, -1);
const RAD = Math.PI / 180;
const degrees = angle => {
  const n = THREE.MathUtils.radToDeg(angle);
  return Math.round((((n + 180) % 360 + 360) % 360 - 180) * 1000) / 1000;
};
const metric = number => Math.round(number * 1000) / 1000;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const point = (array, offset) => new THREE.Vector3(array[offset], array[offset + 1], array[offset + 2]);

function readMesh(geometry, item) {
  const pos = geometry?.getAttribute("position");
  if (!pos || pos.count < 3) return null;
  const index = geometry.getIndex();
  const count = Math.floor((index ? index.count : pos.count) / 3);
  if (!count) return null;
  const scaling = item.scale_xyz_percent || [item.scale_percent ?? 100, item.scale_percent ?? 100, item.scale_percent ?? 100];
  const scale = scaling.map(v => Number(v) / 100);
  if (scale.some(v => !Number.isFinite(v) || v <= 0)) return null;
  const stride = Math.max(1, Math.ceil(count / MAX_FACES));
  const triangles = [];
  const normals = new Map();
  for (let i = 0; i < count; i += stride) {
    const a = [], coordinates = [];
    for (let j = 0; j < 3; j++) {
      const vertexId = index ? index.getX(i * 3 + j) : i * 3 + j;
      const vector = new THREE.Vector3().fromBufferAttribute(pos, vertexId)
        .multiply(new THREE.Vector3(...scale));
      a.push(vector);
      coordinates.push(...vector.toArray());
    }
    const cross = a[1].clone().sub(a[0]).cross(a[2].clone().sub(a[0]));
    const area = cross.length() / 2;
    if (area < 1e-8 || !Number.isFinite(area)) continue;
    const normal = cross.normalize();
    const key = [normal.x, normal.y, normal.z].map(v => Math.round(v * 6) / 6).join(",");
    const aggregated = normals.get(key) || { normal: new THREE.Vector3(), area: 0 };
    aggregated.normal.addScaledVector(normal, area);
    aggregated.area += area;
    normals.set(key, aggregated);
    triangles.push({ coords: coordinates, normal, area });
  }
  return { triangles, normals: [...normals.values()].sort((a, b) => b.area - a.area), stride };
}

function candidatesFor(item, geometry, mesh) {
  const sampled = readMesh(geometry, item);
  if (!sampled) return null;
  const current = new THREE.Quaternion().setFromEuler(new THREE.Euler(
    Number(item.rotation_xyz_deg?.[0] || 0) * RAD,
    Number(item.rotation_xyz_deg?.[1] || 0) * RAD,
    Number(item.rotation_deg || 0) * RAD, "XYZ"));
  const raw = [
    { label: "Current orientation", quat: current },
  ];
  for (const [label, normal] of [
    ["Top", [0, 0, -1]], ["Bottom", [0, 0, 1]],
    ["Left side", [-1, 0, 0]], ["Right side", [1, 0, 0]],
    ["Front", [0, -1, 0]], ["Rear", [0, 1, 0]],
  ]) {
    const vector = new THREE.Vector3(...normal).applyQuaternion(current);
    const q = new THREE.Quaternion().setFromUnitVectors(vector, DOWN).multiply(current);
    raw.push({ label, quat: q });
  }
  for (const face of sampled.normals.slice(0, 12)) {
    const vector = face.normal.clone().applyQuaternion(current).normalize();
    const q = new THREE.Quaternion().setFromUnitVectors(vector, DOWN).multiply(current);
    raw.push({ label: "Broad mesh face", quat: q });
  }
  const results = [];
  const seen = new Set();
  for (const entry of raw) {
    const euler = new THREE.Euler().setFromQuaternion(entry.quat, "XYZ");
    const orientation = {
      rotation_xyz_deg: [degrees(euler.x), degrees(euler.y)],
      rotation_deg: degrees(euler.z),
    };
    // Deduplicate physically equivalent poses (including +/- 180 wraps).
    const key = new THREE.Vector3(0, 0, 1).applyQuaternion(entry.quat).toArray()
      .map(v => Math.round(v * 100)).join(",") + ";" +
      new THREE.Vector3(1, 0, 0).applyQuaternion(entry.quat).toArray()
        .map(v => Math.round(v * 100)).join(",");
    if (seen.has(key)) continue;
    seen.add(key);
    results.push({ ...entry, orientation });
    if (results.length >= MAX_CANDIDATES) break;
  }
  return { samples: sampled.triangles, sampleStride: sampled.stride, candidates: results };
}

function evaluate(samples, quaternion) {
  const transformed = [];
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  let minZ = Infinity, maxZ = -Infinity;
  let surface = 0;
  for (const triangle of samples) {
    const vertices = [point(triangle.coords, 0), point(triangle.coords, 3), point(triangle.coords, 6)]
      .map(v => v.applyQuaternion(quaternion));
    for (const vertex of vertices) {
      minX = Math.min(minX, vertex.x); maxX = Math.max(maxX, vertex.x);
      minY = Math.min(minY, vertex.y); maxY = Math.max(maxY, vertex.y);
      minZ = Math.min(minZ, vertex.z); maxZ = Math.max(maxZ, vertex.z);
    }
    const normal = triangle.normal.clone().applyQuaternion(quaternion);
    surface += triangle.area;
    transformed.push({ vertices, normal, area: triangle.area });
  }
  const height = Math.max(0.001, maxZ - minZ);
  const footprint = Math.max(0.001, (maxX - minX) * (maxY - minY));
  const contactTolerance = clamp(height * 0.01, 0.12, 0.6);
  let contact = 0, support = 0, unsupported = 0;
  for (const face of transformed) {
    const centreZ = face.vertices.reduce((sum, v) => sum + v.z, 0) / 3 - minZ;
    const angle = face.normal.z;
    if (centreZ <= contactTolerance && angle < -0.88) contact += face.area;
    // Overhang shallower than ~45 degrees below the horizontal tends to
    // require support. This is an AREA x HEIGHT risk proxy, not actual support
    // volume (which depends on ray obstruction and native slicer settings).
    if (angle < -0.70 && centreZ > contactTolerance) {
      const weight = (-angle - 0.70) / 0.30;
      support += face.area * weight * Math.sqrt(centreZ / height);
      unsupported += face.area * weight;
    }
  }
  const supportRisk = support / Math.max(surface, 1);
  const contactRatio = clamp(contact / footprint, 0, 1);
  const stability = contactRatio / (1 + height / Math.sqrt(footprint));
  // Relative ordering only, NOT minutes, grams, or a probability of success.
  const timeProxy = height * 0.70 + supportRisk * 110;
  const materialProxy = supportRisk * 80; // part volume is orientation invariant
  const failureRisk = 1 / (0.03 + stability * 5) + supportRisk * 3;
  return {
    height: metric(height), contactArea: metric(contact),
    supportRisk: metric(supportRisk), unsupportedArea: metric(unsupported),
    stability: metric(stability), timeProxy: metric(timeProxy),
    materialProxy: metric(materialProxy), failureRisk: metric(failureRisk),
  };
}

// Compare with the best absolute proxy, not with the worst candidate in the
// current shortlist. Min/max scaling incorrectly forces a two-pose comparison
// to read 0/100 even when the measured difference is tiny.
const relativeMetric = (candidates, metricName) => {
  const values = candidates.map(item => item.metrics[metricName]);
  const best = Math.min(...values);
  return values.map(value => {
    // An exact zero baseline cannot have a meaningful percentage increase.
    // Keep the absolute proxy visible and record that the percentage is N/A.
    const overhead = Math.max(0, value - best);
    const percent = best > 1e-9 ? (overhead / best) * 100 :
      overhead <= 1e-9 ? 0 : null;
    // Saturating score is used ONLY to weight different proxy dimensions.
    // The displayed overhead remains uncapped and is not a probability.
    const score = overhead <= 1e-9 ? 0 :
      overhead / (Math.max(Math.abs(best), 1e-9) + overhead);
    return {
      absolute: value,
      percent: percent === null ? null : Math.round(percent * 10) / 10,
      score,
    };
  });
};

export const AUTO_ORIENT_GOALS = Object.freeze({
  balanced: "Balanced · time, material, supports and reliability",
  supports: "Minimum supports",
  speed: "Fastest print · estimated",
});

export function evaluateAutoOrient(geometry, item, bedX, bedY, others = [], dimensions = {}) {
  const data = candidatesFor(item, geometry);
  if (!data || !data.samples.length) return { error: "No readable STL triangles for orientation analysis." };
  const candidates = [];
  for (const option of data.candidates) {
    const transformed = { ...item, ...option.orientation };
    const bounds = plateEnvelope(transformed, dimensions[item.instance_id]);
    if (!bounds || bounds.minX < -bedX / 2 || bounds.maxX > bedX / 2 ||
        bounds.minY < -bedY / 2 || bounds.maxY > bedY / 2) continue;
    if (others.some(other => other.instance_id !== item.instance_id &&
        plateFootprintsOverlap(transformed, dimensions[item.instance_id], other,
          dimensions[other.instance_id], 2) !== false)) continue;
    candidates.push({
      label: option.label,
      orientation: option.orientation,
      metrics: evaluate(data.samples, option.quat),
    });
  }
  if (!candidates.length) return {
    error: "No candidate orientation fits this plate without overlapping another model. Move or auto-arrange models first.",
  };
  const compared = {};
  for (const key of ["supportRisk", "timeProxy", "materialProxy", "failureRisk"])
    compared[key] = relativeMetric(candidates, key);
  const weight = {
    balanced: { supportRisk: 0.20, timeProxy: 0.25, materialProxy: 0.15, failureRisk: 0.40 },
    supports: { supportRisk: 0.78, timeProxy: 0.06, materialProxy: 0.12, failureRisk: 0.04 },
    speed: { supportRisk: 0.08, timeProxy: 0.82, materialProxy: 0.05, failureRisk: 0.05 },
  };
  const choices = {};
  for (const [goal, weights] of Object.entries(weight)) {
    choices[goal] = candidates.map((candidate, index) => ({
      ...candidate, index,
      relative: {
        time: compared.timeProxy[index],
        material: compared.materialProxy[index],
        support: compared.supportRisk[index],
        failure: compared.failureRisk[index],
      },
      score: metric(Object.entries(weights).reduce((sum, [key, w]) =>
        sum + compared[key][index].score * w, 0)),
    })).sort((a, b) => a.score - b.score || a.metrics.failureRisk - b.metrics.failureRisk);
  }
  return {
    choices, faceSamples: data.samples.length, approximate: data.sampleStride > 1,
    warning: "Relative mesh heuristics only. Print time, material, support volume and print success are not predicted by a native slicer. Slice the selected pose to verify.",
  };
}
