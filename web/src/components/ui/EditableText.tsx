import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { cn } from "../../lib/cn";

interface EditableTextProps {
  value: string;
  onSave: (newValue: string) => void;
  multiline?: boolean;
  className?: string;
  inputClassName?: string;
  highlightFrom?: string | null;
  highlightActive?: boolean;
}

function getChangedSlice(previous: string, current: string): { start: number; end: number } | null {
  if (previous === current) return null;
  let start = 0;
  const minLen = Math.min(previous.length, current.length);
  while (start < minLen && previous[start] === current[start]) start += 1;

  let prevEnd = previous.length - 1;
  let currEnd = current.length - 1;
  while (prevEnd >= start && currEnd >= start && previous[prevEnd] === current[currEnd]) {
    prevEnd -= 1;
    currEnd -= 1;
  }
  return { start, end: currEnd + 1 };
}

export function EditableText({
  value,
  onSave,
  multiline = false,
  className,
  inputClassName,
  highlightFrom,
  highlightActive = false,
}: EditableTextProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const ref = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editing) return;
    ref.current?.focus();
    ref.current?.setSelectionRange(ref.current.value.length, ref.current.value.length);
  }, [editing]);

  useEffect(() => {
    if (!editing || !multiline) return;
    const el = ref.current as HTMLTextAreaElement | null;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, 40)}px`;
  }, [editing, multiline, draft]);

  const save = () => {
    setEditing(false);
    if (draft !== value) onSave(draft);
  };

  const revert = () => {
    setEditing(false);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !multiline) {
      e.preventDefault();
      save();
    }
    if (e.key === "Enter" && multiline && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      save();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      revert();
    }
  };

  const changedSlice = highlightActive && highlightFrom != null
    ? getChangedSlice(highlightFrom, value)
    : null;

  const renderValue = () => {
    if (!value) return <em className="text-ink-black/40 text-[0.78rem]">click to edit</em>;
    if (!changedSlice || changedSlice.start >= changedSlice.end) return value;
    return (
      <>
        {value.slice(0, changedSlice.start)}
        <span className="diff-highlight">{value.slice(changedSlice.start, changedSlice.end)}</span>
        {value.slice(changedSlice.end)}
      </>
    );
  };

  const sharedWrapperClasses = cn(
    "min-w-0 cursor-text transition-colors",
    multiline ? "block whitespace-pre-wrap" : "inline-block max-w-full align-baseline",
    className,
  );

  if (editing) {
    const inputClasses = cn(
      "min-w-0 border-[2px] border-ink-black bg-bristol px-2 py-1 text-inherit outline-none shadow-none",
      "focus:shadow-[inset_0_-3px_0_0_var(--color-hero-red)]",
      multiline
        ? "block w-full resize-none overflow-hidden whitespace-pre-wrap break-words [line-height:inherit]"
        : "inline-block w-full max-w-full [line-height:inherit]",
      inputClassName,
    );

    return (
      <span className={sharedWrapperClasses}>
        {multiline ? (
          <textarea
            ref={ref as React.RefObject<HTMLTextAreaElement>}
            className={inputClasses}
            rows={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={save}
            onKeyDown={handleKeyDown}
          />
        ) : (
          <input
            ref={ref as React.RefObject<HTMLInputElement>}
            className={inputClasses}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={save}
            onKeyDown={handleKeyDown}
          />
        )}
      </span>
    );
  }

  return (
    <span
      className={sharedWrapperClasses}
      onClick={() => {
        setDraft(value);
        setEditing(true);
      }}
    >
      {renderValue()}
    </span>
  );
}
