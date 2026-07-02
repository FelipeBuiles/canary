import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import { fetchBranding, getCachedBranding, type Branding } from "../lib/legal";

/**
 * Shared chrome for the three legal pages (Terms, Privacy, Acceptable Use).
 * Public — no auth required. Reads contact emails from /api/branding so the
 * docs stay in sync with the configured legal/support address.
 */
export function LegalLayout({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: ReactNode;
}) {
  const [branding, setBranding] = useState<Branding>(getCachedBranding());

  useEffect(() => {
    fetchBranding().then(setBranding);
  }, []);

  return (
    <div className="min-h-svh bg-ink-black text-pulp-paper">
      <header className="flex h-14 items-center border-b-[2px] border-ink-black bg-bristol px-4 text-ink-black">
        <Link to="/" className="flex items-center gap-2.5">
          <BrandMark className="h-7 w-7 shrink-0" />
          <span className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
            {branding.product_name}
          </span>
        </Link>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-12 sm:px-8 sm:py-16">
        <h1 className="font-display text-[2.4rem] font-black uppercase leading-[0.95] tracking-[-0.03em] text-pulp-paper sm:text-[3rem]">
          {title}
        </h1>
        <p className="mt-3 font-meta text-[0.6rem] font-bold uppercase tracking-[0.18em] text-pulp-paper/45">
          Last updated: {updated}
        </p>

        <div className="legal-prose mt-10 font-body text-[0.95rem] leading-7 text-pulp-paper/80">
          {children}
        </div>

        <footer className="mt-16 border-t border-pulp-paper/15 pt-6 font-meta text-[0.58rem] uppercase tracking-[0.16em] text-pulp-paper/40">
          © 2026 {branding.product_name} ·{" "}
          <a className="hover:text-pulp-paper/70" href={`mailto:${branding.legal_email}`}>
            {branding.legal_email}
          </a>
        </footer>
      </main>
    </div>
  );
}
