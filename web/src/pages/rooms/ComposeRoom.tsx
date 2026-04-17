import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { usePages, usePage, useUpdatePage, useReplacePage, useReflowPages, useGeneratePageStyleVars, useTranslatePageBubbles, useExport } from "../../api/queries";
import { downloadExportUrl } from "../../api/pages";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { PageNavigator } from "../../components/compose/PageNavigator";
import { PropertyPanel } from "../../components/compose/PropertyPanel";
import { EditorToolbar } from "../../components/compose/EditorToolbar";
import { PageEditor } from "../../components/compose/PageEditor";
import { useComposeStore } from "../../store/compose";
import type { ComicPage, Bubble, Sfx } from "../../types/api";
import "../../components/compose/comic-page.css";

export function ComposeRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: pageList, isLoading: loadingList } = usePages(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const currentPage = Number(searchParams.get("page") ?? 1);
  const safePage = pageList?.length ? Math.min(currentPage, pageList.length) : undefined;
  const { data: page, isLoading: loadingPage } = usePage(name, safePage);

  const updatePageMut = useUpdatePage();
  const replacePageMut = useReplacePage();
  const reflowPagesMut = useReflowPages();
  const generatePageStyleMut = useGeneratePageStyleVars();
  const translateBubblesMut = useTranslatePageBubbles();
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

  function setPage(p: number) {
    setSearchParams({ page: String(p) }, { replace: true });
    deselect();
    clearHistory();
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

  function handleTranslateBubbles() {
    if (!name || !page) return;
    pushUndo(page);
    translateBubblesMut.mutate({ project: name });
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
    <div className="space-y-3 -mx-5 px-3 max-w-none">
      <ShowcaseHeader
        label="COMPOSE / PAGE EDITOR"
        title="PAGE EDITOR"
        lead="Position bubbles, edit dialogue, adjust layout, and export your comic."
      />

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
      />

      <div className="flex gap-4 h-[calc(100vh-180px)]">
        {/* Left: page navigator */}
        <div className="w-[220px] flex-shrink-0 overflow-y-auto">
          <PageNavigator
            project={name}
            pages={pageList}
            currentPage={pageNumber}
            onSelect={setPage}
          />
        </div>

        {/* Center: native React editor (replaces iframe + overlay) */}
        <div className="flex-1 flex items-center justify-center overflow-hidden bg-ink-black/5 p-4 border-[2px] border-ink-black">
          {loadingPage ? (
            <div
              className="flex items-center justify-center bg-ink-black/5"
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
              selectedId={selection?.elementId ?? null}
              selectedType={selection?.type ?? null}
              onSelect={select}
              onDeselect={deselect}
              onDragEnd={handleDragEnd}
            />
          ) : null}
        </div>

        {/* Right: property panel */}
        <div className="w-[340px] flex-shrink-0 overflow-y-auto">
          {page ? (
            <PropertyPanel
              page={page}
              selection={selection}
              onUpdateBubble={handleUpdateBubble}
              onUpdateSfx={handleUpdateSfx}
              onUpdatePage={handleUpdatePageProps}
              onReflowPages={handleReflowPages}
              onGeneratePageStyle={handleGeneratePageStyle}
              onTranslateBubbles={handleTranslateBubbles}
              isGeneratingPageStyle={generatePageStyleMut.isPending}
              isTranslatingBubbles={translateBubblesMut.isPending}
              onDeleteElement={handleDeleteElement}
              onUnpin={handleUnpin}
            />
          ) : (
            <div />
          )}
        </div>
      </div>
    </div>
  );
}
