import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDesktopLayout } from "../hooks/useDesktopLayout";

interface ShellSlotsContextValue {
  topEl: HTMLElement | null;
  setTopEl: (el: HTMLElement | null) => void;
  bottomEl: HTMLElement | null;
  setBottomEl: (el: HTMLElement | null) => void;
}

const ShellSlotsContext = createContext<ShellSlotsContextValue | null>(null);

/** Wraps the shell so pages can project content into the masthead and footer. */
export function TopBarSlotProvider({ children }: { children: ReactNode }) {
  const [topEl, setTopEl] = useState<HTMLElement | null>(null);
  const [bottomEl, setBottomEl] = useState<HTMLElement | null>(null);
  return (
    <ShellSlotsContext.Provider value={{ topEl, setTopEl, bottomEl, setBottomEl }}>
      {children}
    </ShellSlotsContext.Provider>
  );
}

/** Used by AppTopBar to register the DOM node that receives portaled content. */
// eslint-disable-next-line react-refresh/only-export-components
export function useTopBarSlotRegister() {
  const ctx = useContext(ShellSlotsContext);
  return ctx?.setTopEl;
}

/**
 * Renders children into the masthead slot of AppTopBar. Pages own their
 * header content (kicker, title, tabs, actions); the shell owns the bar.
 */
export function TopBarPortal({ children, inlineOnMobile = false }: { children: ReactNode; inlineOnMobile?: boolean }) {
  const ctx = useContext(ShellSlotsContext);
  const desktop = useDesktopLayout();
  if (!ctx || (inlineOnMobile && !desktop)) return children;
  if (!ctx?.topEl) return null;
  return createPortal(children, ctx.topEl);
}

/** The shell-owned footer host: a zero-height div until a page portals into it. */
export function BottomBarHost() {
  const ctx = useContext(ShellSlotsContext);
  return <div ref={ctx?.setBottomEl} className="shrink-0" />;
}

/**
 * Desktop actions use the standing shell footer. Phone actions stay in the
 * page's scroll flow so review content can use the full viewport.
 */
export function BottomBarPortal({ children }: { children: ReactNode }) {
  const ctx = useContext(ShellSlotsContext);
  const desktop = useDesktopLayout();
  // Rooms remain independently renderable in tests, component references,
  // and embedded surfaces that do not mount the full application shell.
  if (!ctx || !desktop) return children;
  if (!ctx?.bottomEl) return null;
  return createPortal(children, ctx.bottomEl);
}
