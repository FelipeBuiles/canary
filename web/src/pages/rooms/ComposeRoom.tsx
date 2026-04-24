import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  usePages,
  usePage,
  useUpdatePage,
  useReplacePage,
  useReflowPages,
  useApplyStructuralOperation,
  useGeneratePageStyleVars,
  useTranslatePageBubbles,
  useExport,
  useProjectConfig,
  useUpdateProjectConfig,
  useProjectStatus,
} from "../../api/queries";
import { downloadExportUrl } from "../../api/pages";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { ComposeHeader } from "../../components/compose/ComposeHeader";
import { ModeSwitcher } from "../../components/compose/ModeSwitcher";
import { ScriptMode } from "../../components/compose/ScriptMode";
import { LayoutMode } from "../../components/compose/LayoutMode";
import { StyleMode } from "../../components/compose/StyleMode";
import { PreviewMode } from "../../components/compose/PreviewMode";
import { CommandPalette } from "../../components/compose/CommandPalette";
import { TryLayoutsModal } from "../../components/compose/TryLayoutsModal";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { useAllPages } from "../../hooks/useAllPages";
import { useComposeStore } from "../../store/compose";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import type { ComposeMode } from "../../components/compose/compose-types";
import "../../components/compose/comic-page.css";

function isInputFocused() {
  const el = document.activeElement as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function ComposeRoom() {
  const { name } = useParams<{ name: string }>();

  // ── Mode state ───────────────────────────────────────────────────────────
  const [mode, setMode] = useState<ComposeMode>("script");
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [tryLayoutsOpen, setTryLayoutsOpen] = useState(false);
  const [inspectorMode, setInspectorMode] = useState<"floating" | "fixed">(() => {
    const saved = window.localStorage.getItem("canary.compose.inspector-mode");
    return saved === "floating" ? "floating" : "fixed";
  });

  // ── Page state (URL param for Layout mode deep-link, localStorage persist) ──
  const [searchParams, setSearchParams] = useSearchParams();
  const currentPage = Number(searchParams.get("page") ?? 1);

  const { data: pageList, isLoading: loadingList } = usePages(name);
  const { data: projectStatus } = useProjectStatus(name);
  const safePage = pageList?.length ? Math.min(currentPage, pageList.length) : undefined;
  const { data: page, isLoading: loadingPage } = usePage(name, safePage);

  // Fetch all pages for Script/Preview modes
  const { pages: allPages, isLoading: loadingAllPages } = useAllPages(name, pageList);

  // Current page index (0-based) derived from URL param
  const pageIdx = (safePage ?? 1) - 1;

  const { data: projectConfig } = useProjectConfig(name);
  const [outputLanguageOverride, setOutputLanguageOverride] = useState<"en" | "es" | "fr" | null>(null);
  const outputLanguage = outputLanguageOverride ?? projectConfig?.target_language ?? "en";

  // ── Mutations ────────────────────────────────────────────────────────────
  const updatePageMut = useUpdatePage();
  const replacePageMut = useReplacePage();
  const reflowPagesMut = useReflowPages();
  const structuralOpMut = useApplyStructuralOperation();
  const generatePageStyleMut = useGeneratePageStyleVars();
  const translateBubblesMut = useTranslatePageBubbles();
  const updateProjectConfigMut = useUpdateProjectConfig();
  const exportMut = useExport();

  // ── Compose store ────────────────────────────────────────────────────────
  const selection = useComposeStore((s) => s.selection);
  const select = useComposeStore((s) => s.select);
  const deselect = useComposeStore((s) => s.deselect);
  const pushUndo = useComposeStore((s) => s.pushUndo);
  const popUndo = useComposeStore((s) => s.popUndo);
  const popRedo = useComposeStore((s) => s.popRedo);
  const undoStack = useComposeStore((s) => s.undoStack);
  const redoStack = useComposeStore((s) => s.redoStack);
  const clearHistory = useComposeStore((s) => s.clearHistory);

  // ── Zoom ─────────────────────────────────────────────────────────────────
  const [zoom, setZoom] = useState(1);
  const clampZoom = (v: number) => Math.max(0.5, Math.min(2.5, Number(v.toFixed(2))));

  // ── Page navigation ──────────────────────────────────────────────────────
  function setPageNum(p: number, opts?: { preserveSelection?: boolean }) {
    setSearchParams({ page: String(p) }, { replace: true });
    if (!opts?.preserveSelection) deselect();
    clearHistory();
    setZoom(1);
  }

  // ── Mutations ────────────────────────────────────────────────────────────

  function patchPage(patch: Partial<ComicPage>, targetPageNum?: number) {
    const pNum = targetPageNum ?? safePage;
    if (!name || !pNum) return;
    const targetPage = targetPageNum ? allPages[targetPageNum - 1] : page;
    if (targetPage) pushUndo(targetPage);
    updatePageMut.mutate({ project: name, pageNum: pNum, data: patch });
  }

  function handleUpdateBubble(panelId: string, bubbleId: string, bPatch: Partial<Bubble>, targetPageNum?: number) {
    patchPage(
      { panels: [{ id: panelId, bubbles: [{ id: bubbleId, ...bPatch }] }] as ComicPage["panels"] },
      targetPageNum,
    );
  }

  function handleUpdateSfx(panelId: string, sPatch: Partial<Sfx>) {
    patchPage({ panels: [{ id: panelId, sfx: sPatch }] as ComicPage["panels"] });
  }

  function handleUpdatePanel(panelId: string, pPatch: Partial<PagePanel>) {
    patchPage({ panels: [{ id: panelId, ...pPatch }] as ComicPage["panels"] });
  }

  function handleUpdatePageProps(patch: Partial<ComicPage>) {
    patchPage(patch);
  }

  function handleUpdatePanelStructure(
    plannedPanelId: string,
    patch: { importance?: string | null; shape_intent?: string | null; generation_mode?: string | null },
  ) {
    if (!name || !safePage) return;
    clearHistory();
    structuralOpMut.mutate({
      project: name,
      data: {
        operation: "panel_override",
        page_number: safePage,
        planned_panel_id: plannedPanelId,
        importance: patch.importance ?? undefined,
        shape_intent: patch.shape_intent ?? undefined,
        generation_mode: patch.generation_mode ?? undefined,
      },
    });
  }

  function handleReflowPages(panelsPerPage: number) {
    if (!name || !page) return;
    reflowPagesMut.mutate(
      { project: name, panelsPerPage },
      {
        onSuccess: (pages) => {
          clearHistory();
          const lastPage = pages.at(-1)?.page_number ?? 1;
          if (currentPage > lastPage) setPageNum(lastPage);
        },
      },
    );
  }

  function handleGeneratePageStyle() {
    if (!name) return;
    generatePageStyleMut.mutate({ project: name });
  }

  function handleTranslateBubbles(targetLanguage: "en" | "es" | "fr") {
    if (!name || !page) return;
    pushUndo(page);
    translateBubblesMut.mutate({ project: name, targetLanguage });
  }

  function handleOutputLanguageChange(targetLanguage: "en" | "es" | "fr") {
    setOutputLanguageOverride(targetLanguage);
    if (!name) return;
    updateProjectConfigMut.mutate({ project: name, data: { target_language: targetLanguage } });
  }

  function handleDeleteElement(panelId: string, type: "bubble" | "sfx", elementId: string) {
    if (!name || !safePage || !page) return;
    pushUndo(page);
    if (type === "bubble") {
      patchPage({ panels: [{ id: panelId, remove_bubble_ids: [elementId] }] as unknown as ComicPage["panels"] });
    } else {
      patchPage({ panels: [{ id: panelId, remove_sfx: true }] as unknown as ComicPage["panels"] });
    }
    deselect();
  }

  function handleUnpin(panelId: string, type: "bubble" | "sfx", elementId: string) {
    if (type === "bubble") {
      handleUpdateBubble(panelId, elementId, { x: null, y: null, tail_x: null, tail_y: null });
    } else {
      handleUpdateSfx(panelId, { x: null, y: null });
    }
  }

  function handleDragEnd(panelId: string, type: "bubble" | "sfx", elementId: string, x: number, y: number) {
    if (type === "bubble") handleUpdateBubble(panelId, elementId, { x, y });
    else handleUpdateSfx(panelId, { x, y });
  }

  function handleAddBubble(bubbleType: "speech" | "thought" | "narration") {
    if (!page || !name || !safePage) return;
    const targetPanel = selection?.panelId ? page.panels.find((p) => p.id === selection.panelId) : page.panels[0];
    if (!targetPanel) return;
    pushUndo(page);
    const newBubble = {
      id: `new-${Date.now()}`,
      type: bubbleType,
      text: bubbleType === "narration" ? "Narration text..." : "Dialogue...",
      side: "left" as const,
    };
    patchPage({ panels: [{ id: targetPanel.id, bubbles: [newBubble] }] as unknown as ComicPage["panels"] });
  }

  function handleAddSfx() {
    if (!page || !name || !safePage) return;
    const targetPanel = selection?.panelId ? page.panels.find((p) => p.id === selection.panelId) : page.panels[0];
    if (!targetPanel) return;
    pushUndo(page);
    patchPage({ panels: [{ id: targetPanel.id, sfx: { text: "KRAK!" } }] as unknown as ComicPage["panels"] });
  }

  function handleUndo() {
    const prev = popUndo();
    if (!prev || !name || !safePage || !page) return;
    useComposeStore.setState((s) => ({ redoStack: [...s.redoStack, structuredClone(page)] }));
    replacePageMut.mutate({ project: name, pageNum: safePage, data: prev });
  }

  function handleRedo() {
    const next = popRedo();
    if (!next || !name || !safePage || !page) return;
    useComposeStore.setState((s) => ({ undoStack: [...s.undoStack, structuredClone(page)] }));
    replacePageMut.mutate({ project: name, pageNum: safePage, data: next });
  }

  function handleExport(format: "pdf" | "cbz") {
    if (!name) return;
    exportMut.mutate(
      { project: name, format },
      { onSuccess: () => { window.open(downloadExportUrl(name, format), "_blank"); } },
    );
  }

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // Mode switching — only when not typing
      if (!isInputFocused() && !cmdkOpen) {
        if (e.key === "1") { setMode("script"); return; }
        if (e.key === "2") { setMode("layout"); return; }
        if (e.key === "3") { setMode("style"); return; }
        if (e.key === "4") { setMode("preview"); return; }
      }
      // Global shortcuts
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setCmdkOpen((o) => !o); return; }
      if ((e.metaKey || e.ctrlKey) && e.key === "e") { e.preventDefault(); setMode("preview"); return; }
      if ((e.metaKey || e.ctrlKey) && e.key === "m") { e.preventDefault(); handleGeneratePageStyle(); return; }
      if ((e.metaKey || e.ctrlKey) && e.key === "l") { e.preventDefault(); setTryLayoutsOpen(true); return; }
      if (e.key === "Escape") { if (cmdkOpen) { setCmdkOpen(false); return; } deselect(); return; }
      // Layout mode shortcuts
      if (mode === "layout" && !isInputFocused()) {
        if (e.key === "b" || e.key === "B") { handleAddBubble("speech"); return; }
        if (e.key === "t" && !e.shiftKey) { handleAddBubble("thought"); return; }
        if (e.key === "n" && !e.shiftKey) { handleAddBubble("narration"); return; }
        if (e.key === "x" || e.key === "X") { handleAddSfx(); return; }
        if (e.key === "N" && e.shiftKey) {
          const narration = page?.panels.flatMap((panel) =>
            panel.bubbles
              .filter((bubble) => bubble.type === "narration")
              .map((bubble) => ({ panelId: panel.id, bubbleId: bubble.id }))
          )[0];
          if (narration) select(narration.panelId, "bubble", narration.bubbleId);
          return;
        }
        if (e.key === "T" && e.shiftKey) {
          const thought = page?.panels.flatMap((panel) =>
            panel.bubbles
              .filter((bubble) => bubble.type === "thought")
              .map((bubble) => ({ panelId: panel.id, bubbleId: bubble.id }))
          )[0];
          if (thought) select(thought.panelId, "bubble", thought.bubbleId);
          return;
        }
        if (e.key === "Delete" || e.key === "Backspace") {
          if (selection && page) handleDeleteElement(selection.panelId, selection.type, selection.elementId);
        }
        if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) { e.preventDefault(); handleUndo(); }
        if ((e.metaKey || e.ctrlKey) && e.key === "z" && e.shiftKey) { e.preventDefault(); handleRedo(); }
        if ((e.metaKey || e.ctrlKey) && (e.key === "=" || e.key === "+")) { e.preventDefault(); setZoom((z) => clampZoom(z + 0.1)); }
        if ((e.metaKey || e.ctrlKey) && e.key === "-") { e.preventDefault(); setZoom((z) => clampZoom(z - 0.1)); }
        if ((e.metaKey || e.ctrlKey) && e.key === "0") { e.preventDefault(); setZoom(1); }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  useEffect(() => {
    window.localStorage.setItem("canary.compose.inspector-mode", inspectorMode);
  }, [inspectorMode]);

  // ── Script → Layout deep-link ────────────────────────────────────────────
  function handleSwitchToLayout(targetPageNum: number, panelId: string, bubbleId: string) {
    setPageNum(targetPageNum, { preserveSelection: true });
    setMode("layout");
    select(panelId, "bubble", bubbleId);
  }

  // ── Render ───────────────────────────────────────────────────────────────

  const composeStageStatus = projectStatus?.stages?.compose?.status ?? "pending";

  if (loadingList || (!pageList?.length && composeStageStatus !== "pending")) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
          LOADING PAGE EDITOR...
        </p>
      </div>
    );
  }

  if (!pageList?.length || !name) {
    const stageInfo = projectStatus?.stages?.compose;
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <StagePlaceholder
          stage="compose"
          status={stageInfo?.status ?? "pending"}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
        />
      </div>
    );
  }

  const pageNumber = safePage ?? 1;

  return (
    <div className="-mx-5 -my-6 flex min-h-[calc(100vh-58px)] flex-col bg-pulp-paper md:-my-6">
      {/* Persistent header with Export CTA */}
      <ComposeHeader
        mode={mode}
        isExporting={exportMut.isPending}
        onExport={handleExport}
        onOpenCmdk={() => setCmdkOpen(true)}
        onPreview={() => setMode("preview")}
        rerunAction={
          <RerunStageAction
            project={name}
            stage="compose"
            label="Compose"
            className="min-h-8 border px-3 py-1.5 text-[0.52rem] tracking-[0.16em]"
          />
        }
      />

      {/* Mode tab switcher */}
      <ModeSwitcher mode={mode} onModeChange={setMode} />

      {/* Mode content — fills remaining height */}
      {mode === "script" && (
        <ScriptMode
          project={name}
          pages={allPages}
          isLoading={loadingAllPages}
          pageIdx={pageIdx}
          outputLanguage={outputLanguage}
          onPageSelect={(idx) => setPageNum(idx + 1)}
          onUpdateBubble={(pageNum, panelId, bubbleId, patch) =>
            handleUpdateBubble(panelId, bubbleId, patch, pageNum)
          }
          onSwitchToLayout={handleSwitchToLayout}
        />
      )}

      {mode === "layout" && (
        <LayoutMode
          project={name}
          pageList={pageList}
          page={page}
          pageNumber={pageNumber}
          isLoadingPage={loadingPage}
          zoom={zoom}
          selection={selection}
          undoStack={undoStack}
          redoStack={redoStack}
          isGeneratingPageStyle={generatePageStyleMut.isPending}
          isTranslatingBubbles={translateBubblesMut.isPending}
          outputLanguage={outputLanguage}
          onPageSelect={setPageNum}
          onAddBubble={handleAddBubble}
          onAddSfx={handleAddSfx}
          onDelete={() => { if (selection) handleDeleteElement(selection.panelId, selection.type, selection.elementId); }}
          onUndo={handleUndo}
          onRedo={handleRedo}
          onTryLayouts={() => setTryLayoutsOpen(true)}
          onSelect={select}
          onDeselect={deselect}
          onDragEnd={handleDragEnd}
          onZoomChange={(z) => setZoom(clampZoom(z))}
          onZoomIn={() => setZoom((z) => clampZoom(z + 0.1))}
          onZoomOut={() => setZoom((z) => clampZoom(z - 0.1))}
          onZoomReset={() => setZoom(1)}
          onUpdatePanel={handleUpdatePanel}
          onUpdatePanelStructure={handleUpdatePanelStructure}
          onUpdateBubble={handleUpdateBubble}
          onUpdateSfx={handleUpdateSfx}
          onUpdatePage={handleUpdatePageProps}
          onReflowPages={handleReflowPages}
          onGeneratePageStyle={handleGeneratePageStyle}
          onOutputLanguageChange={handleOutputLanguageChange}
          onTranslateBubbles={handleTranslateBubbles}
          onDeleteElement={handleDeleteElement}
          onUnpin={handleUnpin}
          inspectorMode={inspectorMode}
          onInspectorModeChange={setInspectorMode}
        />
      )}

      {mode === "style" && (
        <StyleMode
          project={name}
          isMatchingStyle={generatePageStyleMut.isPending}
          isTranslatingBubbles={translateBubblesMut.isPending}
          outputLanguage={outputLanguage}
          pageCount={pageList.length}
          onMatchStyle={handleGeneratePageStyle}
          onTranslateBubbles={handleTranslateBubbles}
          onOutputLanguageChange={handleOutputLanguageChange}
        />
      )}

      {mode === "preview" && (
        <PreviewMode
          project={name}
          pages={allPages}
          pageList={pageList}
          isLoading={loadingAllPages}
          pageIdx={pageIdx}
          isExporting={exportMut.isPending}
          onPageSelect={(idx) => setPageNum(idx + 1)}
          onExport={handleExport}
        />
      )}

      {/* Command palette */}
      {cmdkOpen && (
        <CommandPalette
          onClose={() => setCmdkOpen(false)}
          onSwitchMode={setMode}
          onExport={handleExport}
          onMatchStyle={handleGeneratePageStyle}
          onTranslate={() => handleTranslateBubbles(outputLanguage)}
          onAddBubble={handleAddBubble}
          onAddSfx={handleAddSfx}
          onTryLayouts={() => setTryLayoutsOpen(true)}
        />
      )}

      {/* Try Layouts modal */}
      {tryLayoutsOpen && name && safePage && (
        <TryLayoutsModal
          project={name}
          pageNum={safePage}
          page={page}
          onClose={() => setTryLayoutsOpen(false)}
        />
      )}
    </div>
  );
}
