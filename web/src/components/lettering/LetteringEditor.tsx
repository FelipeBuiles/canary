import { ErrorNotice } from "../composites/ErrorNotice";
import { useEffect, useMemo, useReducer, useRef, useState, type KeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { defaultTailTarget, elementRect, canvasMeasure, fontCSS, loadFonts, placementChecks, renderOverlay, resolvePage, styleFor, textFor, translationStatus, type PlacementCheck } from "@lettering-engine";
import { getLetteringSuggestions, getPageLettering, putPageLettering, resetPageLettering, getBookLetteringStyle, putBookLetteringStyle, type HybridLetteringResponse, type PageLettering, type LetteringElement, type LetteringStyle, type RoleName, } from "../../api/lettering";
import { pageRenderUrl } from "../../api/pages";
import { clearLetteringDraft, editableSignature, historyReducer, initialHistory, letteringDraftKey, readLetteringDraft, writeLetteringDraft } from "../../lib/letteringHistory";
import { Redo2, Undo2 } from "lucide-react";
import { Button } from "../ui/Button";
import { FieldLabel, TextAreaField } from "../ui/Field";
import { Surface } from "../ui/Surface";
import { LetteringCanvas } from "./LetteringCanvas";
import { LetteringStyleControls } from "./LetteringStyleControls";
import { LetteringPresetTiles, LetteringRoleTiles } from "./LetteringPickers";
import { BalloonJoin, EmphasisButton, TailCurve } from "./LetteringBalloonControls";
import { joinedPlacement, toggleEmphasis } from "./letteringTools";
import { sampleWords } from "./letteringVoices";
import { ProjectLetteringLanguage } from "./ProjectLetteringLanguage";
import { PlacementCheckPanel } from "./PlacementCheckPanel";
import { engineEvidence, useChecks } from "../../lib/placementChecks";
import { msg } from "../../locales/messages";
import { useI18n } from "../../i18n";
import "./lettering.css";
const roleNames: Record<RoleName, string> = { caption: msg("Caption"), speech: msg("Speech"), thought: msg("Thought"), sfx: msg("Sound effect") };
const errors: Record<string, string> = {
  stale_translation: msg("The source wording changed. Review this translation before exporting."),
  missing_translation: msg("This language still uses the source wording. Add its translation before exporting."),
  outside_page: msg("Part of this lettering is outside the page. Move it inward or reduce its rotation or scale."),
  unsupported_script: msg("The bundled typefaces do not support this writing system. This page cannot be exported with missing glyphs."),
  font_script_mismatch: msg("Choose M PLUS 1p for supported Japanese or Chinese characters."),
  missing_glyphs: msg("This font lacks some characters. Choose a supported bundled font or change the copy; system font fallback cannot be exported."),
  empty_copy: msg("Write some words or hide this element before exporting."),
};
function message(error: unknown): string { return error instanceof Error ? error.message : "The change could not be saved. Your local draft is still here."; }
export function LetteringEditor({ project, pageNumber, disabled = false }: {
  project: string;
  pageNumber: number;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const query = useQuery({ queryKey: ["page-lettering", project, pageNumber], queryFn: () => getPageLettering(project, pageNumber), refetchOnWindowFocus: false, staleTime: Infinity });
  if (query.isPending)
    return <p role="status">{t("Opening lettering…")}</p>;
  if (query.isError)
    return <Surface padding="lg" border="soft" shadow="none"><ErrorNotice error={query.error} operation="load" onRetry={() => void query.refetch()} />{query.data?.mode !== "baked" && <div className="mt-4"><ProjectLetteringLanguage project={project} disabled={disabled} onApplied={async () => {
      const next = await query.refetch({ throwOnError: true });
      if (next.data?.mode !== "hybrid")
        throw new Error(next.data?.message);
    }} /></div>}</Surface>;
  if (query.data.mode === "baked")
    return <Surface padding="lg" border="soft" shadow="none"><h3 className="font-display text-xl">{t("Lettering is part of this artwork")}</h3><p className="mt-2 text-sm leading-6">{t(query.data.message)}</p></Surface>;
  return <LetteringWorkspace key={`${project}:${pageNumber}`} project={project} pageNumber={pageNumber} initial={query.data} disabled={disabled} />;
}
function LetteringWorkspace({ project, pageNumber, initial, disabled }: {
  project: string;
  pageNumber: number;
  initial: HybridLetteringResponse;
  disabled: boolean;
}) {
  const { t } = useI18n(), client = useQueryClient();
  const [base, setBase] = useState(initial), [history, dispatch] = useReducer(historyReducer, initial.state, initialHistory);
  const [selected, setSelected] = useState<string | null>(initial.state.elements.find(e => !e.hidden)?.id ?? null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<Error | string | null>(null), [fontsReady, setFontsReady] = useState(false), [fontAttempt, setFontAttempt] = useState(0);
  const draftKey = letteringDraftKey(project, pageNumber);
  const [recovery, setRecovery] = useState(() => {
    const draft = readLetteringDraft(draftKey);
    return draft && editableSignature(draft.state) !== editableSignature(initial.state) ? draft : null;
  });
  const [draftStored, setDraftStored] = useState(true), [bookStyleOpen, setBookStyleOpen] = useState(false), [addOpen, setAddOpen] = useState(false);
  const [loadedArtUrl, setLoadedArtUrl] = useState<string | null>(null);
  const [translationBusy, setTranslationBusy] = useState(false);
  const [showFaces, setShowFaces] = useState(false), [focusedCheck, setFocusedCheck] = useState<{ key: string; check: PlacementCheck } | null>(null);
  const artUrl = pageRenderUrl(project, pageNumber, base.render_revision);
  const textarea = useRef<HTMLTextAreaElement>(null), root = useRef<HTMLDivElement>(null);
  const dirty = editableSignature(history.present) !== editableSignature(base.state) || base.needs_save;
  const dirtyRef = useRef(dirty);
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);
  const canRestore = !!recovery && recovery.baseRevision === base.saved_revision && recovery.sourceSha === base.state.comic_page_sha256 && recovery.styleSha === base.style.content_sha256;
  const locked = busy || translationBusy || disabled || !fontsReady || !!recovery || base.source_stale;
  const pageLocked = locked || bookStyleOpen;
  const measure = useMemo(() => fontsReady ? canvasMeasure() : null, [fontsReady]);
  const layout = useMemo(() => {
    if (!measure)
      return { state: null, error: null };
    try {
      return { state: resolvePage(history.present, base.style, measure), error: null };
    }
    catch (error) {
      return { state: null, error: message(error) };
    }
  }, [history.present, base.style, measure]);
  const current = layout.state?.elements.find(e => e.id === selected) ?? null;
  const canonical = current?.source_lettering_item_id ? base.canonical[current.source_lettering_item_id] : null;
  const checks = useChecks(layout.state, base.evidence);
  const heads = base.evidence.page_read?.heads ?? null;
  const faceGuides = heads?.map(head => ({ ...head, label: (head.entity_id && base.evidence.speaker_names[head.entity_id]) || t("Face") })) ?? null;
  // A focused finding stays on the canvas only while it is still reported.
  const focus = focusedCheck && checks.some(check => check.code === focusedCheck.check.code && check.element_id === focusedCheck.check.element_id) ? focusedCheck.check : null;
  const issues = layout.state?.elements.filter(e => !e.hidden && (e.resolved?.overflow || e.resolved?.warnings.length)) ?? [];
  useEffect(() => {
    let live = true;
    loadFonts().then(() => {
      if (live)
        setFontsReady(true);
    }).catch(error => {
      if (live)
        setError(error instanceof Error ? error : message(error));
    });
    return () => { live = false; };
  }, [fontAttempt]);
  useEffect(() => {
    // Persist committed edits, not every intermediate pointer preview.
    if (recovery || history.gesture) return;
    if (!dirty) {
      clearLetteringDraft(draftKey);
      return;
    }
    const saved = writeLetteringDraft(draftKey, {
      version: 1, baseRevision: base.saved_revision, sourceSha: base.state.comic_page_sha256,
      styleSha: base.style.content_sha256, imageSha: base.render_image_sha256, state: history.present, updatedAt: new Date().toISOString()
    });
    // Storage can be disabled or full. This is a safety signal, never a claim of server persistence.
    queueMicrotask(() => setDraftStored(saved));
  }, [history.present, history.gesture, base, draftKey, dirty, recovery]);
  useEffect(() => {
    if (!dirty)
      return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function changeState(state: PageLettering, preview = false) { dispatch({ type: preview ? "preview" : "change", value: state }); setError(null); }
  function patch(id: string, patch: Partial<LetteringElement>, preview = false) {
    changeState({ ...history.present, elements: history.present.elements.map(element => {
      if (element.id !== id) return element;
      const next = { ...element, ...patch };
      if (patch.text_by_locale) {
        next.translation_sources = { ...next.translation_sources };
        for (const [locale, text] of Object.entries(patch.text_by_locale)) {
          if (locale !== "source" && element.text_by_locale[locale] !== text) next.translation_sources[locale] = next.text_by_locale.source;
        }
      }
      return next;
    }) }, preview);
  }
  function withFixes(state: PageLettering, fixes: PlacementCheck[]): PageLettering {
    const patches = new Map<string, Partial<LetteringElement>>();
    for (const check of fixes) if (check.element_id && check.fix) patches.set(check.element_id, { ...patches.get(check.element_id), ...check.fix });
    return { ...state, elements: state.elements.map(e => patches.has(e.id) ? { ...e, ...patches.get(e.id) } : e) };
  }
  function fixCheck(check: PlacementCheck) {
    if (pageLocked || !check.element_id || !check.fix) return;
    patch(check.element_id, check.fix);
    setSelected(check.element_id);
    setFocusedCheck(null);
  }
  function fixAll() {
    if (pageLocked || !measure) return;
    // Move bodies first, then aim tails from where the bodies landed: one undo step.
    const movable = checks.filter(check => check.severity === "fix" && check.fix?.placement);
    let next = withFixes(history.present, movable);
    try {
      const aims = placementChecks(resolvePage(next, base.style, measure), engineEvidence(base.evidence)).filter(check => check.severity === "fix" && check.fix?.tail_target);
      next = withFixes(next, aims);
    } catch (error) { setError(error instanceof Error ? error : message(error)); return; }
    changeState(next);
    setFocusedCheck(null);
  }
  async function relayout() {
    const suggestion = await getLetteringSuggestions(project, pageNumber);
    if (suggestion.render_image_sha256 !== base.render_image_sha256)
      throw new Error(t("The artwork changed. Reload the page before redoing the layout."));
    // Planned balloons only; wording, styles and added lettering stay as they are.
    changeState({ ...history.present, elements: history.present.elements.map(e => {
      const seed = suggestion.elements[e.id];
      return seed && e.source_lettering_item_id ? { ...e, placement: seed.placement, tail_target: seed.tail_target, rotation: 0, scale: 1, tight_box: true } : e;
    }) });
    setFocusedCheck(null);
  }
  async function refreshEvidence() {
    const next = await getPageLettering(project, pageNumber);
    if (next.mode !== "hybrid") throw new Error(next.message);
    if (next.render_image_sha256 === base.render_image_sha256) setBase(old => ({ ...old, evidence: next.evidence }));
    void client.invalidateQueries({ predicate: query => query.queryKey.includes(project) && query.queryKey[0] !== "page-lettering" });
    setShowFaces(true);
  }
  function acknowledge(next: HybridLetteringResponse, clearHistory = false) {
    setBase(next);
    dispatch({ type: clearHistory ? "reset" : "acknowledge", value: next.state });
    client.setQueryData(["page-lettering", project, pageNumber], next);
    clearLetteringDraft(draftKey);
    setError(null);
    // Query roots differ across the existing rooms. Invalidate this project's
    // read models so both the page gallery and Book preflight drop old pixels.
    void client.invalidateQueries({ predicate: query => query.queryKey.includes(project) && query.queryKey[0] !== "page-lettering" });
  }
  async function save(markReviewed = false) {
    if (pageLocked || !layout.state || layout.error)
      return;
    setBusy(true);
    setError(null);
    try {
      acknowledge(await putPageLettering(project, pageNumber, layout.state, base, markReviewed));
    }
    catch (error) {
      setError(error instanceof Error ? error : message(error));
    }
    finally {
      setBusy(false);
    }
  }
  async function reload() {
    if (dirty && !window.confirm(t("Reload the saved lettering? Your unsaved draft remains on this device for recovery.")))
      return;
    setBusy(true);
    try {
      const next = await getPageLettering(project, pageNumber);
      if (next.mode !== "hybrid")
        throw new Error(next.message);
      const draft = readLetteringDraft(draftKey);
      setBase(next);
      client.setQueryData(["page-lettering", project, pageNumber], next);
      dispatch({ type: "reset", value: next.state });
      setRecovery(draft && editableSignature(draft.state) !== editableSignature(next.state) ? draft : null);
      setError(null);
    }
    catch (error) {
      setError(error instanceof Error ? error : message(error));
    }
    finally {
      setBusy(false);
    }
  }
  async function rebuild() {
    if (!window.confirm(t("Rebuild lettering from the current page plan? This replaces placement and display wording, but preserves the previous saved revision in the project archive. Artwork is untouched.")))
      return;
    setBusy(true);
    setError(null);
    try {
      acknowledge(await resetPageLettering(project, pageNumber, base), true);
      setRecovery(null);
    }
    catch (error) {
      setError(error instanceof Error ? error : message(error));
    }
    finally {
      setBusy(false);
    }
  }
  function add(role: RoleName) {
    const id = `custom-${crypto.randomUUID()}`, placement = { x: .28, y: .38, width: .44, height: .16 };
    const tail = role === "speech" || role === "thought" ? defaultTailTarget(placement) : null;
    const element: LetteringElement = {
      id, source_lettering_item_id: null, role, text_by_locale: { source: "", ...(history.present.locale !== "source" ? { [history.present.locale]: "" } : {}) }, suggested_placement: placement, placement,
      hidden: false, style_override: null, tail_target: tail, suggested_tail_target: tail, rotation: 0, scale: 1, z_index: 0, tight_box: true, resolved: null
    };
    changeState({ ...history.present, elements: [...history.present.elements, element] });
    setSelected(id);
    setAddOpen(false);
    requestAnimationFrame(() => textarea.current?.focus());
  }
  function remove() {
    if (!current)
      return; if (current.source_lettering_item_id)
      patch(current.id, { hidden: !current.hidden });
    else {
      // Balloons joined to a removed lead stand on their own again.
      changeState({ ...history.present, elements: history.present.elements.filter(e => e.id !== current.id).map(e => e.link_to === current.id ? { ...e, link_to: null } : e) });
      setSelected(null);
    }
  }
  // Stress the selected words (or the word at the caret) and keep them selected.
  function emphasize() {
    const field = textarea.current;
    if (!field || !current || pageLocked) return;
    const locale = history.present.locale, next = toggleEmphasis(field.value, field.selectionStart, field.selectionEnd);
    if (next.text === field.value) return;
    patch(current.id, { text_by_locale: { ...current.text_by_locale, [locale]: next.text } });
    requestAnimationFrame(() => { field.focus(); field.setSelectionRange(next.start, next.end); });
  }
  function keys(event: KeyboardEvent<HTMLDivElement>) {
    if (pageLocked)
      return;
    const typing = event.target instanceof HTMLElement && !!event.target.closest("input,textarea,select,[contenteditable=true]");
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      event.stopPropagation();
      dispatch({ type: "commit" });
      // Commit buffered numeric/text fields before the click reads the latest render.
      if (typing && (event.target instanceof HTMLElement))
        event.target.blur();
      requestAnimationFrame(() => root.current?.querySelector<HTMLButtonElement>("[data-lettering-save]")?.click());
    }
    if (!typing && (event.metaKey || event.ctrlKey) && ["z", "y"].includes(event.key.toLowerCase())) {
      event.preventDefault();
      event.stopPropagation();
      dispatch({ type: event.key.toLowerCase() === "y" || event.shiftKey ? "redo" : "undo" });
    }
    if (!typing && ["Backspace", "Delete"].includes(event.key) && current) {
      event.preventDefault();
      remove();
    }
  }
  function recover() {
    if (!recovery || !canRestore)
      return;
    const state = { ...recovery.state, revision: base.state.revision, content_sha256: "", canvas_aspect_ratio: base.state.canvas_aspect_ratio };
    // The exact saved allocation/style must match; a new art image still needs
    // visual placement review. Geometry is not silently remapped to a new plan.
    try {
      if (measure)
        resolvePage(state, base.style, measure);
      changeState(state);
      setRecovery(null);
    }
    catch (error) {
      setError(error instanceof Error ? error : message(error));
    }
  }
  function downloadRecovery() {
    if (!recovery)
      return; const blob = new Blob([JSON.stringify(recovery, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = `page-${pageNumber}-lettering-draft.json`; link.click(); URL.revokeObjectURL(url);
  }
  async function adoptBookChange() {
    if (dirtyRef.current)
      throw new Error(t("Save this page before changing the book-wide style"));
    const next = await getPageLettering(project, pageNumber);
    if (next.mode !== "hybrid")
      throw new Error(next.message);
    if (dirtyRef.current)
      throw new Error(t("Save this page before changing the book-wide style"));
    acknowledge(next, true);
  }
  const reviewPending = !dirty && !busy && base.placement_review_needed && !base.source_stale;
  return <div ref={root} className="lettering-editor" onKeyDown={keys}>
    <style>{fontCSS()}</style>
    <div className="lettering-main-toolbar">
      <div className="lettering-toolbar-book">
        <Button variant="outline" size="xs" disabled={pageLocked || dirty} title={dirty ? t("Save this page before changing the book-wide style") : undefined} onClick={() => setBookStyleOpen(true)} aria-expanded={bookStyleOpen}>{t("Book lettering style")}</Button>
        <div className="lettering-language"><ProjectLetteringLanguage project={project} disabled={pageLocked || dirty} onBusyChange={setTranslationBusy} onApplied={adoptBookChange} /></div>
      </div>
      <div className="lettering-toolbar-actions">
        {issues.length > 0 && <span role="status" className="lettering-issue-count">{t("{count, plural, one {# element needs attention before export} other {# elements need attention before export}}", { count: issues.length })}</span>}
        <span role="status" aria-live="polite" className="lettering-save-state">{busy ? t("Saving…") : dirty ? t(draftStored ? "Unsaved · draft kept on this device" : "Unsaved · local recovery unavailable") : reviewPending ? t("Placement not reviewed") : t("Saved")}</span>
        <Button size="xs" variant="outline" className="lettering-icon-button" aria-label={t("Undo")} title={t("Undo")} disabled={pageLocked || (!history.past.length && !history.gesture)} onClick={() => dispatch({ type: "undo" })}><Undo2 size={16} aria-hidden="true" /></Button>
        <Button size="xs" variant="outline" className="lettering-icon-button" aria-label={t("Redo")} title={t("Redo")} disabled={pageLocked || !history.future.length} onClick={() => dispatch({ type: "redo" })}><Redo2 size={16} aria-hidden="true" /></Button>
        <Button data-lettering-save size="sm" disabled={pageLocked || !layout.state || (!dirty && !base.placement_review_needed)} title={reviewPending ? t("Check the lettering against this artwork, then confirm to record your placement review. Suggested positions are starting points, not detected empty spaces.") : undefined} onClick={() => void save(loadedArtUrl === artUrl)}>{reviewPending ? t("Confirm placement") : t("Save lettering")}</Button>
      </div>
    </div>
    <div className="lettering-notices">
    {error && <div><ErrorNotice error={error} operation="save" /><div className="flex flex-wrap gap-2 mt-2"><Button variant="outline" size="xs" onClick={() => void reload()} disabled={busy}>{t("Reload saved version")}</Button>{!fontsReady && <Button size="xs" onClick={() => { setError(null); setFontAttempt(n => n + 1); }}>{t("Retry fonts")}</Button>}</div></div>}
    {layout.error && <ErrorNotice error={layout.error} operation="preview" />}
    {!draftStored && dirty && <p role="alert" className="lettering-error">{t("This browser could not store your recovery draft. Save before closing or changing pages.")}</p>}
    {recovery && <div className="lettering-notice"><h4 className="font-bold">{t("Unsaved lettering found on this device")}</h4><p>{canRestore ? t("Restore it before continuing, or keep the saved version.") : t("This draft belongs to an older page or style revision. It will not be applied to newer work. Download it to recover wording, then keep the saved version.")}</p>
      {recovery.imageSha !== base.render_image_sha256 && canRestore && <p>{t("The artwork has changed. Restored placement will need another visual check.")}</p>}
      <div className="flex flex-wrap gap-2 mt-3">{canRestore && <Button size="sm" onClick={recover} disabled={!fontsReady}>{t("Restore draft")}</Button>}<Button size="sm" variant="outline" onClick={downloadRecovery}>{t("Download draft")}</Button><Button size="sm" variant="outline" onClick={() => {
        if (window.confirm(t("Discard this unsaved local draft and keep the saved version?"))) {
          clearLetteringDraft(draftKey);
          setRecovery(null);
        }
      }}>{t("Keep saved version")}</Button></div></div>}
    {base.source_stale && <div className="lettering-notice"><h4 className="font-bold">{t("The page plan changed")}</h4><p>{t("These placements are preserved, but cannot be published against a different allocation. Rebuild from the current plan to continue.")}</p><Button className="mt-3" variant="outline" disabled={busy} onClick={() => void rebuild()}>{t("Rebuild lettering")}</Button></div>}
    {disabled && <p className="lettering-notice">{t("Artwork is being revised. Your lettering is retained; finish editing after the new render is ready.")}</p>}
    </div>
    {bookStyleOpen && <div className="lettering-book-style-wrap"><BookStyleEditor project={project} initial={base.style} pagePreview={{ state: history.present, artUrl }} disabled={locked || dirty} onClose={() => setBookStyleOpen(false)} onApplied={async () => {
      await adoptBookChange();
      setBookStyleOpen(false);
    }} /></div>}
    {!fontsReady ? <p role="status" className="lettering-loading">{t("Loading the book’s bundled typefaces…")}</p> : layout.state && <div className="lettering-workspace" hidden={bookStyleOpen}>
      <LetteringCanvas guides={{
        faces: showFaces && faceGuides ? faceGuides : [],
        dragFaces: faceGuides ?? [],
        focus: focus ? { ...focus.mark, severity: focus.severity } : null,
      }} state={layout.state} style={base.style} artUrl={artUrl} onArtReady={setLoadedArtUrl} selected={selected} disabled={pageLocked} select={setSelected} focusText={() => textarea.current?.focus()} begin={() => dispatch({ type: "begin" })} preview={(id, value) => patch(id, value, true)} commit={() => dispatch({ type: "commit" })} cancel={() => dispatch({ type: "cancel" })} change={patch} />
      <aside className="lettering-inspector" aria-label={t("Lettering controls")}>
        <PlacementCheckPanel project={project} pageNumber={pageNumber} state={layout.state} evidence={base.evidence} checks={checks} locale={history.present.locale} disabled={pageLocked} focused={focusedCheck?.key ?? null} showFaces={showFaces} onShowFaces={setShowFaces}
          onFocus={(key, check) => { setFocusedCheck(old => old?.key === key ? null : { key, check }); if (check.element_id) setSelected(check.element_id); }}
          onFix={fixCheck} onFixAll={fixAll} onRelayout={relayout} onChecked={refreshEvidence} />
        {current ? <fieldset disabled={pageLocked} className="lettering-element-controls">
          <legend className="lettering-section-title">{t(roleNames[current.role])}{current.hidden && <span>{t("Hidden")}</span>}</legend>
          {translationStatus(current, history.present.locale) === "stale" && <div role="alert">
            <p>{t("The source wording changed. Review this translation before exporting.")}</p>
            <p lang="und">{current.text_by_locale.source}</p>
            <Button variant="outline" size="xs" onClick={() => patch(current.id, { translation_sources: { ...current.translation_sources, [history.present.locale]: current.text_by_locale.source } })}>{t("Confirm translation matches source")}</Button>
          </div>}
          <div><div className="lettering-copy-head"><FieldLabel htmlFor="lettering-copy">{t("Words on the page")} · {history.present.locale === "source" ? t("source") : history.present.locale}</FieldLabel><EmphasisButton onToggle={emphasize} /></div><TextAreaField ref={textarea} id="lettering-copy" className="lettering-copy-field" value={current.text_by_locale[history.present.locale] ?? ""} placeholder={history.present.locale !== "source" ? current.text_by_locale.source : t("Write some words…")} maxLength={10000} onFocus={() => dispatch({ type: "begin" })} onBlur={() => dispatch({ type: "commit" })} onKeyDown={event => {
            if ((event.metaKey || event.ctrlKey) && ["b", "i"].includes(event.key.toLowerCase())) { event.preventDefault(); emphasize(); }
          }} onChange={e => patch(current.id, { text_by_locale: { ...current.text_by_locale, [history.present.locale]: e.target.value } }, true)} />
          </div>
          <div className="lettering-small-actions">{canonical && history.present.locale === "source" && <Button variant="outline" size="xs" onClick={() => patch(current.id, { text_by_locale: { ...current.text_by_locale, source: canonical.text } })}>{t("Reset copy")}</Button>}
            <Button variant="outline" size="xs" onClick={() => patch(current.id, { placement: current.suggested_placement, tail_target: current.suggested_tail_target, rotation: 0, scale: 1, tight_box: true })}>{t("Reset placement")}</Button>
            <Button variant="outline" size="xs" onClick={remove}>{current.source_lettering_item_id ? t(current.hidden ? "Show" : "Hide") : t("Remove")}</Button></div>
          {current.resolved?.warnings.map(warning => <p key={warning} role="status" className="lettering-warning">{t(errors[warning] ?? warning)}</p>)}
          {current.resolved?.overflow && !current.resolved.warnings.length && <p className="lettering-warning">{t("This copy cannot fit at the readable minimum. Widen or heighten the box, or shorten the wording. Export waits for this to be fixed.")}</p>}
          {canonical?.delivery === "offscreen" && current.role === "speech" && <p className="lettering-hint">{t("Offscreen speech has no visible-speaker tail. Choose Radio for an intercom or phone, or Whisper only when the line is spoken quietly.")}</p>}
          {(!canonical || canonical.delivery === "onscreen") && ["speech", "thought"].includes(current.role) && <div className="lettering-pointer-controls">
            <label className="lettering-checkbox"><input type="checkbox" checked={!!current.tail_target} onChange={e => patch(current.id, { tail_target: e.target.checked ? (current.suggested_tail_target ?? defaultTailTarget(elementRect(current))) : null })} />{t("Balloon tail · drag its round handle")}</label>
            <Button variant="outline" size="xs" onClick={() => patch(current.id, { tail_target: defaultTailTarget(elementRect(current)) })}>{t("Reset pointer")}</Button>
            {current.tail_target && <TailCurve value={current.tail_bend ?? 0} onBegin={() => dispatch({ type: "begin" })} onPreview={bend => patch(current.id, { tail_bend: bend }, true)} onCommit={() => dispatch({ type: "commit" })} />}
            <p className="lettering-hint">{heads?.length ? t("Point toward the speaker. The placement check knows where faces are and can aim it for you.") : t("Point toward the speaker. Initial pointers are suggestions, not detected faces.")}</p>
          </div>}
          {["speech", "thought"].includes(current.role) && <BalloonJoin current={current} elements={layout.state.elements} locale={history.present.locale} onJoin={id => {
            const lead = id ? layout.state?.elements.find(e => e.id === id) : null;
            const placement = lead ? joinedPlacement(lead, current) : null;
            patch(current.id, { link_to: id, ...(placement ? { placement } : {}) });
          }} />}
          <details><summary>{t("Position & layer")}</summary><div className="mt-3 space-y-3">
          <label className="lettering-checkbox"><input type="checkbox" checked={current.tight_box} onChange={e => patch(current.id, { tight_box: e.target.checked })} />{t("Snug box around text")}</label>

            <div className="lettering-field-pair"><div><FieldLabel htmlFor="lettering-rotation">{t("Rotation")}</FieldLabel><input id="lettering-rotation" aria-label={t("Rotation")} type="range" min={-180} max={180} step={1} value={current.rotation} onPointerDown={() => dispatch({ type: "begin" })} onPointerUp={() => dispatch({ type: "commit" })} onBlur={() => dispatch({ type: "commit" })} onFocus={() => dispatch({ type: "begin" })} onChange={e => patch(current.id, { rotation: +e.target.value }, true)} /><span className="lettering-hint">{current.rotation}°</span></div>
              <div><FieldLabel htmlFor="lettering-scale">{t("Scale")}</FieldLabel><input id="lettering-scale" aria-label={t("Scale")} type="range" min={.25} max={3} step={.05} value={current.scale} onFocus={() => dispatch({ type: "begin" })} onBlur={() => dispatch({ type: "commit" })} onPointerDown={() => dispatch({ type: "begin" })} onPointerUp={() => dispatch({ type: "commit" })} onChange={e => patch(current.id, { scale: +e.target.value }, true)} /><span className="lettering-hint">{Math.round(current.scale * 100)}%</span></div></div>
            <div className="lettering-small-actions"><Button size="xs" variant="outline" disabled={current.z_index <= -1000} onClick={() => patch(current.id, { z_index: current.z_index - 1 })}>{t("Send backward")}</Button><Button size="xs" variant="outline" disabled={current.z_index >= 1000} onClick={() => patch(current.id, { z_index: current.z_index + 1 })}>{t("Bring forward")}</Button></div>
          </div></details>
          <details open key={current.id} className="lettering-local-style"><summary>{t("Style · this element only")}</summary><div className="mt-3"><p className="lettering-style-scope">{t(current.style_override ? "Custom style" : "Using book style")}</p><LetteringStyleControls key={current.id} role={current.role} value={styleFor(current, base.style)} base={styleFor({ ...current, style_override: null }, base.style)} onUseBase={() => patch(current.id, { style_override: null })} measure={measure} sample={sampleWords(textFor(current, history.present.locale), current.role)} onChange={style => patch(current.id, { style_override: style })} />{current.style_override && <Button variant="outline" size="xs" className="mt-3" onClick={() => patch(current.id, { style_override: null })}>{t("Use book style")}</Button>}</div></details>
        </fieldset> : <p className="lettering-hint p-4">{t("Select lettering on the artwork, or add new words.")}</p>}
        <section className="lettering-list-section">
          <details><summary>{t("Reading order")} <span className="lettering-list-count">{history.present.elements.length}</span></summary>
            <ol className="lettering-reading-order">{layout.state.elements.map((element, index) => <li key={element.id}><button type="button" className={`${selected === element.id ? "is-selected" : ""} ${element.hidden ? "is-hidden" : ""}`} onClick={() => { setSelected(element.id); requestAnimationFrame(() => textarea.current?.focus()); }} aria-pressed={selected === element.id}>
              <span className="lettering-order-number">{index + 1}</span><span className="min-w-0"><span className="lettering-list-role">{t(roleNames[element.role])}{element.hidden ? ` · ${t("Hidden")}` : element.resolved?.overflow ? ` · ${t("Needs attention")}` : ""}</span><span className="lettering-list-copy">{textFor(element, history.present.locale) || t("Write some words…")}</span></span></button></li>)}</ol>
          </details>
          <Button variant="outline" size="sm" disabled={pageLocked || history.present.elements.length >= 200} onClick={() => setAddOpen(value => !value)} aria-expanded={addOpen} aria-controls="lettering-add-form">{t("Add lettering")}</Button>
          {addOpen && <div id="lettering-add-form" className="lettering-add-form">
            <p className="lettering-hint">{t("Choose what to add. It appears on the page in this book’s style, ready for words.")}</p>
            <LetteringRoleTiles mode="add" label={t("Type of lettering")} style={base.style} measure={measure} disabled={pageLocked || history.present.elements.length >= 200} onPick={role => { if (!pageLocked && history.present.elements.length < 200) add(role); }} />
            <div className="lettering-small-actions"><Button size="sm" variant="outline" onClick={() => setAddOpen(false)}>{t("Cancel")}</Button></div>
          </div>}
        </section>
      </aside>
    </div>}
  </div>;
}
export function BookStyleEditor({ project, initial, pagePreview, disabled, onClose, onApplied }: {
  project: string;
  initial: LetteringStyle;
  pagePreview?: { state: PageLettering; artUrl: string };
  disabled: boolean;
  onClose: () => void;
  onApplied: () => Promise<void>;
}) {
  const { t } = useI18n(), [role, setRole] = useState<RoleName>("caption"), [busy, setBusy] = useState(false), [error, setError] = useState<Error | string | null>(null);
  const [saved, setSaved] = useState(initial);
  const [history, setHistory] = useState({ past: [] as LetteringStyle[], present: initial, future: [] as LetteringStyle[] });
  const style = history.present;
  const signature = (value: LetteringStyle) => JSON.stringify({ label: value.label, roles: value.roles });
  const dirty = signature(style) !== signature(saved);
  const [fontsReady, setFontsReady] = useState(false), [fontAttempt, setFontAttempt] = useState(0);
  function setStyle(next: LetteringStyle) {
    setHistory(old => signature(old.present) === signature(next) ? old : ({ past: [...old.past, old.present].slice(-60), present: next, future: [] }));
  }
  useEffect(() => {
    let live = true;
    loadFonts().then(() => { if (live) setFontsReady(true); }).catch(error => { if (live) setError(error instanceof Error ? error : message(error)); });
    return () => { live = false; };
  }, [fontAttempt]);
  useEffect(() => {
    if (!dirty && !busy) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    const navigate = (event: MouseEvent) => {
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!link || link.getAttribute("href")?.startsWith("#")) return;
      if (busy || !window.confirm(t("Discard unsaved book lettering changes?"))) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", warn); document.removeEventListener("click", navigate, true); };
  }, [dirty, busy, t]);
  function close() {
    if (!dirty || window.confirm(t("Discard unsaved book lettering changes?"))) onClose();
  }
  const [presetName, setPresetName] = useState(""), [presetRevision, setPresetRevision] = useState(0);
  const measure = useMemo(() => fontsReady ? canvasMeasure() : null, [fontsReady]);
  const sample = t(({ caption: "A story takes shape.", speech: "There you are! I have a *story* to tell you.", thought: "What if the story took a *different* turn?", sfx: "CRASH!" })[role]);
  const preview = useMemo(() => {
    if (!measure) return { svg: "", overflow: false, error: null };
    const placement = { x: .36, y: .28, width: .28, height: .24 };
    const state: PageLettering = {
      revision: 1, content_sha256: "", page_number: 1, comic_page_sha256: "0".repeat(64), style_sha256: style.content_sha256, locale: "source", canvas_aspect_ratio: 2,
      reviewed_against_render_revision: null, reviewed_against_image_sha256: null,
      elements: [{ id: "style-preview", source_lettering_item_id: null, role, text_by_locale: { source: sample }, suggested_placement: placement, placement, hidden: false, style_override: null, tail_target: role === "speech" || role === "thought" ? { x: .59, y: .55 } : null, suggested_tail_target: null, rotation: 0, scale: 2.5, z_index: 0, tight_box: true, resolved: null }]
    };
    try {
      const resolved = resolvePage(state, style, measure);
      return { svg: renderOverlay(resolved, style), overflow: resolved.elements[0].resolved?.overflow, error: null };
    }
    catch (error) {
      return { svg: "", overflow: false, error: message(error) };
    }
  }, [style, role, sample, measure]);
  const pageSample = useMemo(() => {
    if (!pagePreview || !measure) return null;
    try {
      return { svg: renderOverlay(resolvePage(pagePreview.state, style, measure), style), error: null };
    } catch (error) {
      return { svg: "", error: message(error) };
    }
  }, [pagePreview, style, measure]);
  const presets = useQuery({ queryKey: ["lettering-presets", project], queryFn: () => getBookLetteringStyle(project), staleTime: Infinity });
  async function apply() {
    setBusy(true); setError(null); try {
      const next = await putBookLetteringStyle(project, style, saved.revision);
      setSaved(next);
      setHistory(old => ({ ...old, present: next }));
      await onApplied();
    }
      catch (error) {
        setError(error instanceof Error ? error : message(error));
      }
      finally {
      setBusy(false);
    }
  }
  return <Surface padding="lg" border="soft" shadow="none" className="lettering-book-style"><style>{fontCSS()}</style><div><h4 className="font-display text-xl font-bold">{t("Book lettering style")}</h4><p className="lettering-hint">{t("All pages · local styles stay unchanged")}</p></div>
    <div className="lettering-small-actions">
      <Button variant="outline" size="xs" disabled={disabled || busy || !history.past.length} onClick={() => { setHistory(old => ({ past: old.past.slice(0, -1), present: old.past.at(-1)!, future: [old.present, ...old.future] })); setPresetName(""); setPresetRevision(n => n + 1); }}>{t("Undo style")}</Button>
      <Button variant="outline" size="xs" disabled={disabled || busy || !history.future.length} onClick={() => { setHistory(old => ({ past: [...old.past, old.present], present: old.future[0], future: old.future.slice(1) })); setPresetName(""); setPresetRevision(n => n + 1); }}>{t("Redo style")}</Button>
      <span role="status" className="lettering-hint">{t(dirty ? "Unsaved style changes" : "Saved style")}</span>
    </div>
    {!fontsReady && <p role="status">{t("Loading the book’s bundled typefaces…")}</p>}
    {error && <ErrorNotice error={error} operation="save" />}<div className="lettering-small-actions"><Button disabled={disabled || busy || !fontsReady || !!preview.error || !!pageSample?.error || !!preview.overflow} onClick={() => void apply()}>{busy ? t("Reflowing the book…") : t("Apply to book")}</Button><Button variant="outline" disabled={busy} onClick={close}>{t("Cancel")}</Button>{!fontsReady && error && <Button variant="outline" onClick={() => { setError(null); setFontAttempt(n => n + 1); }}>{t("Retry fonts")}</Button>}</div>
    <fieldset aria-label={t("Book lettering style")} disabled={disabled || busy} className="lettering-book-style-fields">
      <div className="lettering-book-controls">
        <div><span className="ui-field-label">{t("Book look")}</span><p className="lettering-hint mb-2">{presets.isPending ? t("Loading presets…") : presetName ? t("Starting from a preset. Fine-tune any role below.") : t("Custom style. Pick a look to start over from it.")}</p>
          {presets.data && <LetteringPresetTiles presets={presets.data.presets} value={presetName} measure={measure} onPick={name => { const preset = presets.data?.presets[name]; if (preset) { setStyle({ ...preset, source_direction: initial.source_direction, revision: initial.revision }); setPresetName(name); setPresetRevision(value => value + 1); } }} />}</div>
        {presets.isError && <ErrorNotice error={presets.error} operation="load" onRetry={() => void presets.refetch()} />}
        <div><span className="ui-field-label">{t("Type of lettering")}</span><LetteringRoleTiles mode="choose" label={t("Type of lettering")} style={style} measure={measure} value={role} onPick={setRole} /></div>
        <LetteringStyleControls key={`${role}:${presetRevision}`} idPrefix="book-lettering" role={role} value={style.roles[role]} base={saved.roles[role]} baseLabel="Saved style" measure={measure} sample={sampleWords(sample, role)} onChange={value => { setStyle({ ...style, roles: { ...style.roles, [role]: value } }); setPresetName(""); }} />
        {initial.source_direction && <details><summary>{t("Selected creative direction")}</summary><p className="lettering-hint mt-2">{initial.source_direction}</p></details>}
      </div>
      <figure className="lettering-book-preview"><figcaption>{t("Live sample")} · {t(roleNames[role])}</figcaption>{pagePreview && pageSample && <>
        <div className="lettering-book-page-preview">
          <div className="lettering-book-page" style={{ aspectRatio: pagePreview.state.canvas_aspect_ratio, width: `min(100%, calc(min(52dvh, 680px) * ${pagePreview.state.canvas_aspect_ratio}))` }}>
            <img src={pagePreview.artUrl} alt={t("Page artwork")} />
            <div className="lettering-svg" dangerouslySetInnerHTML={{ __html: pageSample.svg }} />
          </div>
        </div>
        <p className="lettering-hint my-3">{t("Preview only · local styles stay unchanged")}</p>
        {pageSample.error && <ErrorNotice error={pageSample.error} operation="preview" />}
      </>}<div className="lettering-book-preview-art" role="img" aria-label={`${t("Live sample")}: ${sample}`} dangerouslySetInnerHTML={{ __html: preview.svg }} />{preview.error && <ErrorNotice error={preview.error} operation="preview" />}{preview.overflow && <p role="status" className="lettering-warning">{t("The sample does not fit. Adjust the size or spacing.")}</p>}</figure>
    </fieldset>
  </Surface>;
}
