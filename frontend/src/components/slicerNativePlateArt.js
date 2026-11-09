import k1Svg from "../assets/slicer-bed-art/creality-k1.svg?raw";
import k2Svg from "../assets/slicer-bed-art/creality-k2.svg?raw";
import { nativeBedArtworkId } from "./slicerNativePlateMatcher";

const bundledSvg = svg => "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
const ARTWORK = Object.freeze({
  "creality-k1": bundledSvg(k1Svg),
  "creality-k2": bundledSvg(k2Svg),
});

/** The bundled SVG stays usable even when the app is served at /static/app/.
 * Do not use an absolute /slicer-bed-art/ URL; that is not the Docker path.
 */
export function nativeBedArtwork(printerName, width, depth) {
  return ARTWORK[nativeBedArtworkId(printerName, width, depth)] || null;
}
