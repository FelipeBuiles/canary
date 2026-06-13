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
  useImages,
} from "../../api/queries";
import { downloadExportUrl } from "../../api/pages";
import { RerunStageAction, StagePlaceholder } from "../../components/composites";
import { ComposeHeader } from "../../components/compose/ComposeHeader";
import { ExportBurst } from "../../components/compose/ExportBurst";
import { ScriptMode } from "../../components/compose/ScriptMode";
import { LayoutMode } from "../../components/compose/LayoutMode";
import { PreviewMode } from "../../components/compose/PreviewMode";
import { IssuesDrawer } from "../../components/compose/IssuesDrawer";
import { useAllPages } from "../../hooks/useAllPages";
import { useComposeStore } from "../../store/compose";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import type { ComposeTab } from "../../components/compose/compose-types";
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

  // ── Tab / drawer state — one tab row, issues as a drawer ─────────────────
  const [tab, setTab] = useState<ComposeTab>("pages");
  const [issuesOpen, setIssuesOpen] = useState(false);
  const [panelReframeId, setPanelReframeId] = useState<string | null>(null);

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
  // Wait for the images query before checking — running against an empty map
  // would flag every panel as a missing-image error while loading.
  const issues = useMemo(
    () => (images ? detectIssues(allPages.filter((p): p is ComicPage => p !== undefined), images) : []),
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

  // One PATCH per page with all bubble edits batched — firing a request per
  // bubble races concurrent read-modify-writes on the same page file.
  function handleBulkUpdateBubbles(
    pageNum: number,
    panelPatches: { id: string; bubbles: (Partial<Bubble> & { id: string })[] }[],
  ) {
    patchPage({ panels: panelPatches as unknown as ComicPage["panels"] }, pageNum);
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
    // patchPage pushes the undo snapshot — no extra push here.
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
    patchPage({ panels: [{ id: targetPanel.id, bubbles: [{ id: `new-${Date.now()}`, type: bubbleType, text: bubbleType === "narration" ? "Narration text..." : "Dialogue...", side: "left" as const }] }] as unknown as ComicPage["panels"] });
  }

  function handleAddSfx() {
    if (!page || !id || !safePage) return;
    const targetPanel = selection?.panelId ? page.panels.find((p) => p.id === selection.panelId) : page.panels[0];
    if (!targetPanel) return;
    patchPage({ panels: [{ id: targetPanel.id, sfx: { text: "KRAK!" } }] as unknown as ComicPage["panels"] });
  }

  // ── Undo / redo ──────────────────────────────────────────────────────────
  // Snapshots are page-scoped: restore to the page they came from, never to
  // whichever page is currently visible (ScriptMode can edit other pages).
  function currentVersionOf(pageNum: number): ComicPage | undefined {
    if (pageNum === safePage && page) return page;
    return allPages[pageNum - 1];
  }

  function handleUndo() {
    const prev = popUndo();
    if (!prev || !id) return;
    const current = currentVersionOf(prev.pageNum);
    if (current) {
      useComposeStore.setState((s) => ({
        redoStack: [...s.redoStack, { pageNum: prev.pageNum, page: structuredClone(current) }],
      }));
    }
    replacePageMut.mutate({ project: id, pageNum: prev.pageNum, data: prev.page });
  }

  function handleRedo() {
    const next = popRedo();
    if (!next || !id) return;
    const current = currentVersionOf(next.pageNum);
    if (current) {
      useComposeStore.setState((s) => ({
        undoStack: [...s.undoStack, { pageNum: next.pageNum, page: structuredClone(current) }],
      }));
    }
    replacePageMut.mutate({ project: id, pageNum: next.pageNum, data: next.page });
  }

  // ── Export / style / translate ───────────────────────────────────────────
  const [exportSuccess, setExportSuccess] = useState<{ format: "pdf" | "cbz"; url: string } | null>(null);

  function handleExport(format: "pdf" | "cbz") {
    if (!id) return;
    setExportSuccess(null);
    exportMut.mutate(
      { project: id, format },
      { onSuccess: (result) => { setExportSuccess({ format, url: result.url ?? downloadExportUrl(id, format) }); } },
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

  // ── Script → Canvas deep-link ────────────────────────────────────────────
  function handleSwitchToCanvas(targetPageNum: number, panelId: string, bubbleId: string) {
    setPageNum(targetPageNum, { preserveSelection: true });
    setTab("pages");
    setPanelReframeId(null);
    select(panelId, "bubble", bubbleId);
  }

  // ── Issue deep-link: navigate to and select the offending item ───────────
  function handleGoToIssue(issue: ComposeIssue) {
    setIssuesOpen(false);
    setPageNum(issue.pageNumber);
    setTab("pages");
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
  // All shortcuts are inert while an input is focused, so typing never
  // triggers tab switches, edits, or anything billable.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (isInputFocused()) return;
      if (e.key === "1") { setTab("pages"); return; }
      if (e.key === "2") { setTab("script"); return; }
      if (e.key === "3") { setTab("export"); return; }
      if ((e.metaKey || e.ctrlKey) && e.key === "e") { e.preventDefault(); setTab("export"); return; }
      if (e.key === "Escape") {
        if (issuesOpen) { setIssuesOpen(false); return; }
        if (panelReframeId) { setPanelReframeId(null); return; }
        deselect();
        return;
      }
      if (tab === "pages") {
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
  const composeStageInfo = projectStatus?.stages?.compose;
  if (loadingList || (!pageList?.length && composeStageStatus !== "pending")) {
    if (composeStageStatus === "running" || composeStageStatus === "pending") {
      return (
        <StagePlaceholder
          stage="compose"
          status={composeStageStatus}
          itemsDone={composeStageInfo?.items_done}
          itemsTotal={composeStageInfo?.items_total}
        />
      );
    }
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">LOADING PAGE EDITOR...</p>
      </div>
    );
  }

  if (!pageList?.length || !id) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <StagePlaceholder
          stage="compose"
          status={composeStageInfo?.status ?? "pending"}
          itemsDone={composeStageInfo?.items_done}
          itemsTotal={composeStageInfo?.items_total}
        />
      </div>
    );
  }

  const pageNumber = safePage ?? 1;
  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.filter((i) => i.severity === "warning").length;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 bg-pulp-paper">
      {/* Thin persistent header — the only tab row */}
      <ComposeHeader
        tab={tab}
        onTabChange={setTab}
        errorCount={errorCount}
        warningCount={warningCount}
        onOpenIssues={() => setIssuesOpen(true)}
        isMatchingStyle={generatePageStyleMut.isPending}
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

      {/* Pages tab */}
      {tab === "pages" && (
            <LayoutMode
              project={id}
              pageList={pageList}
              page={page}
              pageNumber={pageNumber}
              isLoadingPage={loadingPage}
              zoom={zoom}
              selection={selection}
              panelReframeId={panelReframeId}
              canUndo={undoStack.length > 0}
              canRedo={redoStack.length > 0}
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

      {/* Script tab */}
      {tab === "script" && (
        <ScriptMode
          project={id}
          pages={allPages}
          isLoading={loadingAllPages}
          pageIdx={pageIdx}
          onPageSelect={(idx) => setPageNum(idx + 1)}
          onUpdateBubble={(pageNum, panelId, bubbleId, patch) =>
            handleUpdateBubble(panelId, bubbleId, patch, pageNum)
          }
          onBulkUpdateBubbles={handleBulkUpdateBubbles}
          onSwitchToLayout={handleSwitchToCanvas}
        />
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
          outputLanguage={outputLanguage}
          isTranslatingBubbles={translateBubblesMut.isPending}
          issues={issues}
          onPageSelect={(idx) => setPageNum(idx + 1)}
          onExport={handleExport}
          onOutputLanguageChange={handleOutputLanguageChange}
          onTranslateBubbles={handleTranslateBubbles}
        />
      )}

      {/* Issues drawer — reachable from the header chip on any tab */}
      <IssuesDrawer
        open={issuesOpen}
        issues={issues}
        onClose={() => setIssuesOpen(false)}
        onGoToIssue={handleGoToIssue}
      />

      {exportSuccess && (
        <ExportBurst
          pageCount={pageList.length}
          format={exportSuccess.format}
          downloadUrl={exportSuccess.url}
          onDismiss={() => setExportSuccess(null)}
        />
      )}

    </div>
  );
}
