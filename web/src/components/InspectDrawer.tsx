import { useEffect, useRef } from "react";
import { useAdaptation, useBookPlan, useCompletePages } from "../api/queries";
import { useI18n } from "../i18n";
import type { DrawerKind } from "../lib/stations";
import type { BookAdaptation, BookPlan, CompletePageSummary } from "../types/api";
import { Button } from "./ui/Button";
import { Surface } from "./ui/Surface";

interface InspectDrawerProps {
  project: string;
  kind: DrawerKind | null;
  onClose: () => void;
}

function AdaptationDetails({ adaptation }: { adaptation: BookAdaptation }) {
  const { t } = useI18n();
  const beats = adaptation.beats ?? [];
  const spine = adaptation.treatment?.causal_spine ?? [];

  return (
    <>
      <Surface padding="md" border="soft" shadow="none">
        <h3 className="font-display text-lg font-black uppercase">{t("Narrative treatment")}</h3>
        {spine.length > 0 ? (
          <ul className="mt-3 space-y-2 font-body text-sm leading-6">
            {spine.map((line, index) => (
              <li key={`spine-${index}`} className="bg-surface-container px-3 py-2">{line}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 font-body text-sm leading-6">
            {t("The book-wide treatment is ready.")}
          </p>
        )}
      </Surface>

      <Surface padding="md" border="soft" shadow="none">
        <h3 className="font-display text-lg font-black uppercase">{t("Adapted beats")}</h3>
        <p className="mt-2 font-body text-sm">
          {beats.length} {t("ordered story beats")}
        </p>
        {beats.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer font-meta text-[0.62rem] font-bold uppercase tracking-[0.12em] text-hero-red">
              {t("View story beats")}
            </summary>
            <ol className="mt-2 space-y-1">
              {beats.map((beat) => (
                <li
                  key={beat.id}
                  className="grid grid-cols-[2.25rem_minmax(0,1fr)] items-start gap-3 bg-surface-container px-3 py-3"
                >
                  <span className="font-display text-lg font-black leading-none">{beat.order}</span>
                  <p className="min-w-0 font-body text-sm font-semibold leading-5">{beat.summary}</p>
                </li>
              ))}
            </ol>
          </details>
        )}
      </Surface>
    </>
  );
}

function PagePlanDetails({
  plan,
  pages,
  detailsLoading,
  detailsError,
}: {
  plan: BookPlan;
  pages: CompletePageSummary[] | undefined;
  detailsLoading: boolean;
  detailsError: unknown;
}) {
  const { t } = useI18n();
  const planCount = plan.pages?.length ?? 0;

  return (
    <>
      <Surface padding="md" border="soft" shadow="none">
        <h3 className="font-display text-lg font-black uppercase">{t("Book rhythm")}</h3>
        <p className="mt-2 font-body text-sm leading-6">
          {plan.rhythm_summary || t("The page and spread rhythm is ready.")}
        </p>
      </Surface>

      <Surface padding="md" border="soft" shadow="none">
        <h3 className="font-display text-lg font-black uppercase">{t("Planned pages")}</h3>
        <p className="mt-2 font-body text-sm">
          {planCount} {t("complete pages")}
        </p>
        {pages && pages.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer font-meta text-[0.62rem] font-bold uppercase tracking-[0.12em] text-hero-red">
              {t("View planned pages")}
            </summary>
            <ol className="mt-2 space-y-1">
              {pages.map((item) => (
                <li
                  key={item.page.page_number}
                  className="grid grid-cols-[2.25rem_minmax(0,1fr)] items-start gap-3 bg-surface-container px-3 py-3"
                >
                  <span className="font-display text-lg font-black leading-none">
                    {item.page.page_number}
                  </span>
                  <div className="min-w-0">
                    <p className="font-body text-sm font-semibold leading-5">
                      {item.page.layout_intent}
                    </p>
                    <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
                      {item.page.rhythm_intent}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </details>
        )}
        {!pages && detailsLoading && (
          <p className="mt-2 font-body text-sm">{t("Loading page details…")}</p>
        )}
        {!pages && !detailsLoading && (
          <p className="mt-2 font-body text-sm text-ink-muted">
            {detailsError
              ? t("Page details are not available right now.")
              : t("The page plan is not ready yet.")}
          </p>
        )}
      </Surface>
    </>
  );
}

export function InspectDrawer({ project, kind, onClose }: InspectDrawerProps) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const adaptation = useAdaptation(kind === "adaptation" ? project : undefined);
  const plan = useBookPlan(kind === "page-plan" ? project : undefined);
  const completePages = useCompletePages(kind === "page-plan" ? project : undefined);

  // The parent re-renders on every queue/query tick with a fresh inline
  // onClose; calling through a ref keeps this effect (and drawer focus)
  // stable instead of resetting focus mid-read.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!kind) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    panel?.focus();
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      // Keep keyboard focus inside the drawer while it is open.
      if (event.key === "Tab" && panel) {
        const focusables = panel.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        const enabled = Array.from(focusables).filter(
          (el) => !el.hasAttribute("disabled")
            && !el.closest("[hidden]")
            && el.getClientRects().length > 0,
        );
        const active = document.activeElement as HTMLElement | null;
        if (enabled.length === 0) {
          event.preventDefault();
          return;
        }
        const first = enabled[0];
        const last = enabled[enabled.length - 1];
        if (event.shiftKey && (active === first || active === panel || !panel.contains(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (active === last || active === panel || !panel.contains(active))) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = originalOverflow;
      previouslyFocused?.focus?.();
    };
  }, [kind]);

  if (!kind) return null;
  const title = kind === "adaptation" ? t("BOOK ADAPTATION") : t("PAGE PLAN");
  const loading = kind === "adaptation" ? adaptation.isLoading : plan.isLoading;
  const error = kind === "adaptation" ? adaptation.error : plan.error;

  return (
    <aside
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-[120] flex justify-end bg-ink-black/60"
      onClick={() => onCloseRef.current()}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex h-full w-full flex-col border-l-[3px] border-ink-black bg-pulp-paper shadow-ink focus-visible:outline-none sm:max-w-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex min-h-14 shrink-0 items-center justify-between gap-4 border-b-[3px] border-ink-black bg-bristol px-5 py-3 md:py-4">
          <h2 className="min-w-0 truncate font-display text-[1.55rem] font-black uppercase leading-[0.9] tracking-[-0.03em]">
            {title}
          </h2>
          <Button variant="outline" size="xs" onClick={onClose} aria-label={t("Close reading panel")}>
            {t("CLOSE")}
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-5 p-5">
            {loading && <p className="font-meta text-sm font-bold">{t("LOADING…")}</p>}
            {error && (
              <Surface tone="gold" border="hard" shadow="none" padding="md">
                <p className="font-body text-sm font-bold">
                  {t("This automatic work is not available yet.")}
                </p>
              </Surface>
            )}

            {!loading && !error && kind === "adaptation" && !adaptation.data && (
              <Surface tone="container" border="soft" shadow="none" padding="md">
                <p className="font-body text-sm">{t("The book adaptation is not ready yet.")}</p>
              </Surface>
            )}

            {kind === "adaptation" && adaptation.data && (
              <AdaptationDetails adaptation={adaptation.data} />
            )}

            {!loading && !error && kind === "page-plan" && !plan.data && (
              <Surface tone="container" border="soft" shadow="none" padding="md">
                <p className="font-body text-sm">{t("The page plan is not ready yet.")}</p>
              </Surface>
            )}

            {kind === "page-plan" && plan.data && (
              <PagePlanDetails
                plan={plan.data}
                pages={completePages.data?.pages}
                detailsLoading={completePages.isLoading}
                detailsError={completePages.error}
              />
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
