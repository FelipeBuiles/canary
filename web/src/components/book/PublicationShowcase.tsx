import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { Publication } from "../../api/publications";
import { useI18n } from "../../i18n";

export function PublicationShowcase() {
  const { t } = useI18n();
  const { data } = useQuery({ queryKey: ["featured-books"], queryFn: async ({ signal }) => {
    const response = await fetch("/api/public/books", { signal });
    if (!response.ok) throw new Error("Showcase unavailable");
    return response.json() as Promise<Publication[]>;
  }, retry: false });
  if (!data?.length) return null;
  return (
    <section className="landing-showcase" aria-labelledby="showcase-title">
      <div className="landing-section-heading">
        <h2 id="showcase-title">{t("Read a finished book")}</h2>
        <p>{t("Explore complete stories made with Scenewright, from the first page to the last.")}</p>
      </div>
      <div className="landing-showcase__books">
        {data.map(book => (
          <article key={book.id} className="landing-showcase__book">
            <Link className="landing-showcase__cover" to={`/read/${book.id}`} aria-label={book.title}>
              <img src={book.pages[0].url} alt="" width={book.pages[0].width} height={book.pages[0].height} loading="lazy" decoding="async" />
            </Link>
            <div className="landing-showcase__copy">
              <p className="landing-showcase__credit">{book.author} · {book.pages.length} {t("pages")}</p>
              <h3><Link to={`/read/${book.id}`}>{book.title}</Link></h3>
              {book.description && <p className="landing-showcase__description">{book.description}</p>}
              <Link to={`/read/${book.id}`} className="landing-text-link">{t("Read book")}<span aria-hidden="true">→</span></Link>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
