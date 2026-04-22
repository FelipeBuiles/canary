import { Button } from "../ui/Button";
import { ControlGroup } from "../ui/ControlGroup";
import { Icon } from "../ui/Icon";
import { IconButton } from "../ui/IconButton";
import { Surface } from "../ui/Surface";
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
    <Surface className="flex flex-wrap items-center gap-1.5 p-2 sm:gap-2" shadow="paper-sm">
      <ControlGroup label={t("LETTERING")} aria-label={t("ADD LETTERING")}>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onAddBubble("speech")}
          aria-label={t("ADD SPEECH BUBBLE")}
          title={t("ADD SPEECH BUBBLE")}
          className="px-2.5 sm:px-3.5"
        >
          <Icon name="speech" size={14} />
          <span className="hidden sm:inline">{t("SPEECH")}</span>
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onAddBubble("thought")}
          aria-label={t("ADD THOUGHT BUBBLE")}
          title={t("ADD THOUGHT BUBBLE")}
          className="px-2.5 sm:px-3.5"
        >
          <Icon name="thought" size={14} />
          <span className="hidden sm:inline">{t("THOUGHT")}</span>
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => onAddBubble("narration")}
          aria-label={t("ADD NARRATION BOX")}
          title={t("ADD NARRATION BOX")}
          className="px-2.5 sm:px-3.5"
        >
          <Icon name="type" size={14} />
          <span className="hidden sm:inline">{t("NARRATION")}</span>
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={onAddSfx}
          aria-label={t("ADD SOUND EFFECT")}
          title={t("ADD SOUND EFFECT")}
          className="px-2.5 sm:px-3.5"
        >
          <Icon name="sparkles" size={14} />
          <span className="hidden sm:inline">SFX</span>
        </Button>
      </ControlGroup>

      <ControlGroup aria-label={t("EDIT HISTORY")}>
        <Button size="sm" variant="outline" onClick={onDelete} disabled={!hasSelection} aria-label={t("DELETE SELECTED")} title={t("DELETE SELECTED")}>
          <Icon name="trash" size={14} />
          <span className="hidden sm:inline">{t("DELETE")}</span>
        </Button>
        <IconButton icon="undo" label={t("UNDO")} onClick={onUndo} disabled={!canUndo} />
        <IconButton icon="redo" label={t("REDO")} onClick={onRedo} disabled={!canRedo} />
      </ControlGroup>

      <ControlGroup aria-label={t("ZOOM CONTROLS")}>
        <IconButton icon="zoom-out" label={t("ZOOM OUT")} onClick={onZoomOut} />
        <Button size="sm" variant="outline" onClick={onZoomReset} title={t("RESET ZOOM")} className="min-w-16 px-2 sm:min-w-20 sm:px-3.5">
          <span className="sr-only">{t("RESET ZOOM")}</span>
          {Math.round(zoomPercent)}%
        </Button>
        <IconButton icon="zoom-in" label={t("ZOOM IN")} onClick={onZoomIn} />
      </ControlGroup>

      <ControlGroup className="ml-auto" bleed aria-label={t("EXPORT")}>
        <Button
          size="sm"
          variant="primary"
          onClick={() => onExport("pdf")}
          disabled={isExporting}
        >
          <Icon name="pdf" size={14} />
          <span className="hidden sm:inline">{isExporting ? t("EXPORTING…") : t("EXPORT PDF")}</span>
          <span className="sm:hidden">PDF</span>
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
          <span className="hidden sm:inline">CBZ</span>
        </Button>
      </ControlGroup>
    </Surface>
  );
}
