import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

/**
 * Native swipe navigation with controls that reflect actual scroll overflow,
 * not a guessed viewport width. Desktop retains the existing vertical nav.
 */
export default function ResponsiveNav({ items, selected, onSelect, isDisabled, getTitle }) {
  const scrollRef = useRef(null);
  const [edges, setEdges] = useState({ left: false, right: false });

  useEffect(() => {
    const nav = scrollRef.current;
    if (!nav) return undefined;
    const update = () => {
      const max = Math.max(0, nav.scrollWidth - nav.clientWidth);
      setEdges(previous => {
        const left = nav.scrollLeft > 2;
        const right = nav.scrollLeft < max - 2;
        return previous.left === left && previous.right === right
          ? previous : { left, right };
      });
    };
    update();
    nav.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(update) : null;
    observer?.observe(nav);
    for (const child of nav.children) observer?.observe(child);
    window.addEventListener("resize", update);
    return () => {
      nav.removeEventListener("scroll", update);
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [items]);

  useLayoutEffect(() => {
    const nav = scrollRef.current;
    const active = [...(nav?.children || [])].find(item => item.getAttribute("aria-current") === "page");
    if (!nav || !active || window.matchMedia("(min-width: 901px)").matches) return;
    const view = nav.getBoundingClientRect();
    const target = active.getBoundingClientRect();
    if (target.left < view.left) nav.scrollLeft -= view.left - target.left + 6;
    else if (target.right > view.right) nav.scrollLeft += target.right - view.right + 6;
  }, [selected]);

  const move = direction => {
    const nav = scrollRef.current;
    if (!nav) return;
    nav.scrollBy({
      left: direction * Math.max(100, nav.clientWidth * 0.72),
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    });
  };

  return <div className="mobileNavOverflow">
    <button type="button" className={"mobileNavArrow mobileNavArrowLeft" + (edges.left ? " isVisible" : "")}
      disabled={!edges.left} aria-hidden={!edges.left} tabIndex={edges.left ? 0 : -1}
      aria-label="Show previous navigation options" onClick={() => move(-1)}>
      <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m14 5-7 7 7 7"/></svg>
    </button>
    <nav ref={scrollRef} aria-label="Main navigation">
      {items.map(name => <button key={name} className={selected === name ? "active" : ""}
        aria-current={selected === name ? "page" : undefined}
        disabled={isDisabled?.(name)}
        title={getTitle?.(name)}
        onClick={() => onSelect(name)}>{name}</button>)}
    </nav>
    <button type="button" className={"mobileNavArrow mobileNavArrowRight" + (edges.right ? " isVisible" : "")}
      disabled={!edges.right} aria-hidden={!edges.right} tabIndex={edges.right ? 0 : -1}
      aria-label="Show more navigation options" onClick={() => move(1)}>
      <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m10 5 7 7-7 7"/></svg>
    </button>
  </div>;
}
