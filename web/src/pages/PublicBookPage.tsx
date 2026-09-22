import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { publicBook } from "../api/publications";
import { BrandIdentity } from "../components/BrandIdentity";
import { BrandMark } from "../components/BrandMark";
import { BookReader } from "../components/BookReader";
import { Button } from "../components/ui/Button";
import type { ReaderPage } from "../lib/bookReader";
import { useI18n } from "../i18n";
import "./PublicBookPage.css";

export function PublicBookPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["public-book", id],
    queryFn: ({ signal }) => publicBook(id, signal),
    retry: false,
  });
  const [readerOpen, setReaderOpen] = useState(true);
  const [message, setMessage] = useState("");
  const book = query.data;
  const referral = `/signup?ref=book-${encodeURIComponent(id)}`;
  const pages = useMemo<ReaderPage[]>(() => book?.pages.map(page => ({
    pageNumber: page.number,
    revision: 1,
    imageUrl: page.url,
    spreadRole: page.spread_role ?? (page.width > page.height ? "spread" : "single"),
  })) ?? [], [book]);

  async function share() {
    try {
      if (navigator.share) await navigator.share({ title: book?.title, url: window.location.href });
      else {
        await navigator.clipboard.writeText(window.location.href);
        setMessage(t("Link copied."));
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setMessage(t("Copy this page’s address to share the book."));
      }
    }
  }

  const closingPage = book && (
    <section className="public-book-end" aria-labelledby="bookend-title">
      <BrandMark className="mx-auto h-14 w-14" />
      <p className="mt-4 font-meta">{t("Made with Scenewright")}</p>
      <h2 id="bookend-title" className="mt-5 font-display text-3xl">{t("Every book starts with a story.")}</h2>
      <p className="mt-3 font-body">{t("Bring your story to life.")}</p>
      <Link className="public-book-cta" to={referral}>{t("Create yours with Scenewright")}</Link>
      <details className="mt-8">
        <summary className="cursor-pointer p-3 underline">{t("Download this book")}</summary>
        <img className="mx-auto my-4 w-full max-w-64 border-2 border-ink-black" src={`/api/public/books/${book.id}/bookend`} alt={t("Back page preview")} loading="lazy" />
        <div className="flex justify-center gap-6">
          {["pdf", "cbz"].map(format => <a key={format} className="p-3 underline" href={`/api/public/books/${book.id}/download/${format}`}>{format.toUpperCase()}</a>)}
        </div>
      </details>
    </section>
  );

  return <div className="public-book">
    <header className="public-book-header">
      <Link to="/" className="inline-flex items-center"><BrandIdentity /></Link>
      <Link to={referral} className="underline">{t("Create your own")}</Link>
    </header>
    <main>
      {query.isPending && <p className="p-8" role="status">{t("Loading book…")}</p>}
      {query.isError && <section className="p-8">
        <h1 className="font-display text-3xl">{t("Book unavailable")}</h1>
        <p role="alert">{t(query.error.message)}</p>
        <Button onClick={() => void query.refetch()}>{t("Try again")}</Button>
      </section>}
      {book && <>
        <title>{book.title} — Scenewright</title>
        {!readerOpen && <>
          <section className="public-book-intro">
            {book.pages[0] && <button className="public-book-cover" onClick={() => setReaderOpen(true)} aria-label={t("Open the first page")}>
              <img src={book.pages[0].url} width={book.pages[0].width} height={book.pages[0].height} alt={t("First page of the book")} />
            </button>}
            <div className="public-book-description">
            <h1 className="font-display text-4xl">{book.title}</h1>
            <p className="mt-2 font-meta">{book.author} · {book.pages.length} {t("pages")}</p>
            {book.description && <p className="mt-4 max-w-prose font-body">{book.description}</p>}
            <div className="mt-5 flex flex-wrap gap-3">
              <Button onClick={() => setReaderOpen(true)}>{t("Read your book")}</Button>
              <Button variant="outline" onClick={() => void share()}>{t("Share book")}</Button>
            </div>
            {message && <p role="status" className="mt-3">{message}</p>}
            </div>
          </section>
          {closingPage}
        </>}
        {readerOpen && <BookReader
          key={`${book.id}-${book.version}`}
          pages={pages}
          title={book.title}
          onClose={() => setReaderOpen(false)}
          closeLabel={t("About this book")}
          headerActions={<>
            <button type="button" className="min-h-11 border-2 border-bristol/40 px-3 font-meta text-xs font-bold text-bristol hover:border-bristol" onClick={() => void share()}>{t("Share book")}</button>
            {message && <span role="status" className="max-w-64 text-sm text-bristol">{message}</span>}
          </>}
          endContent={closingPage}
        />}
      </>}
    </main>
  </div>;
}
