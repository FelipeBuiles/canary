import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { cn } from "../../lib/cn";

interface EditableTextProps {
  value: string;
  onSave: (newValue: string) => void;
  multiline?: boolean;
  className?: string;
  inputClassName?: string;
}

export function EditableText({
  value,
  onSave,
  multiline = false,
  className,
  inputClassName,
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
      "w-full border-[2px] border-ink-black bg-white px-2 py-1 text-sm outline-none",
      multiline && "resize-y",
      inputClassName,
    );
    return multiline ? (
      <textarea
        ref={ref as React.RefObject<HTMLTextAreaElement>}
        className={inputClasses}
        rows={4}
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

  return (
    <span
      className={cn("cursor-text hover:bg-ink-black/5 rounded-sm transition-colors", className)}
      onClick={() => {
        setDraft(value);
        setEditing(true);
      }}
    >
      {value || <em className="text-ink-black/40 text-[0.78rem]">click to edit</em>}
    </span>
  );
}
