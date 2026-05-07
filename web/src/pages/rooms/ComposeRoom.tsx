import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  usePages,
  usePage,
  useUpdatePage,
  useReplacePage,
  useGeneratePageStyleVars,
  useTranslatePageBubbles,
  useExport,
  useProjectConfig,
  useUpdateProjectConfig,
  useProjectStatus,
  useSetTheme,
  useImages,
} from "../../api/queries";
import { downloadExportUrl } from "../../api/pages";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { ComposeHeader } from "../../components/compose/ComposeHeader";
import { EditSubTabs } from "../../components/compose/ModeSwitcher";
import { ScriptMode } from "../../components/compose/ScriptMode";
import { LayoutMode } from "../../components/compose/LayoutMode";
import { PreviewMode } from "../../components/compose/PreviewMode";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { IssueMode } from "../../components/compose/IssueMode";
import { useAllPages } from "../../hooks/useAllPages";
import { useComposeStore } from "../../store/compose";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import type { ComposeTab, EditSubMode } from "../../components/compose/compose-types";
import { detectIssues } from "../../lib/issueEngine";
import type { ComposeIssue } from "../../lib/issueEngine";
import "../../components/compose/comic-page.css";

function isInputFocused() {
  const el = document.activeElement as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function ComposeRoom() {
  const { id } = useParams<{ id: string }>();

  // ── Tab / sub-mode state ─────────────────────────────────────────────────
  const [tab, setTab] = useState<ComposeTab>("edit");
  const [editSubMode, setEditSubMode] = useState<EditSubMode>("canvas");
  const [panelReframeId, setPanelReframeId] = useState<string | null>(null);
  const [cmdkOpen, setCmdkOpen] = useState(false);

  // ── Page state ────────────────────────────────────────────────────────────
  const [searchParams, setSearchParams] = useSearchParams();
  const currentPage = Number(searchParams.get("page") ?? 1);

  const { data: projectStatus } = useProjectStatus(id);
  const composeStageStatus = projectStatus?.stages?.compose?.status ?? "pending";
  const { data: pageList, isLoading: loadingList, refetch: refetchPageList } = usePages(id);
  const safePage = pageList?.length ? Math.min(currentPage, pageList.length) : undefined;
  const { data: page, isLoading: loadingPage } = usePage(id, safePage);

  const { pages: allPages, isLoading: loadingAllPages } = useAllPages(id, pageList);

  const { data: images } = useImages(id);
  const issues = useMemo(
    () => detectIssues(allPages.filter((p): p is ComicPage => p !== undefined), images ?? []),
    [allPages, images],
  );

  const pageIdx = (safePage ?? 1) - 1;

  const { data: projectConfig } = useProjectConfig(id);
  const [outputLanguageOverride, setOutputLanguageOverride] = useState<"en" | "es" | "fr" | null>(null);
  const outputLanguage = outputLanguageOverride ?? projectConfig?.target_language ?? "en";

  // ── Mutations ────────────────────────────────────────────────────────────
  const updatePageMut = useUpdatePage();
  const replacePageMut = useReplacePage();
  const generatePageStyleMut = useGeneratePageStyleVars();
  const translateBubblesMut = useTranslatePageBubbles();
  const updateProjectConfigMut = useUpdateProjectConfig();
  const exportMut = useExport();
  const setThemeMut = useSetTheme();

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

  // ── Patch helpers ────────────────────────────────────────────────────────
  function patchPage(patch: Partial<ComicPage>, targetPageNum?: number) {
    const pNum = targetPageNum ?? safePage;
    if (!id || !pNum) return;
    const targetPage = targetPageNum ? allPages[targetPageNum - 1] : page;
    if (targetPage) pushUndo(targetPage);
    updatePageMut.mutate({ project: id, pageNum: pNum, data: patch });
  }

  function handleUpdateBubble(panelId: string, bubbleId: string, bPatch: Partial<Bubble>, targetPageNum?: number) {
    patchPage(
      { panels: [{ id: panelId, bubbles: [{ id: bubbleId, ...bPatch }] }] as ComicPage["panels"] },
      targetPageNum,
    );
  }

  function handleUpdateSfx(panelId: string, sfxIndex: number, sPatch: Partial<Sfx>) {
    patchPage({ panels: [{ id: panelId, sfx: sPatch, sfx_index: sfxIndex }] as unknown as ComicPage["panels"] });
  }

  function handleUpdatePanel(panelId: string, pPatch: Partial<PagePanel>) {
    patchPage({ panels: [{ id: panelId, ...pPatch }] as ComicPage["panels"] });
  }

  // ── Panel reframe ────────────────────────────────────────────────────────
  function handlePanelReframeStart(panelId: string) {
    deselect();
    setPanelReframeId(panelId);
  }

  function handlePanelReframeDragEnd(panelId: string, newOffsetX: number, newOffsetY: number) {
    handleUpdatePanel(panelId, {
      image_offset_x: Math.round(newOffsetX),
      image_offset_y: Math.round(newOffsetY),
    });
  }

  function handleResetPanelFrame(panelId: string) {
    handleUpdatePanel(panelId, { image_offset_x: null, image_offset_y: null });
  }

  // ── Selection — also clears panel reframe ────────────────────────────────
  function handleSelect(panelId: string, type: "bubble" | "sfx", elementId: string) {
    setPanelReframeId(null);
    select(panelId, type, elementId);
  }

  function handleDeselect() {
    setPanelReframeId(null);
    deselect();
  }

  // ── Element delete / unpin ───────────────────────────────────────────────
  function parseSfxIndex(elementId: string): number {
    const m = elementId.match(/__sfx__(\d+)$/);
    return m ? Number(m[1]) : 0;
  }

  function handleDeleteElement(panelId: string, type: "bubble" | "sfx", elementId: string) {
    if (!id || !safePage || !page) return;
    pushUndo(page);
    if (type === "bubble") {
      patchPage({ panels: [{ id: panelId, remove_bubble_ids: [elementId] }] as unknown as ComicPage["panels"] });
    } else {
      patchPage({ panels: [{ id: panelId, remove_sfx: parseSfxIndex(elementId) }] as unknown as ComicPage["panels"] });
    }
    deselect();
  }

  function handleUnpin(panelId: string, type: "bubble" | "sfx", elementId: string) {
    if (type === "bubble") {
      handleUpdateBubble(panelId, elementId, { x: null, y: null, tail_x: null, tail_y: null });
    } else {
      handleUpdateSfx(panelId, parseSfxIndex(elementId), { x: null, y: null });
    }
  }

  function handleDragEnd(panelId: string, type: "bubble" | "sfx", elementId: string, x: number, y: number) {
    if (type === "bubble") handleUpdateBubble(panelId, elementId, { x, y });
    else handleUpdateSfx(panelId, parseSfxIndex(elementId), { x, y });
  }

  // ── Add elements ─────────────────────────────────────────────────────────
  function handleAddBubble(bubbleType: "speech" | "thought" | "narration") {
    if (!page || !id || !safePage) return;
    const targetPanel = selection?.panelId ? page.panels.find((p) => p.id === selection.panelId) : page.panels[0];
    if (!targetPanel) return;
    pushUndo(page);
    patchPage({ panels: [{ id: targetPanel.id, bubbles: [{ id: `new-${Date.now()}`, type: bubbleType, text: bubbleType === "narration" ? "Narration text..." : "Dialogue...", side: "left" as const }] }] as unknown as ComicPage["panels"] });
  }

  function handleAddSfx() {
    if (!page || !id || !safePage) return;
    const targetPanel = selection?.panelId ? page.panels.find((p) => p.id === selection.panelId) : page.panels[0];
    if (!targetPanel) return;
    pushUndo(page);
    patchPage({ panels: [{ id: targetPanel.id, sfx: { text: "KRAK!" } }] as unknown as ComicPage["panels"] });
  }

  // ── Undo / redo ──────────────────────────────────────────────────────────
  function handleUndo() {
    const prev = popUndo();
    if (!prev || !id || !safePage || !page) return;
    useComposeStore.setState((s) => ({ redoStack: [...s.redoStack, structuredClone(page)] }));
    replacePageMut.mutate({ project: id, pageNum: safePage, data: prev });
  }

  function handleRedo() {
    const next = popRedo();
    if (!next || !id || !safePage || !page) return;
    useComposeStore.setState((s) => ({ undoStack: [...s.undoStack, structuredClone(page)] }));
    replacePageMut.mutate({ project: id, pageNum: safePage, data: next });
  }

  // ── Export / style / translate ───────────────────────────────────────────
  function handleExport(format: "pdf" | "cbz") {
    if (!id) return;
    exportMut.mutate(
      { project: id, format },
      { onSuccess: (result) => { window.open(result.url ?? downloadExportUrl(id, format), "_blank"); } },
    );
  }

  function handleGeneratePageStyle() {
    if (!id) return;
    generatePageStyleMut.mutate({ project: id });
  }

  function handleTranslateBubbles(targetLanguage: "en" | "es" | "fr") {
    if (!id) return;
    translateBubblesMut.mutate({ project: id, targetLanguage });
  }

  function handleOutputLanguageChange(targetLanguage: "en" | "es" | "fr") {
    setOutputLanguageOverride(targetLanguage);
    if (!id) return;
    updateProjectConfigMut.mutate({ project: id, data: { target_language: targetLanguage } });
  }

  function handleThemeChange(theme: string) {
    if (!id) return;
    setThemeMut.mutate({ project: id, theme });
  }

  // ── Script → Canvas deep-link ────────────────────────────────────────────
  function handleSwitchToCanvas(targetPageNum: number, panelId: string, bubbleId: string) {
    setPageNum(targetPageNum, { preserveSelection: true });
    setEditSubMode("canvas");
    setPanelReframeId(null);
    select(panelId, "bubble", bubbleId);
  }

  // ── Export → Issues navigation ───────────────────────────────────────────
  function handleGoToIssues() {
    setTab("edit");
    setEditSubMode("issues");
  }

  // ── Issue deep-link ──────────────────────────────────────────────────────
  function handleGoToIssue(issue: ComposeIssue) {
    setPageNum(issue.pageNumber);
    setEditSubMode("canvas");
    if (issue.panelId && issue.bubbleId) {
      select(issue.panelId, "bubble", issue.bubbleId);
    } else {
      deselect();
    }
  }

  // ── Poll while compose is running ────────────────────────────────────────
  useEffect(() => {
    if (!id) return;
    const waitingForPages =
      composeStageStatus === "running" ||
      (composeStageStatus === "complete" && !pageList?.length);
    if (!waitingForPages) return;
    void refetchPageList();
    const interval = window.setInterval(() => { void refetchPageList(); }, 2000);
    return () => window.clearInterval(interval);
  }, [id, composeStageStatus, pageList?.length, refetchPageList]);

  // ── Keyboard shortcuts ───────────────────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!isInputFocused() && !cmdkOpen) {
        if (e.key === "1") { setTab("edit"); setEditSubMode("canvas"); return; }
        if (e.key === "2") { setTab("edit"); setEditSubMode("script"); return; }
        if (e.key === "3") { setTab("export"); return; }
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setCmdkOpen((o) => !o); return; }
      if ((e.metaKey || e.ctrlKey) && e.key === "e") { e.preventDefault(); setTab("export"); return; }
      if ((e.metaKey || e.ctrlKey) && e.key === "m") { e.preventDefault(); handleGeneratePageStyle(); return; }
      if (e.key === "Escape") {
        if (cmdkOpen) { setCmdkOpen(false); return; }
        if (panelReframeId) { setPanelReframeId(null); return; }
        deselect();
        return;
      }
      if (tab === "edit" && editSubMode === "canvas" && !isInputFocused()) {
        if (e.key === "b" || e.key === "B") { handleAddBubble("speech"); return; }
        if (e.key === "t" && !e.shiftKey) { handleAddBubble("thought"); return; }
        if (e.key === "n" && !e.shiftKey) { handleAddBubble("narration"); return; }
        if (e.key === "x" || e.key === "X") { handleAddSfx(); return; }
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

  // ── Loading / empty states ───────────────────────────────────────────────
  if (loadingList || (!pageList?.length && composeStageStatus !== "pending")) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">LOADING PAGE EDITOR...</p>
      </div>
    );
  }

  if (!pageList?.length || !id) {
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
  const activeTheme = pageList?.[0]?.theme ?? "default";

  return (
    <div className="-mx-5 -my-6 flex min-h-[calc(100vh-58px)] flex-col gap-3 bg-pulp-paper md:-my-6">
      {/* Thin persistent header */}
      <ComposeHeader
        tab={tab}
        onTabChange={setTab}
        isExporting={exportMut.isPending}
        isMatchingStyle={generatePageStyleMut.isPending}
        onExport={handleExport}
        onMatchStyle={handleGeneratePageStyle}
        rerunAction={
          <RerunStageAction
            project={id}
            stage="compose"
            label="Compose"
            className="min-h-7 border border-ink-black/20 px-3 py-1 text-[0.5rem] tracking-[0.16em] text-ink-black/50 hover:text-ink-black"
          />
        }
        pageCount={pageList.length}
      />

      {/* Edit tab */}
      {tab === "edit" && (
        <>
          <EditSubTabs subMode={editSubMode} onSubModeChange={setEditSubMode} issueCount={issues.length} />

          {editSubMode === "canvas" && (
            <LayoutMode
              project={id}
              pageList={pageList}
              page={page}
              pageNumber={pageNumber}
              isLoadingPage={loadingPage}
              zoom={zoom}
              selection={selection}
              panelReframeId={panelReframeId}
              undoStack={undoStack}
              redoStack={redoStack}
              onPageSelect={setPageNum}
              onAddBubble={handleAddBubble}
              onAddSfx={handleAddSfx}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onSelect={handleSelect}
              onDeselect={handleDeselect}
              onDragEnd={handleDragEnd}
              onZoomChange={(z) => setZoom(clampZoom(z))}
              onUpdatePanel={handleUpdatePanel}
              onUpdateBubble={handleUpdateBubble}
              onUpdateSfx={handleUpdateSfx}
              onPanelReframeStart={handlePanelReframeStart}
              onPanelReframeDragEnd={handlePanelReframeDragEnd}
              onResetPanelFrame={handleResetPanelFrame}
              onDeleteElement={handleDeleteElement}
              onUnpin={handleUnpin}
            />
          )}

          {editSubMode === "issues" && (
            <IssueMode issues={issues} onGoToIssue={handleGoToIssue} />
          )}

          {editSubMode === "script" && (
            <ScriptMode
              project={id}
              pages={allPages}
              isLoading={loadingAllPages}
              pageIdx={pageIdx}
              outputLanguage={outputLanguage}
              onPageSelect={(idx) => setPageNum(idx + 1)}
              onUpdateBubble={(pageNum, panelId, bubbleId, patch) =>
                handleUpdateBubble(panelId, bubbleId, patch, pageNum)
              }
              onSwitchToLayout={handleSwitchToCanvas}
            />
          )}
        </>
      )}

      {/* Export tab */}
      {tab === "export" && (
        <PreviewMode
          project={id}
          pages={allPages}
          pageList={pageList}
          isLoading={loadingAllPages}
          pageIdx={pageIdx}
          isExporting={exportMut.isPending}
          activeTheme={activeTheme}
          outputLanguage={outputLanguage}
          isTranslatingBubbles={translateBubblesMut.isPending}
          issues={issues}
          onPageSelect={(idx) => setPageNum(idx + 1)}
          onExport={handleExport}
          onThemeChange={handleThemeChange}
          onOutputLanguageChange={handleOutputLanguageChange}
          onTranslateBubbles={handleTranslateBubbles}
          onReviewIssues={handleGoToIssues}
        />
      )}

      {/* Command palette: TO DO//reimplement when it makes sense */}
      {/* {cmdkOpen && (
        <CommandPalette
          onClose={() => setCmdkOpen(false)}
          onSwitchMode={(m) => {
            if (m === "script") { setTab("edit"); setEditSubMode("script"); }
            else if (m === "layout") { setTab("edit"); setEditSubMode("canvas"); }
            else if (m === "preview") { setTab("export"); }
            else if (m === "style") { setTab("export"); }
          }}
          onExport={handleExport}
          onMatchStyle={handleGeneratePageStyle}
          onTranslate={() => handleTranslateBubbles(outputLanguage)}
          onAddBubble={handleAddBubble}
          onAddSfx={handleAddSfx}
        />
      )} */}

    </div>
  );
}
