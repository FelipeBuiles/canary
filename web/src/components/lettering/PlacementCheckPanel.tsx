import { ErrorNotice } from "../composites/ErrorNotice";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { textFor, type PlacementCheck } from "@lettering-engine";
import type { LetteringEvidence, PageLettering } from "../../api/lettering";
import { analyzeCompletePage, getPageAnalysisEstimate } from "../../api/pages";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { Button } from "../ui/Button";
import type { Translator } from "../../locales/messages";
import { useI18n } from "../../i18n";

const checkKey = (check: PlacementCheck, index: number) => `${check.element_id ?? "page"}:${check.code}:${index}`;

function quote(text: string | undefined, limit = 28) {
  const words = (text ?? "").replace(/\s+/g, " ").trim();
  return words.length > limit ? `${words.slice(0, limit - 1)}…` : words;
}

/** Plain-language findings: what is wrong, why it matters, and what Fix does. */
function describe(check: PlacementCheck, who: string | null, t: Translator) {
  switch (check.code) {
    case "crosses_panel": return { title: t("Crosses a panel border"), detail: t("Readers expect words to stay inside the panel they belong to."), action: t("Fit inside panel") };
    case "covers_face": return { title: who ? t("Covers {name}’s face", { name: who }) : t("Covers a face"), detail: t("Faces carry the emotion of the beat. Move the words just clear of it."), action: t("Move off face") };
    case "tail_misses_speaker": return { title: who ? t("Tail points away from {name}", { name: who }) : t("Tail points away from the speaker"), detail: t("The tail tells readers who is talking."), action: t("Aim the tail") };
    case "tail_missing": return { title: who ? t("No tail to {name}", { name: who }) : t("No tail to the speaker"), detail: t("Optional when the speaker is obvious, but a tail removes doubt."), action: t("Add a tail") };
    case "covers_in_world_text": return { title: t("Hides “{text}” in the art", { text: quote(check.text) }), detail: t("Signs and labels can matter to the scene. Keep them visible unless you mean to cover them."), action: t("Move aside") };
    case "stray_lettering": return { title: t("Lettering drawn into the art: “{text}”", { text: quote(check.text) }), detail: t("Cover it with lettering, or revise the artwork to remove it."), action: null };
  }
}

export function PlacementCheckPanel({ project, pageNumber, state, evidence, checks, locale, disabled, focused, showFaces, onShowFaces, onFocus, onFix, onFixAll, onRelayout, onChecked }: {
  project: string;
  pageNumber: number;
  state: PageLettering;
  evidence: LetteringEvidence;
  checks: PlacementCheck[];
  locale: string;
  disabled: boolean;
  focused: string | null;
  showFaces: boolean;
  onShowFaces: (show: boolean) => void;
  onFocus: (key: string, check: PlacementCheck) => void;
  onFix: (check: PlacementCheck) => void;
  onFixAll: () => void;
  onRelayout: () => Promise<void>;
  onChecked: () => Promise<void>;
}) {
  const { t } = useI18n();
  const read = evidence.page_read, heads = read?.heads ?? null;
  const [running, setRunning] = useState<"check" | "relayout" | null>(null), [error, setError] = useState<string | null>(null);
  const estimate = useQuery({
    queryKey: ["project", project, "page-analysis-estimate", pageNumber, read?.render_revision ?? null],
    queryFn: () => getPageAnalysisEstimate(project, pageNumber), enabled: !read, staleTime: 60_000,
  });
  const order = new Map(state.elements.map((element, index) => [element.id, index + 1]));
  const byId = new Map(state.elements.map(element => [element.id, element]));
  const fixable = checks.filter(check => check.severity === "fix" && check.fix);
  const toFix = checks.filter(check => check.severity === "fix").length, toConsider = checks.length - toFix;
  const whoFor = (check: PlacementCheck) => {
    const head = heads?.find(h => h.x === check.mark.x && h.y === check.mark.y && h.width === check.mark.width);
    return head?.entity_id ? evidence.speaker_names[head.entity_id] ?? null : null;
  };
  async function run(kind: "check" | "relayout", work: () => Promise<void>) {
    setRunning(kind); setError(null);
    try { await work(); }
    catch (caught) {
      if (kind === "check") maybeShowInsufficientCredits(caught, { actionLabel: t("Check this page") });
      setError(caught instanceof Error ? caught.message : t("The check could not finish. Try again."));
    }
    finally { setRunning(null); }
  }
  const summary = !checks.length ? (heads ? t("Looks clear") : t("Panels look clear")) : [toFix && `${toFix} ${t("to fix")}`, toConsider && `${toConsider} ${t("to consider")}`].filter(Boolean).join(" · ");
  return <details className="lettering-check" open={checks.length > 0 || !read}>
    <summary><span>{t("Placement check")}</span><span className={`lettering-check-badge ${toFix ? "is-fix" : toConsider ? "is-consider" : "is-clear"}`}>{summary}</span></summary>
    <div className="lettering-check-body">
      <p className="lettering-check-source">{!read
        ? t("Faces not read yet. Panel borders are checked.")
        : heads === null
          ? t("Faces not read for this artwork. Panels and drawn-in text are checked.")
          : heads.length
            ? `${t("Checked against this artwork")} · ${heads.length} ${t("{count, plural, one {face found} other {faces found}}", { count: heads.length })}`
            : t("Checked against this artwork · no faces found")}</p>
      {checks.length > 0 && <ul className="lettering-check-list">{checks.map((check, index) => {
        const key = checkKey(check, index), copy = describe(check, whoFor(check), t), element = check.element_id ? byId.get(check.element_id) : null;
        return <li key={key} className={`lettering-check-item is-${check.severity} ${focused === key ? "is-focused" : ""}`}>
          <button type="button" className="lettering-check-target" aria-pressed={focused === key} onClick={() => onFocus(key, check)}>
            <span className="lettering-check-dot" aria-hidden="true" />
            <span className="min-w-0"><span className="lettering-check-title">{copy.title}</span>
              {element && <span className="lettering-check-where">{order.get(element.id)} · {quote(textFor(element, locale)) || t("Write some words…")}</span>}
              <span className="lettering-check-detail">{copy.detail}</span></span>
          </button>
          {check.fix && copy.action && <Button size="xs" variant="outline" disabled={disabled} onClick={() => onFix(check)}>{copy.action}</Button>}
        </li>;
      })}</ul>}
      <div className="lettering-small-actions">
        {fixable.length > 1 && <Button size="xs" variant="secondary" disabled={disabled} onClick={onFixAll}>{t("Fix all")} · {fixable.length}</Button>}
        {!!heads?.length && <label className="lettering-checkbox"><input type="checkbox" checked={showFaces} onChange={event => onShowFaces(event.target.checked)} />{t("Show faces found")}</label>}
      </div>
      {!!heads?.length && <div className="lettering-check-relayout">
        <Button size="xs" variant="outline" disabled={disabled || !!running} onClick={() => void run("relayout", onRelayout)}>{running === "relayout" ? t("Laying out…") : t("Redo layout around faces")}</Button>
        <p className="lettering-hint">{t("Places each planned balloon above its speaker, inside its panel. Your wording and styles stay; Undo restores your layout.")}</p>
      </div>}
      {!read && <div className="lettering-check-run">
        <Button size="xs" variant="outline" title={t("Finds faces for balloons and tails, and any words drawn into the art. New pages get this automatically.")} disabled={disabled || !!running || !estimate.data} onClick={() => void run("check", async () => { await analyzeCompletePage(project, pageNumber); await onChecked(); })}>
          {running === "check" ? t("Checking this page…") : t("Check this page")}{estimate.data ? ` · ~${estimate.data.estimate_credits} ${t("credits")}` : ""}
        </Button>
        {estimate.error && <ErrorNotice error={(estimate.error as Error)} operation="estimate" />}
      </div>}
      {error && <ErrorNotice error={error} operation="generate" />}
      <p className="lettering-hint">{t("Hints, not verdicts. You still confirm placement against the artwork.")}</p>
    </div>
  </details>;
}
