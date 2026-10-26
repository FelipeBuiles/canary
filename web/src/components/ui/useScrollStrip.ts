import { useCallback, useEffect, useState } from "react";

export type Edges = { before: boolean; after: boolean };

/**
 * A horizontal strip that says when it holds more than fits and lets any
 * pointer reach it: an edge fade and an arrow on each side with hidden
 * items, and a plain mouse wheel scrolls it sideways. Touch keeps its swipe.
 */
export function useScrollStrip<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [edges, setEdges] = useState<Edges>({ before: false, after: false });
  const attach = useCallback((element: T | null) => setNode(element), []);

  useEffect(() => {
    if (!node) return;
    const measure = () => {
      // One pixel of slack absorbs subpixel widths at fractional zoom.
      const before = node.scrollLeft > 1;
      const after = node.scrollLeft + node.clientWidth < node.scrollWidth - 1;
      setEdges((current) => current.before === before && current.after === after ? current : { before, after });
    };
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
      const max = node.scrollWidth - node.clientWidth;
      // At either end the page scrolls on as usual.
      if (max <= 1 || (event.deltaY < 0 ? node.scrollLeft <= 0 : node.scrollLeft >= max - 1)) return;
      event.preventDefault();
      node.scrollLeft += event.deltaY * (event.deltaMode === 1 ? 16 : 1);
    };
    measure();
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    resize?.observe(node);
    const mutations = typeof MutationObserver === "undefined" ? null : new MutationObserver(measure);
    mutations?.observe(node, { childList: true, subtree: true });
    node.addEventListener("scroll", measure, { passive: true });
    node.addEventListener("load", measure, true);
    node.addEventListener("wheel", wheel, { passive: false });
    return () => {
      resize?.disconnect();
      mutations?.disconnect();
      node.removeEventListener("scroll", measure);
      node.removeEventListener("load", measure, true);
      node.removeEventListener("wheel", wheel);
    };
  }, [node]);

  const page = useCallback((direction: -1 | 1) => {
    if (!node) return;
    const smooth = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    node.scrollBy?.({ left: direction * Math.max(node.clientWidth * 0.8, 120), behavior: smooth ? "smooth" : "auto" });
  }, [node]);

  return { attach, element: node, ...edges, page };
}

/** What the controls need from a strip: which sides hide items, and a way to page. */
export type ScrollStrip = Edges & { page: (direction: -1 | 1) => void };
