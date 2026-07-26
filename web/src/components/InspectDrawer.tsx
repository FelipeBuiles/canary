import { useAdaptation, useBookPlan } from "../api/queries";
import { useI18n } from "../i18n";
import type { DrawerKind } from "../lib/stations";
import { Button } from "./ui/Button";
import { Surface } from "./ui/Surface";

interface InspectDrawerProps {
  project: string;
  kind: DrawerKind | null;
  onClose: () => void;
}

export function InspectDrawer({ project, kind, onClose }: InspectDrawerProps) {
  const { t } = useI18n();
  const adaptation = useAdaptation(kind === "adaptation" ? project : undefined);
  const plan = useBookPlan(kind === "page-plan" ? project : undefined);

  if (!kind) return null;
  const title = kind === "adaptation" ? t("BOOK ADAPTATION") : t("PAGE PLAN");
  const loading = kind === "adaptation" ? adaptation.isLoading : plan.isLoading;
  const error = kind === "adaptation" ? adaptation.error : plan.error;

  return (
    <aside
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-modal flex justify-end bg-ink-black/60"
    >
      <div className="h-full w-full max-w-2xl overflow-y-auto border-l-[3px] border-ink-black bg-pulp-paper shadow-ink">
        <header className="sticky top-0 z-sticky flex items-center justify-between gap-4 border-b-[3px] border-ink-black bg-bristol px-5 py-4">
          <div>
            <p className="font-meta text-xs font-bold text-hero-red">{t("AUTOMATIC WORK")}</p>
            <h2 className="font-display text-2xl font-black uppercase">{title}</h2>
          </div>
          <Button variant="outline" size="xs" onClick={onClose}>{t("CLOSE")}</Button>
        </header>

        <div className="space-y-5 p-5">
          {loading && <p className="font-meta text-sm font-bold">{t("LOADING…")}</p>}
          {error && (
            <Surface tone="gold" border="hard" shadow="none" padding="md">
              <p className="font-body text-sm font-bold">{t("This automatic work is not available yet.")}</p>
            </Surface>
          )}

          {kind === "adaptation" && adaptation.data && (
            <>
              <Surface padding="md" border="soft" shadow="none">
                <h3 className="font-display text-lg font-black uppercase">{t("Narrative treatment")}</h3>
                <p className="mt-2 font-body text-sm leading-6">
                  {adaptation.data.treatment?.causal_spine?.join(" ") || t("The book-wide treatment is ready.")}
                </p>
              </Surface>
              <Surface padding="md" border="soft" shadow="none">
                <h3 className="font-display text-lg font-black uppercase">{t("Adapted beats")}</h3>
                <p className="mt-2 font-body text-sm">
                  {adaptation.data.beats?.length ?? 0} {t("ordered story beats")}
                </p>
              </Surface>
            </>
          )}

          {kind === "page-plan" && plan.data && (
            <>
              <Surface padding="md" border="soft" shadow="none">
                <h3 className="font-display text-lg font-black uppercase">{t("Book rhythm")}</h3>
                <p className="mt-2 font-body text-sm leading-6">
                  {plan.data.rhythm_summary || t("The page and spread rhythm is ready.")}
                </p>
              </Surface>
              <Surface padding="md" border="soft" shadow="none">
                <h3 className="font-display text-lg font-black uppercase">{t("Planned pages")}</h3>
                <p className="mt-2 font-body text-sm">
                  {plan.data.pages?.length ?? 0} {t("complete pages")}
                </p>
              </Surface>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
