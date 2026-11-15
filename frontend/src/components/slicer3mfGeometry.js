/**
 * Geometry-only 3MF import for the preparation plate.
 *
 * Three's 3MFLoader resolves core mesh resources, build items and supported
 * component transforms. STLExporter bakes the resulting world transforms into
 * one mesh, keeping relative positions of separate parts in the source file.
 * This deliberately does NOT promise a native editable 3MF project round-trip.
 *
 * The generated STL goes through the existing server-side STL validation and
 * owner-scoped private temporary source flow before it can be drafted/sliced.
 */
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
import { STLExporter } from "three/examples/jsm/exporters/STLExporter.js";

export const MAX_3MF_IMPORT_BYTES = 16 * 1024 * 1024;
const MAX_STL_RESULT_BYTES = 32 * 1024 * 1024;
// Match the validated private STL upload path rather than the more restrictive
// downstream 3MF packaging limit, which is checked separately at slicing time.
export const MAX_IMPORTED_TRIANGLES = 500000;
// Import and 3MF preparation accept the same validated source triangle limit.
// Final archive-size and worker limits are checked independently.
export const MAX_PACKAGED_TRIANGLES = 500000;

export async function threeMfGeometryToStl(file) {
  if (!/\.3mf$/i.test(file?.name || "") || !file.size || file.size > MAX_3MF_IMPORT_BYTES) {
    throw new Error("Choose a nonempty 3MF project no larger than 16 MiB.");
  }
  const raw = await file.arrayBuffer();
  let model;
  try {
    model = new ThreeMFLoader().parse(raw);
  } catch (error) {
    throw new Error("Could not read the 3MF geometry. This file may use unsupported 3MF features or be damaged.");
  }
  model.updateMatrixWorld(true);
  let meshCount = 0;
  let triangles = 0;
  model.traverse(child => {
    if (!child.isMesh || !child.geometry) return;
    const geometry = child.geometry;
    const positions = geometry.getAttribute("position");
    if (!positions || !positions.count) return;
    const faces = geometry.index ? geometry.index.count / 3 : positions.count / 3;
    if (!Number.isInteger(faces) || faces < 1) {
      throw new Error("The 3MF contains invalid mesh triangles.");
    }
    meshCount += 1;
    triangles += faces;
  });
  if (!meshCount || !triangles) throw new Error("This 3MF has no supported printable mesh geometry.");
  if (triangles > MAX_IMPORTED_TRIANGLES) {
    throw new Error("3MF contains " + triangles.toLocaleString("en-GB") +
      " triangles; geometry import supports up to " +
      MAX_IMPORTED_TRIANGLES.toLocaleString("en-GB") +
      " triangles, matching MakerVault's STL validation limit.");
  }
  // STLExporter flattens the loaded scene hierarchy, applying mesh matrices.
  // Relative part positions survive; the whole assembly becomes one STL
  // instance, without a separate modifier/colour/assembly edit tree.
  let binary;
  try {
    binary = new STLExporter().parse(model, { binary: true });
  } catch {
    throw new Error("The 3MF mesh could not be converted for the slicing plate.");
  }
  const data = binary instanceof DataView
    ? binary.buffer.slice(binary.byteOffset, binary.byteOffset + binary.byteLength)
    : binary;
  if (!(data instanceof ArrayBuffer) || data.byteLength < 134 ||
      data.byteLength > MAX_STL_RESULT_BYTES) {
    throw new Error("Converted 3MF geometry exceeds the 32 MiB STL preparation limit.");
  }
  const stem = file.name.replace(/\.3mf$/i, "").replace(/[^a-zA-Z0-9._ -]/g, "_").slice(0, 100) || "Imported model";
  return {
    file: new File([data], stem + " (3MF geometry).stl", { type: "model/stl" }),
    meshes: meshCount,
    triangles,
    exceedsPackagedSliceLimit: triangles > MAX_PACKAGED_TRIANGLES,
  };
}
