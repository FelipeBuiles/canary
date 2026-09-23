/* eslint-disable react-refresh/only-export-components */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { cn } from "../../lib/cn";

/*
 * Print-physics motion shared by checkpoints. Every animation starts from an
 * oversize or offset state and ends on the element's resting style, so the
 * global reduced-motion rule in index.css shows the final state immediately.
 */

/**
 * True once `flag` turns on after mount, until `settle()` is called. Work that
 * was already done when the view opened stays still; work that lands while
 * the author watches gets its moment.
 */
export function useArrival(flag: boolean) {
  const [arrived, setArrived] = useState(false);
  const previous = useRef(flag);
  useEffect(() => {
    const was = previous.current;
    previous.current = flag;
    if (was || !flag) return;
    const timer = window.setTimeout(() => setArrived(true), 0);
    return () => window.clearTimeout(timer);
  }, [flag]);
  return { arrived, settle: () => setArrived(false) };
}

/** A 5-frame platen press (1.08 → 1) whenever `trigger` changes after mount. */
export function usePress(trigger: unknown) {
  const [pressing, setPressing] = useState(false);
  const previous = useRef(trigger);
  useEffect(() => {
    if (Object.is(previous.current, trigger)) return;
    previous.current = trigger;
    const timer = window.setTimeout(() => setPressing(true), 0);
    return () => window.clearTimeout(timer);
  }, [trigger]);
  return {
    className: pressing ? "animate-press-seat" : "",
    onAnimationEnd: () => setPressing(false),
  };
}

/** A rubber stamp: slams in when `play` is true, otherwise rests as a badge. */
export function Stamp({
  children,
  play = false,
  rotate = -6,
  tone = "red",
  className,
  onSettled,
}: {
  children: ReactNode;
  play?: boolean;
  rotate?: number;
  tone?: "red" | "ink";
  className?: string;
  onSettled?: () => void;
}) {
  return (
    <span
      className={cn("stamp", tone === "red" ? "stamp-red" : "stamp-ink", play && "animate-stamp-slam", className)}
      style={{ "--stamp-rotate": `${rotate}deg` } as CSSProperties}
      onAnimationEnd={onSettled}
    >
      {children}
    </span>
  );
}
