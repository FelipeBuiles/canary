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
  const [draft, setDraft] = useState(value);
  const ref = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing) ref.current?.focus();
  }, [editing]);

  // Sync draft when value prop changes (e.g. after save + refetch)
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (!editing || !multiline) return;
    const el = ref.current as HTMLTextAreaElement | null;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.max(el.scrollHeight, 56)}px`;
  }, [editing, multiline, draft, value]);

  const save = () => {
    setEditing(false);
    if (draft !== value) onSave(draft);
  };

  const revert = () => {
    setDraft(value);
    setEditing(false);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !multiline) {
      e.preventDefault();
      save();
    }
    if (e.key === "Escape") {
      revert();
    }
  };

  if (editing) {
    const inputClasses = cn(
      "w-full rounded-sm border-[2px] border-ink-black bg-white px-2 py-1 outline-none",
      multiline && "block overflow-hidden resize-none",
      className,
      inputClassName,
    );
    return multiline ? (
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
    );
  }

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

  return (
    <span
      className={cn(
        "cursor-text hover:bg-ink-black/5 rounded-sm transition-colors",
        multiline && "whitespace-pre-wrap",
        className,
      )}
      onClick={() => {
        setDraft(value);
        setEditing(true);
      }}
    >
      {renderValue()}
    </span>
  );
}
