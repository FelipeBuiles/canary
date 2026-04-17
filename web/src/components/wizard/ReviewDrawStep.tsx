import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { SectionLabel } from "../SectionLabel";
import { PanelCard } from "../PanelCard";
import { useImages } from "../../api/queries";
import { StyleCallout } from "./StyleCallout";
import { useI18n } from "../../i18n";

interface ReviewDrawStepProps {
  project: string;
  onApprove: () => void;
  isApproving: boolean;
}

export function ReviewDrawStep({ project, onApprove, isApproving }: ReviewDrawStepProps) {
  const { data: images, isLoading } = useImages(project);
  const { t } = useI18n();

  return (
    <div className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="sage">{t("REVIEW CHECKPOINT")}</SectionLabel>
        <h1 className="mt-4 display-headline">{t("PANEL GALLERY")}</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          Review the generated panels. Approve to proceed to final assembly.
        </p>
      </Card>

      {isLoading ? (
        <div className="flex min-h-[20vh] items-center justify-center">
          <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">{t("LOADING PANELS…")}</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {images?.map((img) => {
            const key = `${img.scene_id}-${img.panel_number}`;
            const imageUrl = `/api/projects/${encodeURIComponent(project)}/files/images/${img.scene_id}/panel_${String(img.panel_number).padStart(3, "0")}.png`;
            return (
              <PanelCard
                key={key}
                sceneId={img.scene_id}
                panelNumber={img.panel_number}
                status={img.status}
                imageUrl={imageUrl}
              />
            );
          })}
        </div>
      )}

      <div className="flex items-center gap-4">
        <StyleCallout project={project} />
        <Button size="lg" onClick={onApprove} disabled={isApproving}>
          {isApproving ? t("APPROVING…") : t("APPROVE & CONTINUE")}
        </Button>
        <span className="text-[0.72rem] text-ink-black/40">
          Something looks wrong? Regenerate individual panels in the Draw room.
        </span>
      </div>
    </div>
  );
}
