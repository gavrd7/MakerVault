import React from "react";

/** Compact, accessible outline icons for the native MakerVault slicer UI. */
const paths = {
  "shape-box": <><path d="m3 7 9-5 9 5-9 5-9-5Z"/><path d="M3 7v10l9 5 9-5V7M12 12v10"/></>,
  "shape-cylinder": <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5"/></>,
  "shape-sphere": <><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/></>,
  "shape-cone": <><path d="M12 2 3 19c1 4 17 4 18 0L12 2Z"/><ellipse cx="12" cy="19" rx="9" ry="3"/></>,
  "shape-disc": <><ellipse cx="12" cy="8" rx="9" ry="4"/><path d="M3 8v7c0 5 18 5 18 0V8"/></>,
  "shape-torus": <><ellipse cx="12" cy="12" rx="10" ry="8"/><ellipse cx="12" cy="12" rx="4" ry="3"/></>,
  "shape-text": <><path d="M3 5h18M12 5v16M6 5v3m12-3v3"/></>,
  "shape-svg": <><path d="M4 2h11l5 5v15H4zM15 2v5h5M7 17l3-6 3 3 4-5"/></>,
  add: <><path d="M12 5v14M5 12h14"/></>,
  "add-plate": <><path d="m3 13 9-5 9 5-9 5-9-5Z"/><path d="m3 17 9 5 9-5"/><path d="M17 2v9M12.5 6.5h9"/></>,
  "plates-overview": <><rect x="2" y="3" width="9" height="8" rx="1"/><rect x="13" y="3" width="9" height="8" rx="1"/><rect x="2" y="13" width="9" height="8" rx="1"/><rect x="13" y="13" width="9" height="8" rx="1"/><path d="M5 6h3m8 0h3M5 16h3m8 0h3"/></>,
  "paint-support": <><path d="m4 17 8-5 8 5-8 5-8-5Z"/><path d="M7 14v7m5-7v7m5-7v7"/><path d="m4 4 6 6"/></>,
  "paint-seam": <><path d="M5 3h14v18H5z"/><path strokeDasharray="2 2" d="M12 3v18"/><path d="m3 7 4 4"/></>,
  "paint-colour": <><path d="M12 2a10 10 0 1 0 10 10c0-2.2-1.8-3.5-3.9-3.5H16c-1.5 0-2.4-1.3-2.4-2.5 0-1.1.7-2.1 1.1-2.9A10 10 0 0 0 12 2Z"/><circle cx="6.6" cy="10" r="1.1"/><circle cx="9.5" cy="6.4" r="1.1"/><circle cx="15.2" cy="5.5" r="1.1"/><circle cx="6.9" cy="15" r="1.1"/><path d="m17 14 4 4m-5.5-2.5 3.5 3.5"/></>,

  "paint-brush": <><path d="m14 4 6 6-9 9-6-6 9-9Z"/><path d="m14 4 3-2 5 5-2 3M5 13c-2 2-2 5-3 7 3-1 6-1 8-3"/></>,
  "paint-facet": <><path d="M12 3 3 20h18L12 3Z"/><path d="m12 3 1 12M3 20l10-5 8 5"/></>,
  "paint-disc": <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M12 1v4M12 19v4M1 12h4m14 0h4"/></>,
  "paint-sphere": <><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4.5" ry="9"/><path d="M3 12h18M6 6.5c3.5 2 8.5 2 12 0"/></>,
  "paint-fill": <><path d="m4 12 8-8 7 7-8 8-7-7Z"/><path d="m9 7 7 7M4 20h13"/><path d="M19 16c0-1.7 2-3.6 2-3.6s2 1.9 2 3.6a2 2 0 0 1-4 0Z"/></>,
  "paint-smart": <><path d="M4 19 11 5l9 14H4Z"/><path d="m13 8 3 7M8 15l2-4"/></>,
  "paint-height": <><path d="M4 4h16M4 20h16M4 12h16"/><path d="m9 9 3-3 3 3m-3-3v12m-3-3 3 3 3-3"/></>,
  undo: <><path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-2"/></>,
  redo: <><path d="m15 14 5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h2"/></>,
  move: <><path d="M12 2v20M2 12h20M9 5l3-3 3 3M9 19l3 3 3-3M5 9l-3 3 3 3m14-6 3 3-3 3"/></>,
  rotate: <><path d="M20 11a8 8 0 1 1-2.3-5.6L20 8"/><path d="M20 3v5h-5"/></>,
  scale: <><rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 16 8-8M12 8h4v4"/></>,
  arrange: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><path d="M10 6.5h4M6.5 10v4m11-4v4M10 17.5h4"/></>,
  center: <><path d="M3 7V4h4M17 4h4v3M21 17v4h-4M7 21H4v-4"/><rect x="8" y="8" width="8" height="8" rx="1"/><path d="M12 2v6m0 8v6M2 12h6m8 0h6"/></>,
  focus: <><path d="M3 8V4h5m8 0h5v4M21 16v4h-5M8 20H3v-4"/><path d="m7 11 5-3 5 3v5l-5 3-5-3v-5Z"/><path d="m7 11 5 3 5-3m-5 3v5"/></>,
  duplicate: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></>,
  remove: <><path d="M3 6h18M8 6V4h8v2m3 0-1 15H6L5 6M10 10v7m4-7v7"/></>,
  orient: <><path d="M2 20h20"/><path d="m6 15 5-10 8 4-5 10-8-4Z"/><path d="M19 3a8 8 0 0 1 2 8m-2-1 2 1 1-3"/><path d="M10 18v2"/></>,
  face: <><path d="M2 20h20"/><path d="m5 7 10-4 5 8-10 4-5-8Z"/><path d="m11 16 2 3m-5-1 3-2 2 2"/><path d="M14 11 11 16"/></>,
  split: <><path d="m3 7 7-4v18l-7-4V7Zm11-4 7 4v10l-7 4V3Z"/><path d="M12 2v20" strokeDasharray="2 3"/><path d="m7 12-3 0m13 0h3"/></>,
  hollow: <><path d="m12 2 9 5v10l-9 5-9-5V7l9-5Z"/><path d="m12 6 5 3v6l-5 3-5-3V9l5-3Z"/><path d="m3 7 4 2m14-2-4 2"/></>,
  drill: <><path d="m9 2 6 0-1 5h-4L9 2Z"/><path d="m10 7 4 0-1 10-1 4-1-4-1-10Z"/><path d="M9 10h6m-6 3h6"/><path d="M4 20h4m8 0h4"/></>,
  cut: <><path d="M2 12h20" strokeDasharray="3 2"/><path d="m6 8 3-3 4 4-3 3-4-4Zm8 7 3-3 4 4-3 3-4-4Z"/><path d="m3 3 18 18"/></>,
  boolean: <><rect x="3" y="3" width="12" height="12" rx="1.5"/><circle cx="15" cy="15" r="7"/><path d="M8 8h7v7H8Z" fill="currentColor" fillOpacity=".2"/><path d="m18 3 3 0m-1.5-1.5v3"/></>,
  measure: <><path d="M2 9 17 3l5 8-15 6-5-8Z"/><path d="m6 8 2 4m2-5 1 2m3-4 2 4"/><path d="M4 21h16"/><circle cx="4" cy="21" r="1" fill="currentColor"/><circle cx="20" cy="21" r="1" fill="currentColor"/></>,
  paint: <><path d="m14 4 6 6M4 20c2 0 4-2 4-4l9-9-4-4-9 9c-1 1-2 3-2 5v3h2Z"/></>,
  layers: <><path d="m12 2 9 6-9 6-9-6 9-6Zm-9 9 9 6 9-6m-18 5 9 6 9-6"/></>,
  plate: <><path d="m3 8 9-5 9 5-9 5-9-5Z"/><path d="m3 8 0 8 9 5 9-5V8M12 13v8"/><path d="m8 8 4-2 4 2-4 2-4-2Z"/></>,
  printer: <><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M6 7h12M6 17h12M8 10h8v5H8zM12 7v3M7 21v1m10-1v1"/><circle cx="18" cy="5" r="1"/></>,
  models: <><path d="m3 7 5-3 5 3-5 3-5-3Z"/><path d="M3 7v6l5 3 5-3V7M8 10v6"/><path d="m14 13 4-2 4 2-4 2-4-2Z"/><path d="M14 13v5l4 3 4-3v-5M18 15v6"/></>,
  settings: <><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="#10161e"/><circle cx="16" cy="12" r="2" fill="#10161e"/><circle cx="10" cy="18" r="2" fill="#10161e"/></>,
  quality: <><path d="m12 2 2.8 6.2L22 9l-5.3 4.9 1.4 7L12 17.5 5.9 21l1.4-7L2 9l7.2-.8L12 2Z"/></>,
  strength: <><path d="M12 2 4 6v6c0 5 3.5 8 8 10 4.5-2 8-5 8-10V6l-8-4Z"/><path d="m9 12 2 2 4-4"/></>,
  speed: <><path d="M4 16a8 8 0 1 1 16 0M12 16l4-6M4 20h16"/></>,
  supports: <><path d="m4 7 8-5 8 5-8 5-8-5ZM4 12l8 5 8-5M8 16v6m8-6v6"/></>,
  multifilament: <><circle cx="7" cy="7" r="3"/><circle cx="17" cy="7" r="3"/><path d="M7 10v4l5 5 5-5v-4M12 19v3"/></>,
  others: <><circle cx="12" cy="12" r="3"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2m0-14-2 2M7 17l-2 2"/></>,
};

export default function SlicerUiIcon({ name, size = 19 }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width={size} height={size}
    fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
    strokeLinejoin="round" className="slicerUiIcon">{paths[name] || paths.others}</svg>;
}
