import React from "react";

/** UI-only display metadata. Engine installation/verification remains server-owned. */
const LOGOS = Object.freeze({
  orcaslicer: "/static/app/slicer-engines/orcaslicer.svg",
  crealityprint: "/static/app/slicer-engines/crealityprint.svg",
  bambustudio: "/static/app/slicer-engines/bambustudio.svg",
  prusaslicer: "/static/app/slicer-engines/prusaslicer.svg",
  snapmakerorca: "/static/app/slicer-engines/snapmakerorca.svg",
});

export function SlicerEngineLogo({ engine, label = "Slicer engine", size = "normal" }) {
  const src = LOGOS[engine];
  if (src) {
    return <img className={"slicerEngineLogo" + (size === "small" ? " slicerEngineLogoSmall" : "")}
      src={src} width={size === "small" ? 28 : 44} height={size === "small" ? 28 : 44}
      alt="" loading="lazy" decoding="async" />;
  }
  return <span className="slicerEngineLogo slicerEngineLogoFallback" aria-hidden="true">3D</span>;
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
