import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/cn";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
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
  sm: "min-h-8 gap-2 px-3 py-1.5 font-meta text-[0.62rem] tracking-[0.1em]",
  md: "min-h-10 gap-3 px-3 py-2 font-body text-[0.85rem]",
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
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; width: number } | null>(null);

  const selected = options.find((o) => o.value === value);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const menuHeight = Math.min(options.length * 36 + 4, 288);
    const openUp = rect.bottom + menuHeight + 8 > window.innerHeight && rect.top > menuHeight;
    setMenuPos({
      top: openUp ? rect.top - menuHeight - 4 : rect.bottom + 4,
      left: Math.min(rect.left, window.innerWidth - Math.max(rect.width, 180) - 8),
      width: Math.max(rect.width, 180),
    });
    setHighlighted(Math.max(0, options.findIndex((o) => o.value === value)));
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
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  function commit(index: number) {
    const option = options[index];
    if (!option) return;
    setOpen(false);
    triggerRef.current?.focus();
    if (option.value !== value) onValueChange(option.value);
  }

  function onTriggerKeyDown(event: KeyboardEvent) {
    if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
    }
  }

  function onMenuKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted((i) => Math.min(i + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((i) => Math.max(i - 1, 0));
    } else if (event.key === "Home") {
      event.preventDefault();
      setHighlighted(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setHighlighted(options.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      commit(highlighted);
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onTriggerKeyDown}
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

      {open && menuPos &&
        createPortal(
          <div
            ref={menuRef}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel}
            onKeyDown={onMenuKeyDown}
            style={{ position: "fixed", top: menuPos.top, left: menuPos.left, minWidth: menuPos.width }}
            className="z-[70] max-h-72 overflow-y-auto border-[2px] border-ink-black bg-bristol shadow-ink-sm"
          >
            {options.map((option, index) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                onClick={() => commit(index)}
                onPointerMove={() => setHighlighted(index)}
                ref={(el) => {
                  if (el && index === highlighted && open) el.focus({ preventScroll: true });
                }}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left font-body text-[0.82rem] outline-none transition-colors",
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
          document.body,
        )}
    </>
  );
}
