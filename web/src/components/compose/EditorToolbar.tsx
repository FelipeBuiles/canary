import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";

interface EditorToolbarProps {
  onAddBubble: (type: "speech" | "thought" | "narration") => void;
  onAddSfx: () => void;
  onDelete: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onExport: (format: "pdf" | "cbz") => void;
  hasSelection: boolean;
  canUndo: boolean;
  canRedo: boolean;
  isExporting: boolean;
  zoomPercent: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
}

export function EditorToolbar({
  onAddBubble,
  onAddSfx,
  onDelete,
  onUndo,
  onRedo,
  onExport,
  hasSelection,
  canUndo,
  canRedo,
  isExporting,
  zoomPercent,
  onZoomIn,
  onZoomOut,
  onZoomReset,
}: EditorToolbarProps) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-3 border-[2px] border-ink-black bg-bristol px-4 py-3">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => onAddBubble("speech")}>
          + {t("SPEECH")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onAddBubble("thought")}>
          + {t("THOUGHT")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onAddBubble("narration")}>
          + {t("NARRATION")}
        </Button>
        <Button size="sm" variant="secondary" onClick={onAddSfx}>
          + SFX
        </Button>
      </div>

      <div className="mx-1 h-6 w-px bg-ink-black/20" />

      <Button size="sm" variant="outline" onClick={onDelete} disabled={!hasSelection}>
        {t("DELETE")}
      </Button>

      <div className="mx-1 h-6 w-px bg-ink-black/20" />

      <Button size="sm" variant="outline" onClick={onUndo} disabled={!canUndo}>
        {t("UNDO")}
      </Button>
      <Button size="sm" variant="outline" onClick={onRedo} disabled={!canRedo}>
        {t("REDO")}
      </Button>

      <div className="mx-1 h-6 w-px bg-ink-black/20" />

      <div className="flex items-center gap-1">
        <Button size="sm" variant="outline" onClick={onZoomOut} aria-label={t("ZOOM OUT")}>
          −
        </Button>
        <Button size="sm" variant="outline" onClick={onZoomReset}>
          {Math.round(zoomPercent)}%
        </Button>
        <Button size="sm" variant="outline" onClick={onZoomIn} aria-label={t("ZOOM IN")}>
          +
        </Button>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={() => onExport("pdf")}
          disabled={isExporting}
        >
          {isExporting ? t("EXPORTING...") : t("EXPORT PDF")}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onExport("cbz")}
          disabled={isExporting}
        >
          CBZ
        </Button>
      </div>
    </div>
  );
}
