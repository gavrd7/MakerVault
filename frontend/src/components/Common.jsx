import React, { useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "../api";

export function Modal({ title, subtitle, onClose, children, wide = false }) {
  const modal = <div className="modalBackdrop" role="presentation" onMouseDown={e => {
    if (e.target === e.currentTarget) onClose();
  }}>
    <section className={`modal ${wide ? "modalWide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
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
  return <div className={`boardImage boardImage-${size}`}>
    {src ? <img src={src} alt={alt} loading="lazy" /> : <span>{placeholder}</span>}
  </div>;
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
