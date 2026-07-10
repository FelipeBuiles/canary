import { useEffect } from "react";
import { ShortcutHint } from "../ui/ShortcutHint";

interface ExportBurstProps {
  pageCount: number;
  format: "pdf" | "cbz";
  downloadUrl: string;
  onDismiss: () => void;
}

export function ExportBurst({ pageCount, format, downloadUrl, onDismiss }: ExportBurstProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onDismiss();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  return (
    <div
      className="fixed inset-0 z-[140] flex items-center justify-center bg-ink-black/40 px-4"
      onClick={onDismiss}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-burst-title"
        onClick={(e) => e.stopPropagation()}
        className="animate-comic-pop relative w-full max-w-[420px] border-[2px] border-ink-black bg-narrator-gold text-ink-black shadow-ink"
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <span className="font-meta text-[0.56rem] tracking-[0.22em] uppercase text-ink-black/55">
            EXPORT COMPLETE
          </span>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss"
            className="inline-flex min-h-11 shrink-0 items-center gap-2 border-[2px] border-ink-black/25 px-3 font-meta text-[0.6rem] tracking-[0.12em] uppercase text-ink-black/60 hover:border-ink-black hover:text-ink-black"
          >
            Close <ShortcutHint>Esc</ShortcutHint>
          </button>
        </div>

        <div className="px-6 pb-6 pt-2">
          <h2
            id="export-burst-title"
            className="font-display text-[2rem] font-black leading-[0.95] tracking-[-0.02em] uppercase"
          >
            HOT OFF THE PRESS
          </h2>
          <p className="mt-2 font-meta text-[0.62rem] tracking-[0.2em] uppercase text-ink-black/65">
            ISSUE READY — {pageCount} {pageCount === 1 ? "PAGE" : "PAGES"}
          </p>

          <a
            href={downloadUrl}
            download
            target="_blank"
            rel="noopener noreferrer"
            className="mt-5 inline-flex min-h-11 items-center justify-center gap-2 border-[2px] border-ink-black bg-ink-black px-5 font-meta text-[0.72rem] tracking-[0.16em] uppercase text-narrator-gold shadow-paper-sm transition-[box-shadow,transform] duration-150 hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm active:translate-x-[3px] active:translate-y-[3px] active:shadow-none"
          >
            DOWNLOAD {format.toUpperCase()} ↓
          </a>
        </div>
      </div>
    </div>
  );
}
