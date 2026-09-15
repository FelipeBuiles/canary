import { useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, Plus, Redo2, Save, Undo2 } from "lucide-react";
import { applyBookLetteringStyle, getLettering, getLetteringPresets, previewLettering, resetLettering, saveLettering } from "../../api/lettering";
import type { EditableLettering, LetteringElement, LetteringKind, LetteringRole, PageLettering } from "../../api/lettering";
import { listCompletePages, pageRenderUrl } from "../../api/pages";
import { Button } from "../ui/Button";
import { Surface } from "../ui/Surface";
import { accountIdentity } from "../../lib/accountEpoch";
import { downloadLetteringDraft, readLocalDraft, draftIdentity, elementCopy, letteringHistory, moveBox, resizeBox } from "./letteringHistory";

const kinds: [LetteringKind, string][] = [["caption", "Narration"], ["dialogue", "Speech"], ["thought", "Thought"], ["sfx", "Sound effect"]];
const fieldClass = "min-h-11 min-w-0 w-full border border-ink-black/30 bg-bristol px-2 py-2 font-body text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red";
const message = (error: unknown) => error instanceof Error ? error.message : "Could not save lettering. Your draft is still here.";

export function LetteringWorkspace({ project, pageNumber, onDirtyChange }: {
  project: string; pageNumber: number; onDirtyChange: (dirty: boolean) => void;
}) {
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState("");
  async function resetStalePage() {
    if (!window.confirm("Reset presentation for the current Plan? Saved lettering revisions are retained; canonical story copy and artwork are unchanged.")) return;
    setResetting(true); setResetError("");
    try {
      const pages = await listCompletePages(project);
      const current = pages.pages.find((p) => p.page.page_number === pageNumber);
      await resetLettering(project, pageNumber, current?.lettering?.sha256 ?? null);
      await query.refetch();
    } catch (cause) { setResetError(message(cause)); }
    finally { setResetting(false); }
  }
  const query = useQuery({ queryKey: ["project", project, "lettering", pageNumber], queryFn: () => getLettering(project, pageNumber), retry: false });
  if (query.isPending) return <p role="status" className="p-6">Opening lettering workspace…</p>;
  if (query.isError) return <Surface padding="lg"><p role="alert">{resetError || message(query.error)}</p><div className="mt-4 flex gap-3"><Button variant="outline" onClick={() => void query.refetch()}>Try again</Button>{/older Plan|Plan changed|reservations are stale/i.test(message(query.error)) && <Button disabled={resetting} onClick={() => void resetStalePage()}>Reset lettering for current Plan</Button>}</div></Surface>;
  if (query.data.mode === "baked") return <Surface padding="lg"><h3 className="font-display text-xl">Lettering is part of this artwork</h3><p className="mt-3 max-w-prose">{query.data.message} Existing artwork and exports remain unchanged.</p></Surface>;
  return <LetteringEditor key={`${project}:${pageNumber}`} project={project} initial={query.data} onDirtyChange={onDirtyChange} />;
}

export function LetteringEditor({ project, initial, onDirtyChange }: { project: string; initial: EditableLettering; onDirtyChange: (dirty: boolean) => void }) {
  const qc = useQueryClient();
  const [history, dispatch] = useReducer(letteringHistory, { past: [], present: initial.state, future: [] });
  const state = history.present;
  const draftKey = `canary-lettering:${accountIdentity ?? "local"}:${project}:${initial.state.page_number}:${initial.state.comic_page_sha256}`;
  const [recovery, setRecovery] = useState(() => {
    const saved = readLocalDraft(draftKey);
    return saved && draftIdentity(saved.state) !== draftIdentity(initial.state) ? saved : null;
  });
  const typing = useRef(false);
  const currentRef = useRef(state); currentRef.current = state;
  const [preview, setPreview] = useState(initial);
  const [savedIdentity, setSavedIdentity] = useState(initial.saved_sha256 ? draftIdentity(initial.state) : "");
  const expected = useRef(initial.saved_sha256);
  const [selectedId, setSelectedId] = useState(initial.state.elements[0]?.id ?? "");
  const [zoom, setZoom] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [localeInput, setLocaleInput] = useState("");
  const [showArtOnly, setShowArtOnly] = useState(false);
  const [gesture, setGesture] = useState<{ id: string; dx: number; dy: number; mode: "move" | "resize" | "tail" } | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const svg = useRef<HTMLDivElement>(null);
  const copyInput = useRef<HTMLTextAreaElement>(null);
  const activeGesture = useRef<{ id: string; x: number; y: number; width: number; height: number; mode: "move" | "resize" | "tail" } | null>(null);
  const previewSequence = useRef(0);
  const selected = state.elements.find((element) => element.id === selectedId);
  const dirty = draftIdentity(state) !== savedIdentity;
  const presets = useQuery({ queryKey: ["project", project, "lettering-presets"], queryFn: () => getLetteringPresets(project) });

  useEffect(() => {
    if (recovery) return;
    try {
      if (dirty) sessionStorage.setItem(draftKey, JSON.stringify({ base_sha256: expected.current, state }));
      else sessionStorage.removeItem(draftKey);
    } catch { /* Storage unavailable: the in-memory draft and Download draft still work. */ }
  }, [state, dirty, draftKey, recovery]);

  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const leave = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [dirty]);

  useEffect(() => {
    const sequence = ++previewSequence.current;
    if (draftIdentity(state) === draftIdentity(preview.state)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setPreviewing(true);
      previewLettering(project, state, controller.signal).then((result) => {
        if (sequence !== previewSequence.current || draftIdentity(currentRef.current) !== draftIdentity(state)) return;
        setPreview(result);
        dispatch({ type: "resolve", value: result.state });
        setError("");
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted && sequence === previewSequence.current) setError(message(cause));
      }).finally(() => { if (sequence === previewSequence.current) setPreviewing(false); });
    }, 400);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [state, project, preview.state]);

  function edit(next: PageLettering, coalesce = false) {
    dispatch({ type: "edit", coalesce, value: { ...next, reviewed_against_render_revision: null } });
    setNotice("");
  }
  function changeElement(id: string, patch: Partial<LetteringElement>, coalesce = false) {
    edit({ ...state, elements: state.elements.map((e) => e.id === id ? { ...e, ...patch } : e) }, coalesce);
  }
  const role = selected ? selected.style_override ?? state.style[selected.kind] : undefined;
  function changeRole(patch: Partial<LetteringRole>) {
    if (selected && role) changeElement(selected.id, { style_override: { ...role, ...patch } });
  }

  // Immediate translation/resize feedback uses the server SVG, not a second text renderer.
  useLayoutEffect(() => {
    if (!svg.current) return;
    for (const element of state.elements) {
      const node = [...svg.current.querySelectorAll<SVGGElement>("g[data-lettering-id]")].find((g) => g.dataset.letteringId === element.id);
      const original = preview.state.elements.find((e) => e.id === element.id);
      if (!node || !original) continue;
      let target = element.placement;
      if (gesture?.id === element.id) {
        if (gesture.mode === "move") target = moveBox(target, gesture.dx, gesture.dy);
        if (gesture.mode === "resize") target = resizeBox(target, gesture.dx, gesture.dy);
      }
      const dx = (target.x - original.placement.x) * 1000;
      const dy = (target.y - original.placement.y) * preview.aspect * 1000;
      const sx = target.width / original.placement.width;
      const cx = original.placement.x * 1000, cy = original.placement.y * preview.aspect * 1000;
      node.setAttribute("transform", `translate(${dx} ${dy}) translate(${cx} ${cy}) scale(${sx} 1) translate(${-cx} ${-cy}) rotate(${element.rotation} ${(original.placement.x + original.placement.width / 2) * 1000} ${(original.placement.y + original.resolved.body_height / 2) * preview.aspect * 1000})`);
      node.style.display = element.hidden ? "none" : "";
    }
  }, [state.elements, gesture, preview]);

  function startGesture(event: ReactPointerEvent<HTMLButtonElement>, element: LetteringElement, mode: "move" | "resize" | "tail") {
    if (event.button !== 0 || saving) return;
    event.preventDefault(); event.stopPropagation();
    setSelectedId(element.id);
    const rect = canvas.current?.getBoundingClientRect();
    if (!rect?.width || !rect.height) return;
    activeGesture.current = { id: element.id, x: event.clientX, y: event.clientY, width: rect.width, height: rect.height, mode };
    event.currentTarget.setPointerCapture(event.pointerId);
    setGesture({ id: element.id, dx: 0, dy: 0, mode });
  }
  function moveGesture(event: ReactPointerEvent<HTMLButtonElement>) {
    const start = activeGesture.current;
    if (!start) return;
    setGesture({ id: start.id, mode: start.mode, dx: (event.clientX - start.x) / start.width, dy: (event.clientY - start.y) / start.height });
  }
  function finishGesture(event: ReactPointerEvent<HTMLButtonElement>) {
    const start = activeGesture.current;
    activeGesture.current = null; setGesture(null);
    if (!start) return;
    const e = state.elements.find((item) => item.id === start.id);
    if (!e) return;
    const dx = (event.clientX - start.x) / start.width, dy = (event.clientY - start.y) / start.height;
    if (Math.abs(dx) + Math.abs(dy) < .001) return;
    if (start.mode === "tail" && e.tail_target) changeElement(e.id, { tail_target: { x: Math.max(0, Math.min(1, e.tail_target.x + dx)), y: Math.max(0, Math.min(1, e.tail_target.y + dy)) } });
    else changeElement(e.id, { placement: start.mode === "resize" ? resizeBox(e.placement, dx, dy) : moveBox(e.placement, dx, dy) });
  }
  const pointerHandlers = { onPointerMove: moveGesture, onPointerUp: finishGesture,
    onPointerCancel: () => { activeGesture.current = null; setGesture(null); } };

  async function save() {
    if (saving) return;
    const snapshot = currentRef.current;
    setSaving(true); setError("");
    try {
      const result = await saveLettering(project, snapshot, expected.current);
      expected.current = result.saved_sha256;
      setSavedIdentity(draftIdentity(result.state));
      if (draftIdentity(currentRef.current) === draftIdentity(snapshot)) {
        ++previewSequence.current;
        setPreview(result); dispatch({ type: "resolve", value: result.state });
      }
      setNotice("Saved. Artwork and generation credits are unchanged.");
      void qc.invalidateQueries({ queryKey: ["project", project] });
    } catch (cause) { setError(message(cause)); }
    finally { setSaving(false); setPreviewing(false); }
  }

  async function reloadSaved() {
    if (dirty && !window.confirm("Reload the saved page and discard this in-memory draft? Download your draft first to keep a copy.")) return;
    setSaving(true);
    try {
      const result = await getLettering(project, state.page_number);
      if (result.mode !== "editable") throw new Error(result.message);
      ++previewSequence.current;
      expected.current = result.saved_sha256;
      setSavedIdentity(result.saved_sha256 ? draftIdentity(result.state) : "");
      setPreview(result); dispatch({ type: "reset", value: result.state });
      setError(""); setRecovery(null); setNotice("Loaded the current saved page.");
    } catch (cause) { setError(message(cause)); }
    finally { setSaving(false); setPreviewing(false); }
  }

  async function applyBookStyle() {
    if (dirty) { setError("Save this page before applying a book-wide style."); return; }
    if (!window.confirm("Apply this page’s role styles to every drawn page? Individual element overrides will be kept.")) return;
    setSaving(true); setError("");
    try {
      const pages = await listCompletePages(project);
      const versions = Object.fromEntries(pages.pages.filter((p) => p.active_render).map((p) => [p.page.page_number, p.lettering?.sha256 ?? null]));
      await applyBookLetteringStyle(project, state.style, versions);
      const updated = await getLettering(project, state.page_number);
      if (updated.mode === "editable") {
        expected.current = updated.saved_sha256;
        dispatch({ type: "reset", value: updated.state }); setPreview(updated); setSavedIdentity(draftIdentity(updated.state));
      }
      void qc.invalidateQueries({ queryKey: ["project", project] });
      setNotice("Book-wide style saved. Check page fit before export.");
    } catch (cause) { setError(message(cause)); }
    finally { setSaving(false); setPreviewing(false); }
  }

  function addElement(kind: LetteringKind) {
    const id = `custom-${crypto.randomUUID()}`;
    const placement = { x: .1, y: .1, width: .35, height: .16 };
    const element: LetteringElement = { id, source_lettering_item_id: null, kind, copies: { [state.locale]: kind === "sfx" ? "BOOM!" : "Your text" }, suggested_placement: placement, placement, tail_target: null, style_override: null, hidden: false, rotation: 0, scale: 1, z_index: Math.min(100, state.elements.length + 1), resolved: { lines: [], widths: [], font_size: 22, body_height: .08, overflow: false, reason: "", signature: "" } };
    edit({ ...state, elements: [...state.elements, element] }); setSelectedId(id);
    copyInput.current?.focus();
  }
  const locales = [...new Set(["", state.locale, ...state.elements.flatMap((e) => Object.keys(e.copies))])];
  const overflow = state.elements.filter((e) => !e.hidden && e.resolved.overflow);

  return <section aria-label="Lettering workspace" className="space-y-4" onKeyDown={(event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void save(); return; }
    if (event.target instanceof HTMLElement && event.target.closest("input,textarea,select,[contenteditable=true]")) return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") { event.preventDefault(); dispatch({ type: event.shiftKey ? "redo" : "undo" }); }
  }}>
    <div className="sticky top-0 z-30 flex flex-wrap items-center justify-between gap-3 bg-bristol py-3">
      <div><h3 className="font-display text-xl font-black">Letter the page</h3><p className="mt-1 text-sm text-ink-muted">Select text on the page or in the list. Move it, make it fit, then save. No image generation.</p></div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" aria-label="Undo lettering edit" disabled={!history.past.length || saving} onClick={() => dispatch({ type: "undo" })}><Undo2 size={16} /></Button>
        <Button variant="outline" aria-label="Redo lettering edit" disabled={!history.future.length || saving} onClick={() => dispatch({ type: "redo" })}><Redo2 size={16} /></Button>
        <Button disabled={!dirty || saving} onClick={() => void save()}><Save size={16} />{saving ? "Saving…" : "Save lettering"}</Button>
      </div>
    </div>
    <div role="status" aria-live="polite" className="text-sm text-ink-muted">{previewing ? "Fitting type…" : dirty ? "Unsaved lettering edits" : notice || "All lettering edits saved"}</div>
    {recovery && <div className="border-l-4 border-narrator-gold p-3 text-sm" role="status"><p>A local unsaved draft was recovered. {recovery.base_sha256 !== initial.saved_sha256 && "The saved page has also changed; download the draft to compare without overwriting another session."}</p><div className="mt-2 flex gap-3"><Button variant="outline" size="xs" disabled={recovery.base_sha256 !== initial.saved_sha256} onClick={() => { dispatch({ type: "edit", value: recovery.state }); setRecovery(null); }}>Restore local draft</Button><Button variant="outline" size="xs" onClick={() => downloadLetteringDraft(recovery.state)}>Download recovered draft</Button><Button variant="outline" size="xs" onClick={() => setRecovery(null)}>Discard local draft</Button></div></div>}
    {error && <div role="alert" className="border-l-4 border-hero-red bg-bristol p-3 text-sm">{error} <button type="button" className="min-h-11 underline" onClick={() => void save()}>Retry save</button><button type="button" className="ml-3 min-h-11 underline" onClick={() => void reloadSaved()}>Reload saved page</button></div>}
    {overflow.length > 0 && <div role="status" className="border-l-4 border-narrator-gold bg-bristol p-3 text-sm">{overflow.length} text {overflow.length === 1 ? "element needs" : "elements need"} more room. Saving is allowed, but export waits until everything fits. <button className="min-h-11 underline" onClick={() => setSelectedId(overflow[0].id)}>Show first</button></div>}
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">Zoom<select aria-label="Page zoom" className={fieldClass} value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>{[.75, 1, 1.25, 1.5, 2].map((value) => <option key={value} value={value}>{Math.round(value * 100)}%</option>)}</select></label>
          <Button variant="outline" size="sm" aria-pressed={showArtOnly} onClick={() => setShowArtOnly(!showArtOnly)}>{showArtOnly ? <EyeOff size={16} /> : <Eye size={16} />}{showArtOnly ? "Show lettering" : "Art only"}</Button>
          <Button variant="outline" size="xs" onClick={() => downloadLetteringDraft(state)}>Download draft</Button><span className="text-xs text-ink-muted">Arrow keys nudge · Shift for larger steps · ⌘/Ctrl+S saves</span>
        </div>
        <div className="max-h-[75vh] overflow-auto border border-ink-black/15 bg-ink-black/10 p-4">
          <div ref={canvas} className="relative mx-auto bg-bristol shadow-paper" style={{ width: `${zoom * 100}%`, minWidth: 260, aspectRatio: `${1 / preview.aspect}` }}>
            <img src={pageRenderUrl(project, state.page_number, preview.render_revision)} draggable={false} className="absolute inset-0 h-full w-full select-none" alt={`Page ${state.page_number} base artwork`} />
            {!showArtOnly && <><div ref={svg} className="pointer-events-none absolute inset-0" dangerouslySetInnerHTML={{ __html: preview.svg }} />
              {state.elements.filter((e) => !e.hidden).map((element) => {
                const box = gesture?.id === element.id ? gesture.mode === "move" ? moveBox(element.placement, gesture.dx, gesture.dy) : gesture.mode === "resize" ? resizeBox(element.placement, gesture.dx, gesture.dy) : element.placement : element.placement;
                const isSelected = selectedId === element.id;
                return <div key={element.id} className="pointer-events-none absolute" style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%`, zIndex: element.z_index + 101 }}>
                  <button type="button" aria-label={`Select ${element.kind}: ${elementCopy(element, state, initial.canonical_copy).slice(0, 60) || "empty text"}`} aria-pressed={isSelected} className={`pointer-events-auto absolute inset-0 touch-none border-2 ${isSelected ? "border-hero-red" : "border-transparent hover:border-ink-black/50"} focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red`} onClick={() => setSelectedId(element.id)} onDoubleClick={() => copyInput.current?.focus()} onPointerDown={(event) => startGesture(event, element, "move")} {...pointerHandlers} onKeyDown={(event) => {
                    const delta = event.shiftKey ? .01 : .001;
                    const directions: Record<string, [number, number]> = { ArrowLeft: [-delta, 0], ArrowRight: [delta, 0], ArrowUp: [0, -delta], ArrowDown: [0, delta] };
                    if (directions[event.key]) { event.preventDefault(); const [dx, dy] = directions[event.key]; changeElement(element.id, { placement: moveBox(element.placement, dx, dy) }); }
                  }} />
                  {isSelected && <button type="button" aria-label="Resize selected lettering" title="Drag to resize available text area" className="pointer-events-auto absolute -bottom-5 -right-5 flex size-11 touch-none items-center justify-center text-hero-red" onPointerDown={(event) => startGesture(event, element, "resize")} {...pointerHandlers}><span className="size-3 border-2 border-bristol bg-hero-red shadow-paper" /></button>}
                </div>;
              })}
              {selected?.tail_target && !selected.hidden && <button type="button" aria-label="Move balloon tail" title="Drag toward the speaker" className="absolute z-[300] flex size-11 -translate-x-1/2 -translate-y-1/2 touch-none items-center justify-center text-hero-red" style={{ left: `${(selected.tail_target.x + (gesture?.mode === "tail" ? gesture.dx : 0)) * 100}%`, top: `${(selected.tail_target.y + (gesture?.mode === "tail" ? gesture.dy : 0)) * 100}%` }} onPointerDown={(event) => startGesture(event, selected, "tail")} {...pointerHandlers}><span className="size-3 rounded-full border-2 border-bristol bg-hero-red" /></button>}
            </>}
          </div>
        </div>
        <label className="mt-3 flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={state.reviewed_against_render_revision === preview.render_revision} onChange={(event) => dispatch({ type: "edit", value: { ...state, reviewed_against_render_revision: event.target.checked ? preview.render_revision : null } })} />I checked lettering placement against this artwork</label>
      </div>
      <aside aria-label="Lettering properties" className="min-w-0 space-y-4">
        {selected && role && <Surface padding="md" className="space-y-3">
          <label className="block text-sm font-bold">Display text<textarea ref={copyInput} rows={5} className={fieldClass} value={elementCopy(selected, state, initial.canonical_copy)} maxLength={4000} onFocus={() => { typing.current = false; }} onBlur={() => { typing.current = false; }} onChange={(event) => { changeElement(selected.id, { copies: { ...selected.copies, [state.locale]: event.target.value } }, typing.current); typing.current = true; }} /></label>
          <div className="flex flex-wrap gap-2">
            {selected.source_lettering_item_id && <Button variant="outline" size="xs" onClick={() => changeElement(selected.id, { copies: { ...selected.copies, [state.locale]: initial.canonical_copy[selected.source_lettering_item_id!] } })}>Reset copy</Button>}
            <Button variant="outline" size="xs" onClick={() => changeElement(selected.id, { placement: selected.suggested_placement })}>Reset placement</Button>
            <Button variant="outline" size="xs" onClick={() => changeElement(selected.id, { hidden: !selected.hidden })}>{selected.hidden ? "Show" : "Hide"}</Button>
            {!selected.source_lettering_item_id && <Button variant="outline" size="xs" onClick={() => { edit({ ...state, elements: state.elements.filter((e) => e.id !== selected.id) }); setSelectedId(""); }}>Delete</Button>}
          </div>
          <label className="block text-sm">Treatment<select className={fieldClass} value={selected.kind} onChange={(event) => changeElement(selected.id, { kind: event.target.value as LetteringKind, style_override: null, tail_target: null })}>{kinds.map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select></label>
          {selected.resolved.overflow && <p role="status" className="text-sm text-hero-red">{selected.resolved.reason}</p>}
          <p className="text-xs text-ink-muted">{selected.resolved.lines.length} balanced lines · {selected.resolved.font_size} design units · Source stays unchanged</p>
          {(selected.kind === "dialogue" || selected.kind === "thought") && <Button variant="outline" size="xs" onClick={() => changeElement(selected.id, { tail_target: selected.tail_target ? null : { x: Math.min(.98, selected.placement.x + selected.placement.width * .6), y: Math.min(.98, selected.placement.y + selected.placement.height + .08) } })}>{selected.tail_target ? "Remove tail" : "Add tail toward speaker"}</Button>}
          <details><summary className="min-h-11 cursor-pointer py-3 text-sm font-bold">Type, color & geometry</summary><div className="space-y-3">
            <label className="block text-sm">Font<select className={fieldClass} value={role.font} onChange={(e) => changeRole({ font: e.target.value as LetteringRole["font"] })}>{["ComicNeue-Bold", "EBGaramond-SemiBold", "Bangers-Regular", "MPLUS1p-Bold", "SpecialElite-Regular", "Exo2-SemiBold", "Creepster-Regular"].map((font) => <option key={font} value={font}>{font.replaceAll("-", " ")}</option>)}</select></label>
            <div className="grid grid-cols-2 gap-2">{([
              ["Maximum type", "max_size", role.min_size, 150, .5], ["Minimum type", "min_size", 8, role.max_size, .5],
              ["Line height", "line_height", .9, 2, .05], ["Padding", "padding", 0, 40, 1],
              ["Border", "border", 0, 10, .5], ["Corners", "radius", 0, 40, 1],
              ["Text stroke", "stroke", 0, 8, .5], ["Tracking", "letter_spacing", -1, 8, .1],
            ] as const).map(([label, key, min, max, step]) => <NumberField key={key} label={label} value={role[key]} min={min} max={max} step={step} onChange={(value) => changeRole({ [key]: value })} />)}</div>
            <label className="block text-sm">Alignment<select className={fieldClass} value={role.align} onChange={(e) => changeRole({ align: e.target.value as LetteringRole["align"] })}>{["left", "center", "right"].map((align) => <option key={align}>{align}</option>)}</select></label>
            <div className="grid grid-cols-3 gap-2">{(["color", "fill", "outline"] as const).map((key) => <label key={key} className="text-xs">{key === "color" ? "Text" : key}<input type="color" className="min-h-11 w-full cursor-pointer" value={role[key]} onChange={(e) => changeRole({ [key]: e.target.value })} /></label>)}</div>
            <div className="grid grid-cols-2 gap-2">{(["x", "y", "width", "height"] as const).map((key) => <NumberField key={key} label={`${key} %`} value={selected.placement[key] * 100} min={key === "width" || key === "height" ? 3 : 0} max={100} step={.1} onChange={(value) => { const box = { ...selected.placement, [key]: value / 100 }; box.width = Math.min(box.width, 1 - box.x); box.height = Math.min(box.height, 1 - box.y); if (box.width > 0 && box.height > 0) changeElement(selected.id, { placement: box }); }} />)}
            <NumberField label="Rotation °" value={selected.rotation} min={-45} max={45} step={1} onChange={(rotation) => changeElement(selected.id, { rotation })} />
            <NumberField label="Scale" value={selected.scale} min={.5} max={2} step={.05} onChange={(scale) => changeElement(selected.id, { scale })} />
            <NumberField label="Layer order" value={selected.z_index} min={-100} max={100} step={1} onChange={(z_index) => changeElement(selected.id, { z_index })} /></div>
            <Button variant="outline" size="xs" onClick={() => changeElement(selected.id, { style_override: null })}>Use page role style</Button>
            <Button variant="outline" size="xs" onClick={() => edit({ ...state, style: { ...state.style, [selected.kind]: role }, elements: state.elements.map((e) => e.id === selected.id ? { ...e, style_override: null } : e) })}>Make default for this role</Button>
          </div></details>
        </Surface>}
        <Surface padding="md" className="space-y-2">
          <h4 className="font-display font-bold">Page text</h4>
          <div className="max-h-48 space-y-1 overflow-auto" role="list" aria-label="Lettering elements">{state.elements.map((element, index) => <button key={element.id} type="button" role="listitem" onClick={() => setSelectedId(element.id)} className={`flex min-h-11 w-full items-center gap-2 border-l-2 px-2 text-left text-sm ${selectedId === element.id ? "border-hero-red bg-ink-black/5" : "border-transparent"}`}><span className="font-meta text-xs">{index + 1}</span><span className="min-w-0 flex-1 truncate">{elementCopy(element, state, initial.canonical_copy) || "Translation needed"}</span>{element.hidden ? <EyeOff size={14} /> : element.resolved.overflow ? <span aria-label="Needs more room">!</span> : null}</button>)}</div>
          <div className="grid grid-cols-2 gap-2">{kinds.map(([kind, label]) => <Button key={kind} variant="outline" size="xs" disabled={state.elements.length >= 100} onClick={() => addElement(kind)}><Plus size={14} />{label}</Button>)}</div>
        </Surface>
        <Surface padding="md"><details><summary className="min-h-11 cursor-pointer text-sm font-bold">Language & page style · {state.locale || "Source"}</summary><div className="space-y-3">
          <label className="block text-sm font-bold">Language<select className={fieldClass} value={state.locale} onChange={(event) => edit({ ...state, locale: event.target.value })}>{locales.map((locale) => <option key={locale} value={locale}>{locale || "Source language"}</option>)}</select></label>
          <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); const locale = localeInput.trim(); if (locale) edit({ ...state, locale }); setLocaleInput(""); }}><input aria-label="New language code" placeholder="Add language, e.g. es" maxLength={35} value={localeInput} onChange={(event) => setLocaleInput(event.target.value)} className={fieldClass} /><Button variant="outline" size="xs" type="submit">Add</Button></form>
          {state.locale && <p className="text-xs text-ink-muted">Enter translations below. Missing translations are flagged; original copy is never changed.</p>}
          {state.style.direction && <details><summary className="cursor-pointer text-sm">Selected lettering direction</summary><p className="mt-2 text-xs text-ink-muted">{state.style.direction}</p></details>}
          <label className="block text-sm font-bold">Page style<select className={fieldClass} value={state.style.preset} onChange={(event) => { const style = presets.data?.[event.target.value]; if (style) edit({ ...state, style: { ...style, direction: state.style.direction } }); }}>{["literary", "noir", "manga", "vintage"].map((name) => <option key={name} value={name}>{name[0].toUpperCase() + name.slice(1)}</option>)}</select></label>
          <Button variant="outline" size="xs" fullWidth disabled={dirty || saving} onClick={() => void applyBookStyle()}>Apply role styles to book</Button>
        </div></details></Surface>
      </aside>
    </div>
  </section>;
}

function NumberField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  // Do not clamp every keystroke: authors must be able to clear a field,
  // type a negative rotation or enter a decimal before committing it.
  const [raw, setRaw] = useState<string | null>(null);
  function commit() {
    if (raw?.trim()) {
      const number = Number(raw);
      if (Number.isFinite(number)) onChange(Math.min(max, Math.max(min, number)));
    }
    setRaw(null);
  }
  return <label className="block text-xs">{label}<input type="number" value={raw ?? Math.round(value * 1000) / 1000} min={min} max={max} step={step} className={fieldClass} onChange={(event) => setRaw(event.target.value)} onBlur={commit} onKeyDown={(event) => {
    if (event.key === "Enter") { event.preventDefault(); commit(); }
    if (event.key === "Escape") { event.stopPropagation(); event.preventDefault(); setRaw(null); }
  }} /></label>;
}
