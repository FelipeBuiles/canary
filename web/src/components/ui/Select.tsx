import { useEffect, useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "value" | "onChange" | "size"> {
  value: string;
  options: SelectOption[];
  onValueChange: (value: string) => void;
  disabled?: boolean;
  /** "light" sits on paper surfaces; "dark" sits on ink (sidebar, mobile nav). */
  tone?: "light" | "dark";
  size?: "sm" | "md";
  className?: string;
  id?: string;
  "aria-label"?: string;
}

const TRIGGER_TONE = {
  light:
    "border-ink-black/20 bg-bristol text-ink-black hover:border-ink-black aria-expanded:border-ink-black",
  dark:
    "border-bristol/25 bg-ink-black text-bristol hover:border-bristol/60 aria-expanded:border-bristol",
};

const TRIGGER_SIZE = {
  sm: "min-h-11 gap-2 px-3 py-1.5 font-meta text-xs tracking-[0.08em]",
  md: "min-h-11 gap-3 px-3 py-2 font-body text-sm",
};

/**
 * The print-shop replacement for a native <select>: same listbox semantics,
 * but the menu is a stamped bristol panel instead of the system dropdown.
 * The menu renders through a portal at a fixed position so it never clips
 * inside overflow containers.
 */
export function Select({
  value,
  options,
  onValueChange,
  disabled,
  tone = "light",
  size = "md",
  className,
  id,
  "aria-label": ariaLabel,
  onClick,
  onKeyDown,
  ...triggerProps
}: SelectProps) {
  const menuId = useId();
  const typeahead = useRef({ text: "", time: 0 });
  const [open, setOpen] = useState(false);
  const [portalRoot, setPortalRoot] = useState<HTMLElement | null>(null);
  const [highlighted, setHighlighted] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; width: number } | null>(null);

  const selected = options.find((o) => o.value === value);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const menuHeight = Math.min(options.length * 44 + 4, 288);
    const openUp = rect.bottom + menuHeight + 8 > window.innerHeight && rect.top > menuHeight;
    setMenuPos({
      top: openUp ? rect.top - menuHeight - 4 : rect.bottom + 4,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - Math.max(rect.width, 180) - 8)),
      width: Math.min(Math.max(rect.width, 180), window.innerWidth - 16),
    });
    const selectedIndex = options.findIndex((o) => o.value === value && !o.disabled);
    setHighlighted(selectedIndex >= 0 ? selectedIndex : options.findIndex((o) => !o.disabled));
  }, [open, options, value]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setOpen(false);
      }
    }
    function onScroll(event: Event) {
      if (menuRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }
    function onResize() {
      setOpen(false);
    }
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  function commit(index: number) {
    const option = options[index];
    if (!option || option.disabled) return;
    setOpen(false);
    triggerRef.current?.focus();
    if (option.value !== value) onValueChange(option.value);
  }

  function matchTypeahead(event: KeyboardEvent) {
    if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
    const now = Date.now();
    const previous = now - typeahead.current.time < 700 ? typeahead.current.text : "";
    const text = previous + event.key.toLocaleLowerCase();
    typeahead.current = { text, time: now };
    const search = [...text].every((character) => character === text[0]) ? text[0] : text;
    const start = search.length === 1 ? highlighted + 1 : highlighted;
    for (let offset = 0; offset < options.length; offset++) {
      const index = (Math.max(0, start) + offset) % options.length;
      if (!options[index].disabled && options[index].label.toLocaleLowerCase().startsWith(search)) {
        event.preventDefault();
        if (open) setHighlighted(index);
        else commit(index);
        break;
      }
    }
  }
  function openMenu() {
    setPortalRoot(triggerRef.current?.closest<HTMLElement>("[data-dialog-scope]") ?? document.body);
    setOpen(true);
  }

  function onTriggerKeyDown(event: KeyboardEvent) {
    if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      openMenu();
    }
    else matchTypeahead(event);
  }

  function onMenuKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted((i) => options.findIndex((option, index) => index > i && !option.disabled) === -1 ? i : options.findIndex((option, index) => index > i && !option.disabled));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((i) => options.reduce((last, option, index) => index < i && !option.disabled ? index : last, i));
    } else if (event.key === "Home") {
      event.preventDefault();
      setHighlighted(options.findIndex((option) => !option.disabled));
    } else if (event.key === "End") {
      event.preventDefault();
      setHighlighted(options.reduce((last, option, index) => !option.disabled ? index : last, -1));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      commit(highlighted);
    } else if (event.key === "Tab") {
      setOpen(false);
      triggerRef.current?.focus();
    } else matchTypeahead(event);
  }

  return (
    <>
      <button
        {...triggerProps}
        ref={triggerRef}
        type="button"
        id={id}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={ariaLabel}
        onClick={(event) => { onClick?.(event); if (!event.defaultPrevented) { if (open) setOpen(false); else openMenu(); } }}
        onKeyDown={(event) => { onKeyDown?.(event); if (!event.defaultPrevented) onTriggerKeyDown(event); }}
        className={cn(
          "inline-flex min-w-0 cursor-pointer items-center justify-between border-[2px] text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
          TRIGGER_TONE[tone],
          TRIGGER_SIZE[size],
          className,
        )}
      >
        <span className="min-w-0 truncate">{selected?.label ?? "—"}</span>
        <span aria-hidden className={cn("shrink-0 text-[0.6em] transition-transform", open && "rotate-180")}>
          ▼
        </span>
      </button>

      {open && menuPos && portalRoot &&
        createPortal(
          <div
            ref={menuRef}
            id={menuId}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel}
            onKeyDown={onMenuKeyDown}
            style={{ position: "fixed", top: menuPos.top, left: menuPos.left, minWidth: menuPos.width }}
            className="z-[200] max-h-72 overflow-y-auto border-[2px] border-ink-black bg-bristol shadow-ink-sm"
          >
            {options.map((option, index) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                disabled={option.disabled}
                tabIndex={index === highlighted ? 0 : -1}
                onClick={() => commit(index)}
                onPointerMove={() => !option.disabled && setHighlighted(index)}
                ref={(el) => {
                  if (el && index === highlighted && open) {
                    el.focus({ preventScroll: true });
                    el.scrollIntoView?.({ block: "nearest" });
                  }
                }}
                className={cn(
                  "flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left font-body text-sm outline-none transition-colors disabled:opacity-50",
                  option.value === value
                    ? "bg-ink-black text-bristol"
                    : index === highlighted
                      ? "bg-surface-container text-ink-black"
                      : "text-ink-black/75",
                )}
              >
                <span
                  aria-hidden
                  className={cn("h-[7px] w-[7px] shrink-0", option.value === value ? "bg-hero-red" : "bg-transparent")}
                />
                <span className="min-w-0 flex-1 truncate">{option.label}</span>
              </button>
            ))}
          </div>,
          portalRoot,
        )}
    </>
  );
}
