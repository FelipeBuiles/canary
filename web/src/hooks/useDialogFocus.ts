import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

interface DialogEntry {
  element: HTMLElement;
  close: () => void;
  opener: HTMLElement | null;
}

const dialogs: DialogEntry[] = [];
const inerted = new Map<HTMLElement, boolean>();
let unlockBody: (() => void) | undefined;
const focusSelector = 'button, a[href], input, select, textarea, summary, [tabindex], [contenteditable="true"]';

function available(element: HTMLElement) {
  if (element.matches(':disabled, [aria-disabled="true"]') || element.closest('[inert], [hidden], [aria-hidden="true"]')) return false;
  if (typeof element.checkVisibility === "function" && !element.checkVisibility({ visibilityProperty: true })) return false;
  for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
    const style = getComputedStyle(ancestor);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (ancestor instanceof HTMLDetailsElement && !ancestor.open) {
      const summary = ancestor.querySelector(":scope > summary");
      if (!summary?.contains(element)) return false;
    }
  }
  return true;
}

function targets(element: HTMLElement) {
  return Array.from(element.querySelectorAll<HTMLElement>(focusSelector)).filter((target) => target.tabIndex >= 0 && available(target));
}

function updateBackground() {
  for (const [element, previous] of inerted) element.inert = previous;
  inerted.clear();
  let branch = dialogs.at(-1)?.element;
  while (branch && branch !== document.body) {
    const parent = branch.parentElement;
    if (!parent) break;
    for (const sibling of parent.children) {
      if (sibling instanceof HTMLElement && sibling !== branch) {
        inerted.set(sibling, sibling.inert);
        sibling.inert = true;
      }
    }
    branch = parent;
  }
}

/** Shared modal lifecycle. Portaled controls should portal into their owning dialog. */
export function useDialogFocus(
  ref: RefObject<HTMLElement | null>,
  { enabled = true, onClose, initialFocusRef }: {
    enabled?: boolean;
    onClose: () => void;
    initialFocusRef?: RefObject<HTMLElement | null>;
  },
): void {
  const closeRef = useRef(onClose);
  useLayoutEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const element = ref.current;
    if (!enabled || !element) return;
    const entry: DialogEntry = {
      element,
      close: () => closeRef.current(),
      opener: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    };
    const childIndex = dialogs.findIndex((dialog) => element.contains(dialog.element));
    if (childIndex < 0) dialogs.push(entry);
    else dialogs.splice(childIndex, 0, entry);
    element.dataset.dialogScope = "";
    const previousTabIndex = element.getAttribute("tabindex");
    if (previousTabIndex === null) element.tabIndex = -1;
    if (!unlockBody) {
      const { overflow, position, top, width } = document.body.style;
      const scrollY = window.scrollY;
      document.body.style.overflow = "hidden";
      document.body.style.position = "fixed";
      document.body.style.top = `-${scrollY}px`;
      document.body.style.width = "100%";
      unlockBody = () => {
        Object.assign(document.body.style, { overflow, position, top, width });
        if (scrollY) window.scrollTo({ top: scrollY, behavior: "instant" });
      };
    }
    updateBackground();
    function focusSafe() {
      const preferred = initialFocusRef?.current;
      (preferred && available(preferred) ? preferred : targets(element!)[0] ?? element)?.focus({ preventScroll: true });
    }
    if (dialogs.at(-1) === entry) focusSafe();
    function onKey(event: KeyboardEvent) {
      if (dialogs.at(-1) !== entry || event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        entry.close();
      } else if (event.key === "Tab") {
        const focusable = targets(element!);
        const active = document.activeElement;
        const index = focusable.indexOf(active as HTMLElement);
        if (!focusable.length || index < 0 || (event.shiftKey ? index === 0 : index === focusable.length - 1)) {
          event.preventDefault();
          (event.shiftKey ? focusable.at(-1) : focusable[0])?.focus();
          if (!focusable.length) element?.focus();
        }
      }
    }
    function onFocus(event: FocusEvent) {
      if (dialogs.at(-1) === entry && !element?.contains(event.target as Node)) focusSafe();
    }
    window.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocus);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocus);
      const wasTop = dialogs.at(-1) === entry;
      dialogs.splice(dialogs.indexOf(entry), 1);
      delete element.dataset.dialogScope;
      if (previousTabIndex === null) element.removeAttribute("tabindex");
      updateBackground();
      if (!dialogs.length) {
        unlockBody?.();
        unlockBody = undefined;
      }
      if (wasTop) {
        if (entry.opener?.isConnected && available(entry.opener)) entry.opener.focus({ preventScroll: true });
        else dialogs.at(-1)?.element.focus({ preventScroll: true });
      }
    };
  }, [enabled, ref, initialFocusRef]);
}
