import React from "react";

export function Modal({ title, subtitle, onClose, children, wide = false }) {
  return <div className="modalBackdrop" role="presentation" onMouseDown={e => {
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
}

export function BoardImage({ src, alt = "", size = "normal" }) {
  return <div className={`boardImage boardImage-${size}`}>
    {src ? <img src={src} alt={alt} loading="lazy" /> : <span>MCU</span>}
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
