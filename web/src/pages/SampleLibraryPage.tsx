import { Link, useSearchParams } from "react-router-dom";
import { BrandIdentity } from "../components/BrandIdentity";
import { SampleLibrary } from "../components/wizard/SampleLibrary";
import { useI18n } from "../i18n";

export function SampleLibraryPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  return (
    <div className="min-h-svh bg-pulp-paper text-ink-black">
      <a href="#samples-main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-bristol focus:p-3">{t("Skip to stories")}</a>
      <header className="border-b-[3px] border-ink-black bg-bristol px-5 py-4 sm:px-8">
        <div className="mx-auto flex max-w-[1260px] flex-wrap items-center justify-between gap-4">
          <Link to="/" aria-label={t("Back to home")}><BrandIdentity /></Link>
          <Link to="/signup" className="inline-flex min-h-11 items-center border-2 border-ink-black bg-hero-red px-4 font-meta text-xs font-bold text-bristol shadow-ink-sm hover:bg-[#94141c]">{t("CREATE ACCOUNT")} ↗</Link>
        </div>
      </header>
      <main id="samples-main">
        <div className="bg-ink-black px-5 py-12 text-bristol sm:px-8 sm:py-16">
          <div className="mx-auto max-w-[1260px]">
            <p className="font-meta text-xs font-bold uppercase tracking-[0.2em] text-narrator-gold">{t("THE SAMPLE SHELF")}</p>
            <h1 className="mt-4 max-w-[15ch] font-display text-5xl font-black uppercase leading-[0.92] tracking-[-0.04em] sm:text-7xl">{t("Find a story worth drawing.")}</h1>
            <p className="mt-6 max-w-[65ch] text-base leading-7 text-bristol/80">{t("Explore selected modern stories alongside the classic archive. Search by author, title, or theme; read a complete story before you choose.")}</p>
          </div>
        </div>
        <div className="mx-auto max-w-[1260px] px-5 py-8 sm:px-8 sm:py-12">
          <SampleLibrary initialReadCode={searchParams.get("story")} onReaderChange={(code) => {
            const next = new URLSearchParams(searchParams);
            if (code) next.set("story", code);
            else next.delete("story");
            setSearchParams(next, { replace: true });
          }} />
        </div>
      </main>
    </div>
  );
}
