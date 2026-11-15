import React, { useState } from "react";
import orcaSvg from "../assets/slicer-engines/orcaslicer.svg?raw";
import crealitySvg from "../assets/slicer-engines/crealityprint.svg?raw";
import bambuSvg from "../assets/slicer-engines/bambustudio.svg?raw";
import prusaSvg from "../assets/slicer-engines/prusaslicer.svg?raw";
import snapmakerSvg from "../assets/slicer-engines/snapmakerorca.svg?raw";
import elegooSvg from "../assets/slicer-engines/elegooslicer.svg?raw";
import curaSvg from "../assets/slicer-engines/cura.svg?raw";
import anycubicSvg from "../assets/slicer-engines/anycubicslicernext.svg?raw";

/**
 * Bundle logos inside the JS asset, rather than requesting fixed
 * /static/app/slicer-engines paths that may not exist behind a reverse proxy.
 * Vite's ?raw importer produces a stable same-bundle SVG image data URI.
 */
const logoUri = svg => "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
const LOGOS = Object.freeze({
  orcaslicer: logoUri(orcaSvg),
  crealityprint: logoUri(crealitySvg),
  bambustudio: logoUri(bambuSvg),
  prusaslicer: logoUri(prusaSvg),
  snapmakerorca: logoUri(snapmakerSvg),
  elegooslicer: logoUri(elegooSvg),
  cura: logoUri(curaSvg),
  anycubicslicernext: logoUri(anycubicSvg),
});

export function SlicerEngineLogo({ engine, label = "Slicer engine", size = "normal" }) {
  const [failed, setFailed] = useState(false);
  const src = LOGOS[engine];
  const className = "slicerEngineLogo" + (size === "small" ? " slicerEngineLogoSmall" : "");
  if (src && !failed) {
    return <img className={className}
      src={src} width={size === "small" ? 28 : 44} height={size === "small" ? 28 : 44}
      alt="" decoding="async" onError={() => setFailed(true)} />;
  }
  return <span className={className + " slicerEngineLogoFallback"}
    role="img" aria-label={label}>{String(label).trim().slice(0, 2).toUpperCase()}</span>;
}

/** A branded alternative to a native select (which cannot show image options). */
export default function SlicerEngineChoices({
  engines = [], selected = "", onSelect, disabled = false, mode = "select",
}) {
  return <div className="slicerEngineChoices" role={mode === "select" ? "radiogroup" : "list"}
    aria-label={mode === "select" ? "Slicing engine" : "Available slicer engines"}>
    {engines.map(engine => {
      const active = selected === engine.key;
      const verified = engine.available === true;
      const status = verified
        ? "Verified " + (engine.installed_version || "worker")
        : "Not installed / not verified";
      const body = <>
        <SlicerEngineLogo engine={engine.key} label={engine.label} />
        <span className="slicerEngineChoiceText">
          <strong>{engine.label}</strong>
          <small>{status}</small>
        </span>
      </>;
      return mode === "select"
        ? <label key={engine.key} className={"slicerEngineChoice" + (active ? " isSelected" : "") +
          (disabled ? " isDisabled" : "")}>
          <input type="radio" name="slicer-engine" value={engine.key} checked={active}
            disabled={disabled} onChange={() => onSelect?.(engine.key)} />
          {body}
        </label>
        : <div key={engine.key} role="listitem" className="slicerEngineChoice slicerEngineChoiceInfo">
          {body}
          <small className="slicerEngineInstallHint">Installation not yet available</small>
        </div>;
    })}
  </div>;
}
