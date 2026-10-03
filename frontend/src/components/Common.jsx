import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "../api";

export function Modal({ title, subtitle, onClose, children, wide = false, className = "" }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    const previous = document.activeElement;
    const dialog = dialogRef.current;
    const focusable = dialog?.querySelector(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    focusable?.focus();

    function keydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const items = [...dialog.querySelectorAll(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )].filter(element => element.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [onClose]);

  const modal = <div className="modalBackdrop" role="presentation" onMouseDown={e => {
    if (e.target === e.currentTarget) onClose();
  }}>
    <section ref={dialogRef} className={`modal ${wide ? "modalWide" : ""} ${className}`.trim()} role="dialog" aria-modal="true" aria-label={title}>
      <div className="modalHead">
        <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
        <button type="button" className="iconButton" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="modalBody">{children}</div>
    </section>
  </div>;
  return createPortal(modal, document.body);
}

export function BoardImage({ src, alt = "", size = "normal", placeholder = "MCU" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return <div className={`boardImage boardImage-${size}`}>
    {src && !failed
      ? <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />
      : <span>{placeholder}</span>}
  </div>;
}

const COMPONENT_ARTWORK = [
  { match: ["speaker", "buzzer"], glyph: "◖))", label: "Audio output" },
  { match: ["microphone", "audio-player", "amplifier"], glyph: "◉♪", label: "Audio module" },
  { match: ["button", "switch", "encoder", "joystick", "keypad", "touch", "potentiometer", "trimmer"], glyph: "⌁", label: "Control" },
  { match: ["sensor", "temperature", "humidity", "pressure", "imu", "accelerometer", "gyroscope", "load-cell"], glyph: "◌", label: "Sensor" },
  { match: ["display", "oled", "lcd", "matrix"], glyph: "▣", label: "Display" },
  { match: ["relay", "mosfet", "transistor", "diode", "regulator", "buck", "boost", "battery", "power", "charger", "bms"], glyph: "ϟ", label: "Power" },
  { match: ["connector", "header", "terminal", "usb", "uart", "rs232", "rs485"], glyph: "↔", label: "Connector" },
  { match: ["wifi", "bluetooth", "zigbee", "lora", "radio", "nfc", "rfid", "communications"], glyph: "⌁)", label: "Communications" },
  { match: ["led", "neopixel", "rgb"], glyph: "✦", label: "Lighting" },
  { match: ["resistor"], glyph: "—/\/—", label: "Resistor" },
  { match: ["capacitor"], glyph: "—| |—", label: "Capacitor" },
  { match: ["fan"], glyph: "✣", label: "Fan" },
  { match: ["motor", "servo", "stepper"], glyph: "⟳", label: "Motor" },
  { match: ["fastener", "screw", "insert", "magnet", "mechanical"], glyph: "⬡", label: "Mechanical" },
];

export function ComponentArtwork({ src, alt = "", size = "normal", type = "", category = "", partNumber = "" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  if (src && !failed) {
    return <div className={`boardImage boardImage-${size}`}>
      <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />
    </div>;
  }

  const haystack = `${type} ${category} ${partNumber} ${alt}`.toLowerCase();
  const artwork = COMPONENT_ARTWORK.find(entry => entry.match.some(term => haystack.includes(term)))
    || { glyph: "◇", label: category || "Component" };
  return <div className={`boardImage boardImage-${size} componentArtwork`} role="img" aria-label={`${artwork.label} generic artwork`}>
    <span className="componentArtworkGlyph" aria-hidden="true">{artwork.glyph}</span>
  </div>;
}


export function ImageViewer({ src, alt = "", title = "Image", onClose }) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef(null);
  const viewerRef = useRef(null);

  useEffect(() => {
    function keydown(event) {
      if (event.key === "Escape") onClose?.();
      if (event.key === "+" || event.key === "=") setScale(value => Math.min(8, value + 0.25));
      if (event.key === "-") setScale(value => Math.max(0.25, value - 0.25));
      if (event.key === "0") { setScale(1); setOffset({ x: 0, y: 0 }); }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [onClose]);

  if (!src) return null;

  function zoom(delta) {
    setScale(value => Math.min(8, Math.max(0.25, value + delta)));
  }

  function reset() {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }

  async function fullscreen() {
    try {
      if (!document.fullscreenElement) await viewerRef.current?.requestFullscreen?.();
      else await document.exitFullscreen?.();
    } catch {
      // Browser may deny fullscreen outside a user gesture; no further action needed.
    }
  }

  function pointerDown(event) {
    if (scale <= 1) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { x: event.clientX - offset.x, y: event.clientY - offset.y };
    setDragging(true);
  }

  function pointerMove(event) {
    if (!dragging || !dragRef.current) return;
    setOffset({ x: event.clientX - dragRef.current.x, y: event.clientY - dragRef.current.y });
  }

  function pointerUp() {
    dragRef.current = null;
    setDragging(false);
  }

  const viewer = <div className="imageViewerBackdrop" onMouseDown={event => {
    if (event.target === event.currentTarget) onClose?.();
  }}>
    <section className="imageViewer" ref={viewerRef} role="dialog" aria-modal="true" aria-label={title}>
      <div className="imageViewerToolbar">
        <strong>{title}</strong>
        <div className="imageViewerControls">
          <button type="button" onClick={() => zoom(-0.25)} aria-label="Zoom out">−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button type="button" onClick={() => zoom(0.25)} aria-label="Zoom in">＋</button>
          <button type="button" onClick={reset}>Fit</button>
          <button type="button" onClick={fullscreen}>Fullscreen</button>
          <button type="button" className="iconButton" onClick={onClose} aria-label="Close">×</button>
        </div>
      </div>
      <div
        className={`imageViewerStage ${dragging ? "dragging" : ""}`}
        onWheel={event => {
          event.preventDefault();
          zoom(event.deltaY > 0 ? -0.15 : 0.15);
        }}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerCancel={pointerUp}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
        />
      </div>
    </section>
  </div>;
  return createPortal(viewer, document.body);
}

export function Badge({ children, tone = "neutral" }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function EmptyModule({ title, children, action }) {
  return <section className="empty">
    <div className="emptyIcon">◇</div>
    <h2>{title}</h2>
    <p>{children}</p>
    {action}
  </section>;
}

export function LoadingBlock({ label = "Loading…" }) {
  return <div className="loadingBlock"><span className="spinner" /> {label}</div>;
}

export function ImageManagerModal({ title, endpoint, responseKey, currentImage, onClose, onUpdated }) {
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function uploadFile(event) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("image", file);
      const result = await apiFetch(endpoint, { method: "POST", body: form });
      onUpdated(result[responseKey]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function cacheUrl(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch(endpoint, { method: "POST", body: { url } });
      onUpdated(result[responseKey]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeImage() {
    setBusy(true);
    setError("");
    try {
      const result = await apiFetch(endpoint, { method: "DELETE" });
      onUpdated(result[responseKey]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={title} subtitle="MakerVault stores a sanitised WebP copy in local media storage. Remote URLs must be public HTTPS images." onClose={onClose} wide>
    {error && <div className="formError imageError">{error}</div>}
    <div className="imageManagerGrid">
      <section className="imageManagerPreview">
        <BoardImage src={currentImage} alt="" size="large" placeholder="IMG" />
        <p className="muted">{currentImage ? "Current catalogue image" : "No catalogue image yet"}</p>
        {currentImage && <button type="button" className="dangerButton" disabled={busy} onClick={removeImage}>Remove image</button>}
      </section>
      <section className="imageManagerForms">
        <form onSubmit={uploadFile} className="imageSourceBox">
          <h4>Upload a file</h4>
          <p>JPEG, PNG or WebP up to 8 MiB. MakerVault strips metadata and resizes oversized images.</p>
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => setFile(e.target.files?.[0] || null)} />
          <button className="primary" disabled={busy || !file}>{busy ? "Saving…" : "Upload & cache"}</button>
        </form>
        <form onSubmit={cacheUrl} className="imageSourceBox">
          <h4>Cache from image URL</h4>
          <p>Useful for manufacturer/source images. The app keeps the source URL as provenance.</p>
          <input type="url" required placeholder="https://example.com/product.webp" value={url} onChange={e => setUrl(e.target.value)} />
          <button className="primary" disabled={busy || !url.trim()}>{busy ? "Downloading…" : "Download & cache"}</button>
        </form>
      </section>
    </div>
  </Modal>;
}
