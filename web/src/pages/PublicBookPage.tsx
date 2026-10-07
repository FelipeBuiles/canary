import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { publicBook, publicationLanguages, type PublicationLocale } from "../api/publications";
import { BrandIdentity } from "../components/BrandIdentity";
import { BrandMark } from "../components/BrandMark";
import { BookReader } from "../components/BookReader";
import { Button } from "../components/ui/Button";
import type { ReaderPage } from "../lib/bookReader";
import { LANGUAGES, useI18n } from "../i18n";
import { cn } from "../lib/cn";
import "./PublicBookPage.css";
import { usePublicMetadata } from "../lib/publicMetadata";
import { KAITLIN_EXAMPLE_BOOK_ID, PUBLIC_ORIGIN } from "../lib/publicPages";

/** One reading-language preference per viewer, shared by every public book. */
const READER_LANGUAGE_KEY = "canary.readerLanguage";

function storedReaderLanguage(): string | null {
  try {
    return window.localStorage.getItem(READER_LANGUAGE_KEY);
  } catch {
    return null;
  }
}

function storeReaderLanguage(locale: PublicationLocale) {
  try {
    window.localStorage.setItem(READER_LANGUAGE_KEY, locale);
  } catch {
    // A convenience only; the reader still switches without storage.
  }
}

export function PublicBookPage() {
  const { id = "" } = useParams();
  const { t, language } = useI18n();
  const query = useQuery({
    queryKey: ["public-book", id],
    queryFn: ({ signal }) => publicBook(id, signal),
    retry: false,
  });
  const [readerOpen, setReaderOpen] = useState(true);
  const [message, setMessage] = useState("");
  const book = query.data;
  usePublicMetadata(book ? `${book.title} — Scenewright` : query.isError ? "Book unavailable — Scenewright" : undefined,
    book?.description || (query.isError ? "This book is not available." : `By ${book?.author ?? ""} · Read on Scenewright`), `/read/${id}`, book?.pages[0]?.url,
    { noindex: query.isError, schema: book ? { "@context": "https://schema.org", "@type": "Book", name: book.title,
      author: { "@type": "Person", name: book.author }, description: book.description, url: `${PUBLIC_ORIGIN}/read/${id}`,
      numberOfPages: book.pages.length, image: new URL(book.pages[0].url, PUBLIC_ORIGIN).href,
      ...(book.source_credit ? { isBasedOn: book.source_credit.source_url, license: book.source_credit.license_url } : {}) } : undefined });
  const referral = `/signup?ref=book-${encodeURIComponent(id)}`;
  const languages = useMemo(() => book ? publicationLanguages(book) : [], [book]);
  const [preferredLanguage, setPreferredLanguage] = useState<string | null>(() => storedReaderLanguage() ?? language ?? null);
  const selectedLanguage = languages.find(item => item.locale === preferredLanguage) ?? languages[0];
  const bookPages = selectedLanguage?.pages ?? book?.pages;
  const languageName = (locale: PublicationLocale) => LANGUAGES.find(item => item.code === locale)?.label ?? t("Original language");
  const downloadLocale = selectedLanguage && selectedLanguage !== languages[0] ? `?locale=${selectedLanguage.locale}` : "";
  function chooseLanguage(locale: PublicationLocale) {
    setPreferredLanguage(locale);
    storeReaderLanguage(locale);
  }
  const languageToggle = (tone: "reader" | "paper") => languages.length > 1 && <div role="group" aria-label={t("Book language")} className="flex">
    {languages.map((item, index) => <button
      key={item.locale}
      type="button"
      lang={item.locale === "source" ? undefined : item.locale}
      aria-label={languageName(item.locale)}
      aria-pressed={item === selectedLanguage}
      onClick={() => chooseLanguage(item.locale)}
      className={cn(
        "min-h-11 min-w-11 border-2 px-3 font-meta text-xs font-bold transition-colors",
        index > 0 && "-ml-[2px]",
        tone === "reader"
          ? (item === selectedLanguage ? "relative border-bristol bg-bristol text-ink-black" : "border-bristol/40 text-bristol hover:border-bristol")
          : (item === selectedLanguage ? "relative border-ink-black bg-ink-black text-pulp-paper" : "border-ink-black text-ink-black hover:bg-ink-black/10"),
      )}
    >{item.locale === "source" ? t("Original") : item.locale.toUpperCase()}</button>)}
  </div>;
  const pages = useMemo<ReaderPage[]>(() => bookPages?.map(page => ({
    pageNumber: page.number,
    revision: 1,
    imageUrl: page.url,
    spreadRole: page.spread_role ?? (page.width > page.height ? "spread" : "single"),
  })) ?? [], [bookPages]);

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
      <h2 className="font-display text-3xl">{book.title}</h2>
      <p className="mt-3">{book.author} · {book.pages.length} {t("pages")}</p>
      {book.description && <p className="mx-auto mt-4 max-w-prose">{book.description}</p>}
      {book.id === KAITLIN_EXAMPLE_BOOK_ID && <p className="mt-4 flex flex-wrap justify-center gap-5">
        <Link className="underline" to="/samples?story=kaitlin-out-of-space">{t("READ THE ORIGINAL")}</Link>
        <Link className="underline" to="/examples/kaitlin-out-of-space">{t("landing.footer.example")}</Link>
      </p>}
      <BrandMark className="mx-auto h-14 w-14" />
      <p className="mt-4 font-meta">{t("Made with Scenewright")}</p>
      <h2 id="bookend-title" className="mt-5 font-display text-3xl">{t("Every book starts with a story.")}</h2>
      <p className="mt-3 font-body">{t("Bring your story to life.")}</p>
      {book.source_credit && <aside className="mx-auto mt-7 max-w-prose border-y-2 border-ink-black/20 py-5 text-left text-sm leading-6">
        <h3 className="font-meta text-xs font-bold uppercase tracking-widest">{t("Source and license")}</h3>
        <p className="mt-2">{t("Based on")} <a className="underline" href={book.source_credit.source_url} target="_blank" rel="noopener noreferrer">“{book.source_credit.title}”</a> {t("by")} {book.source_credit.author}, {t("from the SCP Wiki")}.</p>
        <p className="mt-2">{t("This comic adaptation is licensed under")} <a className="underline" href={book.source_credit.license_url} target="_blank" rel="noopener noreferrer">{book.source_credit.license}</a>.</p>
      </aside>}
      <Link className="public-book-cta" to={referral}>{t("Create yours with Scenewright")}</Link>
      <details className="mt-8">
        <summary className="cursor-pointer p-3 underline">{t("Download this book")}</summary>
        <img className="mx-auto my-4 w-full max-w-64 border-2 border-ink-black" src={`/api/public/books/${book.id}/bookend`} alt={t("Back page preview")} loading="lazy" />
        <div className="flex justify-center gap-6">
          {["pdf", "cbz"].map(format => <a key={format} className="p-3 underline" href={`/api/public/books/${book.id}/download/${format}${downloadLocale}`}>{format.toUpperCase()}</a>)}
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
        <ErrorNotice error={query.error} operation="load" onRetry={() => void query.refetch()} />
      </section>}
      {book && <>
        {!readerOpen && <>
          <section className="public-book-intro">
            {bookPages?.[0] && <button className="public-book-cover" onClick={() => setReaderOpen(true)} aria-label={t("Open the first page")}>
              <img src={bookPages[0].url} width={bookPages[0].width} height={bookPages[0].height} alt={t("First page of the book")} />
            </button>}
            <div className="public-book-description">
            <h1 className="font-display text-4xl">{book.title}</h1>
            <p className="mt-2 font-meta">{book.author} · {book.pages.length} {t("pages")}</p>
            {book.description && <p className="mt-4 font-body">{book.description}</p>}
            <div className="mt-5 flex flex-wrap gap-3">
              {languageToggle("paper")}
              <Button onClick={() => setReaderOpen(true)}>{t("Read your book")}</Button>
              <Button variant="outline" onClick={() => void share()}>{t("Share book")}</Button>
            </div>
            {message && <p role="status" className="mt-3">{message}</p>}
            </div>
          </section>
          {closingPage}
        </>}
        {readerOpen && <><h1 className="sr-only">{book.title}</h1><BookReader
          key={`${book.id}-${book.version}`}
          pages={pages}
          title={book.title}
          onClose={() => setReaderOpen(false)}
          closeLabel={t("About this book")}
          languageLabel={languages.length > 1 && selectedLanguage ? languageName(selectedLanguage.locale) : undefined}
          headerActions={<>
            {languageToggle("reader")}
            <button type="button" className="min-h-11 border-2 border-bristol/40 px-3 font-meta text-xs font-bold text-bristol hover:border-bristol" onClick={() => void share()}>{t("Share book")}</button>
            {message && <span role="status" className="max-w-64 text-sm text-bristol">{message}</span>}
          </>}
          endContent={closingPage}
        /></>}
      </>}
    </main>
  </div>;
}
import { ErrorNotice } from "../components/composites/ErrorNotice";
