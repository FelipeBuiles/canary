import { useState } from "react";
import { useParams } from "react-router-dom";
import { usePages, usePage } from "../../api/queries";
import { SectionLabel } from "../../components/SectionLabel";
import { PageCanvas } from "../../components/PageCanvas";
import { FloatingPalette } from "../../components/FloatingPalette";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";

export function ComposeRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: pageList, isLoading: loadingList } = usePages(name);
  const [currentPage, setCurrentPage] = useState(1);
  const safePage = pageList?.length ? Math.min(currentPage, pageList.length) : undefined;
  const { data: page, isLoading: loadingPage } = usePage(name, safePage);

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

  const totalPages = pageList.length;
  const pageNumber = safePage ?? 1;

  return (
    <div className="space-y-5">
      <section className="border-[2px] border-ink-black bg-bristol p-4 md:p-5">
        <SectionLabel>COMPOSE / PAGE EDITOR</SectionLabel>
        <h1 className="mt-3 font-display text-[2.5rem] font-bold leading-[0.86] tracking-[-0.08em] text-ink-black">
          PAGE EDITOR
        </h1>
      </section>

      <section className="grid gap-5 xl:grid-cols-[1fr_200px]">
        <div>
          {/* Page navigation */}
          <div className="mb-4 flex items-center gap-3">
            <Button
              variant="secondary"
              size="md"
              onClick={() => setCurrentPage(Math.max(1, pageNumber - 1))}
              disabled={pageNumber <= 1}
            >
              ← PREV
            </Button>
            <div className="border-[2px] border-ink-black bg-bristol px-4 py-2 font-display text-[0.9rem] font-bold tracking-[-0.03em]">
              PAGE {String(pageNumber).padStart(2, "0")} / {totalPages}
            </div>
            <Button
              variant="secondary"
              size="md"
              onClick={() => setCurrentPage(Math.min(totalPages, pageNumber + 1))}
              disabled={pageNumber >= totalPages}
            >
              NEXT →
            </Button>

            <div className="ml-auto flex gap-1.5">
              {pageList.map((p) => (
                <button
                  key={p.page_number}
                  onClick={() => setCurrentPage(p.page_number)}
                  className={`h-6 w-6 border-[2px] border-ink-black font-meta text-[0.44rem] tracking-[0.12em] ${
                    p.page_number === pageNumber
                      ? "bg-hero-red text-bristol"
                      : "bg-pulp-paper text-ink-black"
                  }`}
                >
                  {p.page_number}
                </button>
              ))}
            </div>
          </div>

          {/* Page canvas */}
          {loadingPage ? (
            <Card className="flex min-h-[40vh] items-center justify-center">
              <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                LOADING PAGE...
              </p>
            </Card>
          ) : page ? (
            <PageCanvas page={page} projectName={name} />
          ) : null}
        </div>

        <FloatingPalette />
      </section>
    </div>
  );
}
