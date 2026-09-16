import { useEffect, useMemo, useReducer, useRef, useState, type KeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { canvasMeasure, fontCSS, loadFonts, resolvePage, roleFor, textFor } from "@lettering-engine";
import { getPageLettering, putPageLettering, resetPageLettering, getBookLetteringStyle, putBookLetteringStyle, type HybridLetteringResponse, type PageLettering, type LetteringElement, type LetteringStyle, type RoleName, } from "../../api/lettering";
import { pageRenderUrl } from "../../api/pages";
import { ApiError } from "../../api/client";
import { clearLetteringDraft, editableSignature, historyReducer, initialHistory, letteringDraftKey, readLetteringDraft, writeLetteringDraft } from "../../lib/letteringHistory";
import { Button } from "../ui/Button";
import { FieldLabel, SelectField, TextAreaField, TextField } from "../ui/Field";
import { Surface } from "../ui/Surface";
import { Toolbar } from "../composites/Toolbar";
import { LetteringCanvas } from "./LetteringCanvas";
import { LetteringStyleControls } from "./LetteringStyleControls";
import { useI18n } from "../../i18n";
import "./lettering.css";
const roleNames: Record<RoleName, string> = { caption: "Caption", speech: "Speech", thought: "Thought", sfx: "Sound effect" };
const errors: Record<string, string> = {
  missing_translation: "This language still uses the source wording. Add its translation before exporting.",
  outside_page: "Part of this lettering is outside the page. Move it inward or reduce its rotation or scale.",
  unsupported_script: "The bundled typefaces do not support this writing system. This page cannot be exported with missing glyphs.",
  font_script_mismatch: "Choose M PLUS 1p for supported Japanese or Chinese characters.",
  missing_glyphs: "This font lacks some characters. Choose a supported bundled font or change the copy; system font fallback cannot be exported.",
  empty_copy: "Write some words or hide this element before exporting.",
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
    return <Surface padding="lg" border="soft" shadow="none"><p role="alert">{message(query.error)}</p><Button className="mt-3" variant="outline" onClick={() => void query.refetch()}>{t("Try again")}</Button></Surface>;
  if (query.data.mode === "baked")
    return <Surface padding="lg" border="soft" shadow="none"><h3 className="font-display text-xl">{t("Lettering is part of this artwork")}</h3><p className="mt-2 max-w-prose text-sm leading-6">{t(query.data.message)}</p></Surface>;
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
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [fontsReady, setFontsReady] = useState(false), [fontAttempt, setFontAttempt] = useState(0);
  const draftKey = letteringDraftKey(project, pageNumber);
  const [recovery, setRecovery] = useState(() => {
    const draft = readLetteringDraft(draftKey);
    return draft && editableSignature(draft.state) !== editableSignature(initial.state) ? draft : null;
  });
  const [draftStored, setDraftStored] = useState(true), [language, setLanguage] = useState(""), [bookStyleOpen, setBookStyleOpen] = useState(false);
  const [loadedArtUrl, setLoadedArtUrl] = useState<string | null>(null);
  const artUrl = pageRenderUrl(project, pageNumber, base.render_revision);
  const textarea = useRef<HTMLTextAreaElement>(null), root = useRef<HTMLDivElement>(null);
  const dirty = editableSignature(history.present) !== editableSignature(base.state) || base.needs_save;
  const canRestore = !!recovery && recovery.baseRevision === base.saved_revision && recovery.sourceSha === base.state.comic_page_sha256 && recovery.styleSha === base.style.content_sha256;
  const locked = busy || disabled || !fontsReady || !!recovery || base.source_stale;
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
  const issues = layout.state?.elements.filter(e => !e.hidden && (e.resolved?.overflow || e.resolved?.warnings.length)) ?? [];
  const locales = [...new Set(["source", history.present.locale, ...history.present.elements.flatMap(e => Object.keys(e.text_by_locale))])];
  useEffect(() => {
    let live = true;
    loadFonts().then(() => {
      if (live)
        setFontsReady(true);
    }).catch(error => {
      if (live)
        setError(message(error));
    });
    return () => { live = false; };
  }, [fontAttempt]);
  useEffect(() => {
    if (recovery || !dirty)
      return;
    const saved = writeLetteringDraft(draftKey, {
      version: 1, baseRevision: base.saved_revision, sourceSha: base.state.comic_page_sha256,
      styleSha: base.style.content_sha256, imageSha: base.render_image_sha256, state: history.present, updatedAt: new Date().toISOString()
    });
    // Storage can be disabled or full. This is a safety signal, never a claim of server persistence.
    queueMicrotask(() => setDraftStored(saved));
  }, [history.present, base, draftKey, dirty, recovery]);
  useEffect(() => {
    if (!dirty)
      return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function changeState(state: PageLettering, preview = false) { dispatch({ type: preview ? "preview" : "change", value: state }); setError(null); }
  function patch(id: string, patch: Partial<LetteringElement>, preview = false) { changeState({ ...history.present, elements: history.present.elements.map(e => e.id === id ? { ...e, ...patch } : e) }, preview); }
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
    if (locked || !layout.state || layout.error)
      return;
    setBusy(true);
    setError(null);
    try {
      acknowledge(await putPageLettering(project, pageNumber, layout.state, base, markReviewed));
    }
    catch (error) {
      if (error instanceof ApiError && error.status === 409)
        setError(t("A newer page, artwork, or book style was saved elsewhere. Your draft is intact. Reload the saved version to compare and recover it; this editor will not overwrite newer work."));
      else
        setError(message(error));
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
      dispatch({ type: "reset", value: next.state });
      setRecovery(draft && editableSignature(draft.state) !== editableSignature(next.state) ? draft : null);
      setError(null);
    }
    catch (error) {
      setError(message(error));
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
      setError(message(error));
    }
    finally {
      setBusy(false);
    }
  }
  function add(role: RoleName) {
    const id = `custom-${crypto.randomUUID()}`, placement = { x: .28, y: .38, width: .44, height: .16 };
    const element: LetteringElement = {
      id, source_lettering_item_id: null, role, text_by_locale: { source: "", ...(history.present.locale !== "source" ? { [history.present.locale]: "" } : {}) }, suggested_placement: placement, placement,
      hidden: false, style_override: null, tail_target: null, suggested_tail_target: null, rotation: 0, scale: 1, z_index: 0, tight_box: true, resolved: null
    };
    changeState({ ...history.present, elements: [...history.present.elements, element] });
    setSelected(id);
    requestAnimationFrame(() => textarea.current?.focus());
  }
  function remove() {
    if (!current)
      return; if (current.source_lettering_item_id)
      patch(current.id, { hidden: !current.hidden });
    else {
      changeState({ ...history.present, elements: history.present.elements.filter(e => e.id !== current.id) });
      setSelected(null);
    }
  }
  function keys(event: KeyboardEvent<HTMLDivElement>) {
    if (locked)
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
      setError(message(error));
    }
  }
  function downloadRecovery() {
    if (!recovery)
      return; const blob = new Blob([JSON.stringify(recovery, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = `page-${pageNumber}-lettering-draft.json`; link.click(); URL.revokeObjectURL(url);
  }
  return <div ref={root} className="lettering-editor" onKeyDown={keys}>
    <style>{fontCSS()}</style>
    <Toolbar className="lettering-main-toolbar" bottomRule>
      <div><h3 className="font-display text-xl font-bold">{t("Lettering desk")}</h3><p className="lettering-hint">{t("Words, not a redraw. Changes here never spend image credits.")}</p></div>
      <div className="lettering-toolbar-actions">
        <span role="status" aria-live="polite" className="lettering-save-state">{busy ? t("Saving…") : dirty ? t(draftStored ? "Unsaved · draft kept on this device" : "Unsaved · local recovery unavailable") : t("Saved")}</span>
        <Button size="xs" variant="outline" disabled={locked || (!history.past.length && !history.gesture)} onClick={() => dispatch({ type: "undo" })}>{t("Undo")}</Button>
        <Button size="xs" variant="outline" disabled={locked || !history.future.length} onClick={() => dispatch({ type: "redo" })}>{t("Redo")}</Button>
        <Button data-lettering-save size="sm" disabled={locked || !layout.state || (!dirty && !base.placement_review_needed)} onClick={() => void save(loadedArtUrl === artUrl)}>{t("Save lettering")}</Button>
      </div>
    </Toolbar>
    {error && <div role="alert" className="lettering-error"><p>{error}</p><div className="flex flex-wrap gap-2 mt-2"><Button variant="outline" size="xs" onClick={() => void reload()} disabled={busy}>{t("Reload saved version")}</Button>{!fontsReady && <Button size="xs" onClick={() => { setError(null); setFontAttempt(n => n + 1); }}>{t("Retry fonts")}</Button>}</div></div>}
    {layout.error && <p role="alert" className="lettering-error">{layout.error}</p>}
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
    {base.placement_review_needed && !base.source_stale && <p className="lettering-hint">{t("Check the lettering against this artwork, then save to record your placement review. Suggested positions are starting points, not detected empty spaces.")}</p>}
    <div className="lettering-context-toolbar">
      <div className="lettering-language"><FieldLabel htmlFor="lettering-locale">{t("Language")}</FieldLabel><SelectField id="lettering-locale" value={history.present.locale} disabled={locked} onChange={e => changeState({ ...history.present, locale: e.target.value })}>{locales.map(locale => <option key={locale} value={locale}>{locale === "source" ? t("Source language") : locale}</option>)}</SelectField></div>
      <form className="lettering-add-language" onSubmit={e => {
        e.preventDefault(); const next = language.trim(); if (/^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$/.test(next)) {
          changeState({ ...history.present, locale: next });
          setLanguage("");
        }
        else
          setError(t("Use a language code such as es, fr, or pt-BR."));
      }}><FieldLabel htmlFor="lettering-new-locale">{t("Add a language")}</FieldLabel><div className="flex gap-1"><TextField id="lettering-new-locale" placeholder="es / fr / pt-BR" value={language} onChange={e => setLanguage(e.target.value)} disabled={locked} maxLength={40} /><Button variant="outline" size="xs" type="submit" disabled={locked || !language.trim()}>{t("Add")}</Button></div></form>
      <Button variant="outline" size="sm" disabled={locked || dirty} title={dirty ? t("Save this page before changing the book-wide style") : undefined} onClick={() => setBookStyleOpen(v => !v)} aria-expanded={bookStyleOpen}>{t("Book lettering style")}</Button>
    </div>
    {bookStyleOpen && <BookStyleEditor project={project} initial={base.style} disabled={locked || dirty} onClose={() => setBookStyleOpen(false)} onApplied={async () => {
      const next = await getPageLettering(project, pageNumber); if (next.mode === "hybrid")
        acknowledge(next, true); setBookStyleOpen(false);
    }} />}
    {!fontsReady ? <p role="status">{t("Loading the book’s bundled typefaces…")}</p> : layout.state && <div className="lettering-workspace">
      <LetteringCanvas state={layout.state} style={base.style} artUrl={artUrl} onArtReady={setLoadedArtUrl} selected={selected} disabled={locked} select={setSelected} focusText={() => textarea.current?.focus()} begin={() => dispatch({ type: "begin" })} preview={(id, value) => patch(id, value, true)} commit={() => dispatch({ type: "commit" })} cancel={() => dispatch({ type: "cancel" })} change={patch} />
      <aside className="lettering-inspector" aria-label={t("Lettering controls")}>
        <section className="lettering-list-section"><h4 className="lettering-section-title">{t("Reading order")} <span>{history.present.elements.length}</span></h4>
          <ol className="lettering-reading-order">{layout.state.elements.map((element, index) => <li key={element.id}><button type="button" className={`${selected === element.id ? "is-selected" : ""} ${element.hidden ? "is-hidden" : ""}`} onClick={() => setSelected(element.id)} aria-pressed={selected === element.id}>
            <span className="lettering-order-number">{index + 1}</span><span className="min-w-0"><span className="lettering-list-role">{t(roleNames[element.role])}{element.hidden ? ` · ${t("Hidden")}` : element.resolved?.overflow ? ` · ${t("Needs attention")}` : ""}</span><span className="lettering-list-copy">{textFor(element, history.present.locale) || t("Write some words…")}</span></span></button></li>)}</ol>
          <div className="lettering-add-actions">{(Object.keys(roleNames) as RoleName[]).map(role => <Button key={role} variant="outline" size="xs" disabled={locked || history.present.elements.length >= 200} onClick={() => add(role)}>+ {t(roleNames[role])}</Button>)}</div>
        </section>
        {current ? <fieldset disabled={locked} className="lettering-element-controls">
          <legend className="lettering-section-title">{t("Selected lettering")}</legend>
          <div><FieldLabel htmlFor="lettering-copy">{t("Words on the page")} · {history.present.locale === "source" ? t("source") : history.present.locale}</FieldLabel><TextAreaField ref={textarea} id="lettering-copy" className="lettering-copy-field" value={current.text_by_locale[history.present.locale] ?? ""} placeholder={history.present.locale !== "source" ? current.text_by_locale.source : t("Write some words…")} maxLength={10000} onFocus={() => dispatch({ type: "begin" })} onBlur={() => dispatch({ type: "commit" })} onChange={e => patch(current.id, { text_by_locale: { ...current.text_by_locale, [history.present.locale]: e.target.value } }, true)} />
            <p className="lettering-hint">{t("Display wording only. The adapted story stays unchanged.")}</p>
          </div>
          {canonical && <details className="lettering-source"><summary>{t("Canonical source copy")}{canonical.speaker ? ` · ${canonical.speaker}` : ""}</summary><p>{canonical.text}</p><p className="lettering-hint">{t("Panel")} {canonical.panel_number} · {canonical.delivery}</p></details>}
          <div className="lettering-small-actions">{canonical && <Button variant="outline" size="xs" onClick={() => patch(current.id, { text_by_locale: { ...current.text_by_locale, [history.present.locale]: canonical.text } })}>{t("Reset copy")}</Button>}
            <Button variant="outline" size="xs" onClick={() => patch(current.id, { placement: current.suggested_placement, tail_target: current.suggested_tail_target, rotation: 0, scale: 1, tight_box: true })}>{t("Reset placement")}</Button>
            <Button variant="outline" size="xs" onClick={remove}>{current.source_lettering_item_id ? t(current.hidden ? "Show" : "Hide") : t("Remove")}</Button></div>
          {current.resolved?.warnings.map(warning => <p key={warning} role="status" className="lettering-warning">{t(errors[warning] ?? warning)}</p>)}
          {current.resolved?.overflow && !current.resolved.warnings.length && <p className="lettering-warning">{t("This copy cannot fit at the readable minimum. Widen or heighten the box, or shorten the wording. Export waits for this to be fixed.")}</p>}
          <p className="lettering-hint">{t("Resolved size")}: {current.resolved?.font_size} · {current.resolved?.lines.length} {t("lines")}</p>
          <label className="lettering-checkbox"><input type="checkbox" checked={current.tight_box} onChange={e => patch(current.id, { tight_box: e.target.checked })} />{t("Snug box around text")}</label>
          {(!canonical || canonical.delivery === "onscreen") && ["speech", "thought"].includes(current.role) && <label className="lettering-checkbox"><input type="checkbox" checked={!!current.tail_target} onChange={e => patch(current.id, { tail_target: e.target.checked ? (current.suggested_tail_target ?? { x: Math.min(.97, current.placement.x + current.placement.width + .06), y: Math.min(.97, current.placement.y + current.placement.height + .08) }) : null })} />{t("Balloon tail · drag its round handle")}</label>}
          <details><summary>{t("Position & layer")}</summary><div className="mt-3 space-y-3">
            <div className="lettering-field-pair"><div><FieldLabel htmlFor="lettering-rotation">{t("Rotation")}</FieldLabel><input id="lettering-rotation" aria-label={t("Rotation")} type="range" min={-180} max={180} step={1} value={current.rotation} onPointerDown={() => dispatch({ type: "begin" })} onPointerUp={() => dispatch({ type: "commit" })} onBlur={() => dispatch({ type: "commit" })} onFocus={() => dispatch({ type: "begin" })} onChange={e => patch(current.id, { rotation: +e.target.value }, true)} /><span className="lettering-hint">{current.rotation}°</span></div>
              <div><FieldLabel htmlFor="lettering-scale">{t("Scale")}</FieldLabel><input id="lettering-scale" aria-label={t("Scale")} type="range" min={.25} max={3} step={.05} value={current.scale} onFocus={() => dispatch({ type: "begin" })} onBlur={() => dispatch({ type: "commit" })} onPointerDown={() => dispatch({ type: "begin" })} onPointerUp={() => dispatch({ type: "commit" })} onChange={e => patch(current.id, { scale: +e.target.value }, true)} /><span className="lettering-hint">{Math.round(current.scale * 100)}%</span></div></div>
            <div className="lettering-small-actions"><Button size="xs" variant="outline" disabled={current.z_index <= -1000} onClick={() => patch(current.id, { z_index: current.z_index - 1 })}>{t("Send backward")}</Button><Button size="xs" variant="outline" disabled={current.z_index >= 1000} onClick={() => patch(current.id, { z_index: current.z_index + 1 })}>{t("Bring forward")}</Button></div>
          </div></details>
          <section className="lettering-local-style"><h4 className="lettering-section-title">{t(current.style_override ? "This element’s style" : "Inherited book style")}</h4><LetteringStyleControls value={roleFor(current, base.style)} onChange={style => patch(current.id, { style_override: style })} />{current.style_override && <Button variant="outline" size="xs" className="mt-3" onClick={() => patch(current.id, { style_override: null })}>{t("Use book style")}</Button>}</section>
        </fieldset> : <p className="lettering-hint p-4">{t("Choose lettering on the page or in the reading-order list. Add a caption to a silent page when needed.")}</p>}
      </aside>
    </div>}
    {issues.length > 0 && <p className="lettering-warning" role="status">{issues.length} {t("visible elements need attention before export. You can still save your work.")}</p>}
    <p className="lettering-hint">{t("Ctrl / ⌘ S saves. Ctrl / ⌘ Z undoes page edits. Text fields keep their normal typing undo. Hidden source copy can always be restored.")}</p>
  </div>;
}
function BookStyleEditor({ project, initial, disabled, onClose, onApplied }: {
  project: string;
  initial: LetteringStyle;
  disabled: boolean;
  onClose: () => void;
  onApplied: () => Promise<void>;
}) {
  const { t } = useI18n(), [style, setStyle] = useState(initial), [role, setRole] = useState<RoleName>("caption"), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const presets = useQuery({ queryKey: ["lettering-presets", project], queryFn: () => getBookLetteringStyle(project), staleTime: Infinity });
  async function apply() {
    setBusy(true); setError(null); try {
      await putBookLetteringStyle(project, style, initial.revision);
      await onApplied();
    }
      catch (error) {
        setError(message(error));
      }
      finally {
      setBusy(false);
    }
  }
  return <Surface padding="lg" border="soft" shadow="none" className="lettering-book-style"><div><h4 className="font-display text-xl font-bold">{t("One lettering style for the book")}</h4><p className="lettering-hint">{t("Applies to every inheriting element. Local overrides remain. All pages reflow without regenerating artwork.")}</p></div>
    <fieldset disabled={disabled || busy}><div className="lettering-preset-grid">{Object.entries(presets.data?.presets ?? {}).map(([name, preset]) => <button type="button" key={name} onClick={() => setStyle({ ...preset, source_direction: initial.source_direction, revision: initial.revision })} className="lettering-preset"><span style={{ fontFamily: preset.roles.caption.font, background: preset.roles.caption.fill, color: preset.roles.caption.color }}>{t("A story takes shape.")}</span><strong>{preset.label}</strong></button>)}</div>
      <div className="lettering-book-style-fields"><div><FieldLabel htmlFor="lettering-style-role">{t("Style role")}</FieldLabel><SelectField id="lettering-style-role" value={role} onChange={e => setRole(e.target.value as RoleName)}>{(Object.keys(roleNames) as RoleName[]).map(role => <option key={role} value={role}>{t(roleNames[role])}</option>)}</SelectField>{initial.source_direction && <details className="mt-4"><summary>{t("Selected creative direction")}</summary><p className="lettering-hint mt-2">{initial.source_direction}</p></details>}</div><LetteringStyleControls idPrefix="book-lettering" value={style.roles[role]} onChange={value => setStyle({ ...style, roles: { ...style.roles, [role]: value } })} /></div>
    </fieldset>{error && <p role="alert" className="lettering-error">{error}</p>}<div className="flex gap-2 mt-4"><Button disabled={disabled || busy} onClick={() => void apply()}>{busy ? t("Reflowing the book…") : t("Apply to book")}</Button><Button variant="outline" disabled={busy} onClick={onClose}>{t("Cancel")}</Button></div>
  </Surface>;
}
