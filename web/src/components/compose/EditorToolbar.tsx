import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
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
    <div className="flex flex-wrap items-center gap-2 border-[2px] border-ink-black bg-bristol p-2 shadow-[4px_4px_0_0_var(--color-ghost-shadow)]">
      <div className="mr-1 hidden border-r-[2px] border-ink-black/15 pr-3 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45 lg:block">
        {t("LETTERING")}
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-1.5" role="group" aria-label={t("ADD LETTERING")}>
        <Button size="sm" variant="secondary" onClick={() => onAddBubble("speech")} title={t("ADD SPEECH BUBBLE")}>
          <Icon name="speech" size={14} />
          {t("SPEECH")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onAddBubble("thought")} title={t("ADD THOUGHT BUBBLE")}>
          <Icon name="thought" size={14} />
          {t("THOUGHT")}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onAddBubble("narration")} title={t("ADD NARRATION BOX")}>
          <Icon name="type" size={14} />
          {t("NARRATION")}
        </Button>
        <Button size="sm" variant="secondary" onClick={onAddSfx} title={t("ADD SOUND EFFECT")}>
          <Icon name="sparkles" size={14} />
          SFX
        </Button>
      </div>

      <div className="mx-1 hidden h-8 w-px bg-ink-black/20 sm:block" />

      <div className="flex items-center gap-1.5" role="group" aria-label={t("EDIT HISTORY")}>
        <Button size="sm" variant="outline" onClick={onDelete} disabled={!hasSelection} aria-label={t("DELETE SELECTED")} title={t("DELETE SELECTED")}>
          <Icon name="trash" size={14} />
          <span className="hidden sm:inline">{t("DELETE")}</span>
        </Button>
        <Button size="sm" variant="outline" onClick={onUndo} disabled={!canUndo} aria-label={t("UNDO")} title={t("UNDO")}>
          <Icon name="undo" size={14} />
        </Button>
        <Button size="sm" variant="outline" onClick={onRedo} disabled={!canRedo} aria-label={t("REDO")} title={t("REDO")}>
          <Icon name="redo" size={14} />
        </Button>
      </div>

      <div className="mx-1 hidden h-8 w-px bg-ink-black/20 sm:block" />

      <div className="flex items-center gap-1.5" role="group" aria-label={t("ZOOM CONTROLS")}>
        <Button size="sm" variant="outline" onClick={onZoomOut} aria-label={t("ZOOM OUT")}>
          <Icon name="zoom-out" size={14} />
        </Button>
        <Button size="sm" variant="outline" onClick={onZoomReset} title={t("RESET ZOOM")}>
          <span className="sr-only">{t("RESET ZOOM")}</span>
          {Math.round(zoomPercent)}%
        </Button>
        <Button size="sm" variant="outline" onClick={onZoomIn} aria-label={t("ZOOM IN")}>
          <Icon name="zoom-in" size={14} />
        </Button>
      </div>

      <div className="ml-auto flex items-center gap-1.5" role="group" aria-label={t("EXPORT")}>
        <Button
          size="sm"
          variant="primary"
          onClick={() => onExport("pdf")}
          disabled={isExporting}
        >
          <Icon name="pdf" size={14} />
          {isExporting ? t("EXPORTING…") : t("EXPORT PDF")}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onExport("cbz")}
          disabled={isExporting}
          aria-label={t("EXPORT CBZ")}
          title={t("EXPORT CBZ")}
        >
          <Icon name="archive" size={14} />
          CBZ
        </Button>
      </div>
    </div>
  );
}
