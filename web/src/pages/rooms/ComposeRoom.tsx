import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { usePages, usePage, useUpdatePage, useReplacePage, useReflowPages, useGeneratePageStyleVars, useTranslatePageBubbles, useExport, useProjectConfig, useUpdateProjectConfig } from "../../api/queries";
import { downloadExportUrl } from "../../api/pages";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Button } from "../../components/ui/Button";
import { PageNavigator } from "../../components/compose/PageNavigator";
import { PropertyPanel } from "../../components/compose/PropertyPanel";
import { EditorToolbar } from "../../components/compose/EditorToolbar";
import { PageEditor } from "../../components/compose/PageEditor";
import { useRunAction } from "../../hooks/useRunAction";
import { useComposeStore } from "../../store/compose";
import type { ComicPage, Bubble, Sfx } from "../../types/api";
import "../../components/compose/comic-page.css";

export function ComposeRoom() {
  const { name } = useParams<{ name: string }>();
  const { handleRun, isPending } = useRunAction();
  const { data: pageList, isLoading: loadingList } = usePages(name);
  const { data: projectConfig } = useProjectConfig(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const currentPage = Number(searchParams.get("page") ?? 1);
  const safePage = pageList?.length ? Math.min(currentPage, pageList.length) : undefined;
  const { data: page, isLoading: loadingPage } = usePage(name, safePage);

  const updatePageMut = useUpdatePage();
  const replacePageMut = useReplacePage();
  const reflowPagesMut = useReflowPages();
  const generatePageStyleMut = useGeneratePageStyleVars();
  const translateBubblesMut = useTranslatePageBubbles();
  const updateProjectConfigMut = useUpdateProjectConfig();
  const exportMut = useExport();

  const selection = useComposeStore((s) => s.selection);
  const select = useComposeStore((s) => s.select);
  const deselect = useComposeStore((s) => s.deselect);
  const pushUndo = useComposeStore((s) => s.pushUndo);
  const popUndo = useComposeStore((s) => s.popUndo);
  const popRedo = useComposeStore((s) => s.popRedo);
  const undoStack = useComposeStore((s) => s.undoStack);
  const redoStack = useComposeStore((s) => s.redoStack);
  const clearHistory = useComposeStore((s) => s.clearHistory);
  const [zoom, setZoom] = useState(1);
  const [outputLanguageOverride, setOutputLanguageOverride] = useState<"en" | "es" | "fr" | null>(null);
  const clampZoom = (value: number) => Math.max(0.5, Math.min(2.5, Number(value.toFixed(2))));
  const outputLanguage = outputLanguageOverride ?? projectConfig?.target_language ?? "en";

  function setPage(p: number) {
    setSearchParams({ page: String(p) }, { replace: true });
    deselect();
    clearHistory();
    setZoom(1);
  }

  // ── Mutations ────────────────────────────────────────────────────────────

  function patchPage(patch: Partial<ComicPage>) {
    if (!name || !safePage || !page) return;
    pushUndo(page);
    updatePageMut.mutate({
      project: name,
      pageNum: safePage,
      data: patch,
    });
  }

  function handleUpdateBubble(panelId: string, bubbleId: string, bPatch: Partial<Bubble>) {
    patchPage({
      panels: [{ id: panelId, bubbles: [{ id: bubbleId, ...bPatch }] }] as ComicPage["panels"],
    });
  }

  function handleUpdateSfx(panelId: string, sPatch: Partial<Sfx>) {
    patchPage({
      panels: [{ id: panelId, sfx: sPatch }] as ComicPage["panels"],
    });
  }

  function handleUpdatePanel(panelId: string, pPatch: Partial<ComicPage["panels"][number]>) {
    patchPage({
      panels: [{ id: panelId, ...pPatch }] as ComicPage["panels"],
    });
  }

  function handleUpdatePageProps(patch: Partial<ComicPage>) {
    patchPage(patch);
  }

  function handleReflowPages(panelsPerPage: number) {
    if (!name || !page) return;
    reflowPagesMut.mutate(
      { project: name, panelsPerPage },
      {
        onSuccess: (pages) => {
          clearHistory();
          const lastPage = pages.at(-1)?.page_number ?? 1;
          if (currentPage > lastPage) setPage(lastPage);
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
    updateProjectConfigMut.mutate({
      project: name,
      data: { target_language: targetLanguage },
    });
  }

  function handleDeleteElement(panelId: string, type: "bubble" | "sfx", elementId: string) {
    if (!name || !safePage || !page) return;
    pushUndo(page);
    if (type === "bubble") {
      patchPage({
        panels: [{ id: panelId, remove_bubble_ids: [elementId] }] as unknown as ComicPage["panels"],
      });
    } else {
      patchPage({
        panels: [{ id: panelId, remove_sfx: true }] as unknown as ComicPage["panels"],
      });
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

  function handleDragEnd(
    panelId: string,
    type: "bubble" | "sfx",
    elementId: string,
    x: number,
    y: number,
  ) {
    if (type === "bubble") {
      handleUpdateBubble(panelId, elementId, { x, y });
    } else {
      handleUpdateSfx(panelId, { x, y });
    }
  }

  function handleAddBubble(bubbleType: "speech" | "thought" | "narration") {
    if (!page || !name || !safePage) return;
    const targetPanel = selection?.panelId
      ? page.panels.find((p) => p.id === selection.panelId)
      : page.panels[0];
    if (!targetPanel) return;
    pushUndo(page);
    const newBubble = {
      id: `new-${Date.now()}`,
      type: bubbleType,
      text: bubbleType === "narration" ? "Narration text..." : "Dialogue...",
      side: "left" as const,
    };
    patchPage({
      panels: [{ id: targetPanel.id, bubbles: [newBubble] }] as unknown as ComicPage["panels"],
    });
  }

  function handleAddSfx() {
    if (!page || !name || !safePage) return;
    const targetPanel = selection?.panelId
      ? page.panels.find((p) => p.id === selection.panelId)
      : page.panels[0];
    if (!targetPanel) return;
    pushUndo(page);
    patchPage({
      panels: [{ id: targetPanel.id, sfx: { text: "KRAK!" } }] as unknown as ComicPage["panels"],
    });
  }

  function handleUndo() {
    const prev = popUndo();
    if (!prev || !name || !safePage || !page) return;
    useComposeStore.setState((s) => ({
      redoStack: [...s.redoStack, structuredClone(page)],
    }));
    replacePageMut.mutate({
      project: name,
      pageNum: safePage,
      data: prev,
    });
  }

  function handleRedo() {
    const next = popRedo();
    if (!next || !name || !safePage || !page) return;
    useComposeStore.setState((s) => ({
      undoStack: [...s.undoStack, structuredClone(page)],
    }));
    replacePageMut.mutate({
      project: name,
      pageNum: safePage,
      data: next,
    });
  }

  function handleExport(format: "pdf" | "cbz") {
    if (!name) return;
    exportMut.mutate(
      { project: name, format },
      {
        onSuccess: () => {
          window.open(downloadExportUrl(name, format), "_blank");
        },
      },
    );
  }

  function handleZoomIn() {
    setZoom((z) => clampZoom(z + 0.1));
  }

  function handleZoomOut() {
    setZoom((z) => clampZoom(z - 0.1));
  }

  function handleZoomReset() {
    setZoom(1);
  }

  // ── Keyboard shortcuts ───────────────────────────────────────────────────

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Delete" || e.key === "Backspace") {
        if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "TEXTAREA") return;
        if (selection && page) {
          handleDeleteElement(selection.panelId, selection.type, selection.elementId);
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && e.shiftKey) {
        e.preventDefault();
        handleRedo();
      }
      if (e.key === "Escape") {
        deselect();
      }
      if ((e.metaKey || e.ctrlKey) && (e.key === "=" || e.key === "+")) {
        e.preventDefault();
        handleZoomIn();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "-") {
        e.preventDefault();
        handleZoomOut();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "0") {
        e.preventDefault();
        handleZoomReset();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  // ── Render ───────────────────────────────────────────────────────────────

  if (loadingList) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
          LOADING PAGE EDITOR...
        </p>
      </div>
    );
  }

  if (!pageList?.length || !name) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <div className="text-center">
          <div className="font-display text-[1.5rem] font-bold tracking-[-0.05em] text-ink-black/30">
            PAGE EDITOR NOT AVAILABLE
          </div>
          <p className="mt-2 text-[0.82rem] text-ink-black/50">
            Complete the COMPOSE stage first.
          </p>
        </div>
      </div>
    );
  }

  const pageNumber = safePage ?? 1;

  return (
    <div className="-mx-5 -my-6 flex min-h-[calc(100vh-58px)] flex-col bg-sidebar-tint/55 md:-my-6">
      <ShowcaseHeader
        label="COMPOSE / PAGE EDITOR"
        title="PAGE EDITOR"
        lead="Position bubbles, edit dialogue, adjust layout, and export your comic."
        className="mx-3 mt-3 shrink-0 md:mx-4 md:mt-4"
        actions={(
          <Button
            size="sm"
            variant="outline"
            onClick={() => name && handleRun(name, "assemble", true)}
            disabled={isPending}
          >
            {isPending ? "RERUNNING…" : "RERUN COMPOSE"}
          </Button>
        )}
      />

      <div className="sticky top-0 z-20 mx-3 mt-3 shrink-0 md:mx-4">
        <EditorToolbar
          onAddBubble={handleAddBubble}
          onAddSfx={handleAddSfx}
          onDelete={() => {
            if (selection) handleDeleteElement(selection.panelId, selection.type, selection.elementId);
          }}
          onUndo={handleUndo}
          onRedo={handleRedo}
          onExport={handleExport}
          hasSelection={!!selection}
          canUndo={undoStack.length > 0}
          canRedo={redoStack.length > 0}
          isExporting={exportMut.isPending}
          zoomPercent={zoom * 100}
          onZoomIn={handleZoomIn}
          onZoomOut={handleZoomOut}
          onZoomReset={handleZoomReset}
        />
      </div>

      <div className="grid flex-1 min-h-0 gap-3 p-3 md:grid-cols-[180px_minmax(0,1fr)] md:p-4 xl:grid-cols-[220px_minmax(0,1fr)_340px]">
        <aside className="min-w-0 md:min-h-0">
          <PageNavigator
            project={name}
            pages={pageList}
            currentPage={pageNumber}
            onSelect={setPage}
          />
        </aside>

        <section className="min-w-0 min-h-[560px] overflow-hidden border-[2px] border-ink-black bg-[radial-gradient(circle_at_1px_1px,rgba(27,28,21,0.12)_1px,transparent_0)] [background-size:18px_18px] p-2 shadow-[6px_6px_0_0_var(--color-ghost-shadow)] md:min-h-0 md:p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">
                PAGE BENCH
              </div>
              <div className="font-display text-[1.1rem] font-bold leading-none tracking-[-0.02em] text-ink-black">
                Page {String(pageNumber).padStart(2, "0")}
              </div>
            </div>
            <div className="hidden font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/45 sm:block">
              {page?.panels.length ?? 0} PANELS
            </div>
          </div>
          <div className="h-[72vh] min-h-[480px] overflow-hidden border-[2px] border-ink-black bg-pulp-paper/90 p-2 md:h-[calc(100vh-306px)] md:min-h-0">
            {loadingPage ? (
              <div
                className="flex h-full items-center justify-center bg-ink-black/5"
                style={{ aspectRatio: "2480 / 3508", maxHeight: "100%" }}
              >
                <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                  LOADING PAGE...
                </p>
              </div>
            ) : page ? (
              <PageEditor
                page={page}
                project={name}
                zoom={zoom}
                onZoomChange={(nextZoom) => setZoom(clampZoom(nextZoom))}
                selectedId={selection?.elementId ?? null}
                selectedType={selection?.type ?? null}
                onSelect={select}
                onDeselect={deselect}
                onDragEnd={handleDragEnd}
              />
            ) : null}
          </div>
        </section>

        <aside className="min-w-0 xl:min-h-0">
          {page ? (
            <PropertyPanel
              page={page}
              selection={selection}
              onUpdatePanel={handleUpdatePanel}
              onUpdateBubble={handleUpdateBubble}
              onUpdateSfx={handleUpdateSfx}
              onUpdatePage={handleUpdatePageProps}
              onReflowPages={handleReflowPages}
              onGeneratePageStyle={handleGeneratePageStyle}
              outputLanguage={outputLanguage}
              onOutputLanguageChange={handleOutputLanguageChange}
              onTranslateBubbles={handleTranslateBubbles}
              isGeneratingPageStyle={generatePageStyleMut.isPending}
              isTranslatingBubbles={translateBubblesMut.isPending}
              onDeleteElement={handleDeleteElement}
              onUnpin={handleUnpin}
            />
          ) : null}
        </aside>
      </div>
    </div>
  );
}
