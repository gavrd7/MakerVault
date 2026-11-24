/**
 * Fail a release build if the local Manifold WASM would be fetched at runtime.
 * The MakerVault slicer can be mounted behind an authenticated URL prefix.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const assets = "dist/assets";
function javascriptFiles(dir) {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return javascriptFiles(path);
    if (name.endsWith(".wasm"))
      throw new Error("Manifold WASM must not be a standalone network asset: " + name);
    return name.endsWith(".js") ? [path] : [];
  });
}

const chunks = javascriptFiles(assets);
let embedded = 0;
for (const name of chunks) {
  const content = readFileSync(name, "utf8");
  const match = content.match(/data:[^"'\s]*;base64,AGFzbQ[A-Za-z0-9+/=]+/);
  if (match) {
    if (match[0].length < 100000)
      throw new Error("The embedded Manifold WASM data is unexpectedly short.");
    embedded++;
  }
}
if (embedded !== 1)
  throw new Error("Expected exactly one bundled Manifold WASM asset, found " + embedded);
console.log("Manifold WebAssembly is bundled in the frontend JavaScript without an external fetch.");
