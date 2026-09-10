import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
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
    <div className="min-h-svh bg-pulp-paper text-ink-black">
      <header className="border-b-[2px] border-ink-black bg-bristol px-5 text-ink-black sm:px-8">
        <div className="mx-auto flex min-h-18 max-w-[1100px] flex-wrap items-center justify-between gap-3 py-3">
        <Link to="/" className="flex min-h-11 items-center gap-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red">
          <BrandMark className="h-8 w-8 shrink-0" variant="micro" />
          <span className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
            {branding.product_name}
          </span>
        </Link>
        <Link to="/" className="inline-flex min-h-11 items-center gap-2 font-body text-sm font-semibold underline underline-offset-4 hover:text-hero-red">
          <ArrowLeft size={16} aria-hidden="true" /> Back to home
        </Link>
        </div>
      </header>

      <main className="mx-auto max-w-[1100px] px-5 py-8 sm:px-8 sm:py-12">
        <nav aria-label="Legal documents" className="mb-10 flex flex-wrap gap-x-5 gap-y-1 border-b border-ink-black/20 pb-4">
          {[
            { to: "/legal/terms", label: "Terms of Service" },
            { to: "/legal/privacy", label: "Privacy Policy" },
            { to: "/legal/acceptable-use", label: "Acceptable Use & Reporting" },
          ].map(({ to, label }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `inline-flex min-h-11 items-center border-b-2 font-body text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red ${isActive ? "border-hero-red text-ink-black" : "border-transparent text-ink-muted hover:border-ink-black/30 hover:text-ink-black"}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <article className="mx-auto max-w-[70ch]">
        <h1 className="font-display text-[2.4rem] font-black uppercase leading-[0.95] tracking-[-0.03em] text-ink-black sm:text-[3rem]">
          {title}
        </h1>
        <p className="mt-4 font-body text-sm text-ink-muted">
          Last updated: {updated}
        </p>

        <div className="mt-10 break-words font-body text-base leading-7 text-ink-muted [&_h2]:mb-3 [&_h2]:mt-10 [&_h2]:font-display [&_h2]:text-xl [&_h2]:font-bold [&_h2]:leading-tight [&_h2]:tracking-tight [&_h2]:text-ink-black [&_p]:mb-4 [&_ul]:mb-5 [&_ul]:list-disc [&_ul]:pl-6 [&_li]:mb-2 [&_strong]:font-semibold [&_strong]:text-ink-black [&_a]:text-ink-black [&_a]:underline [&_a]:underline-offset-4 [&_a:hover]:text-hero-red [&_a:focus-visible]:outline [&_a:focus-visible]:outline-hero-red">
          {children}
        </div>

        </article>
        <footer className="mt-16 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-ink-black/20 pt-6 font-body text-sm text-ink-muted">
          © 2026 {branding.product_name} ·{" "}
          <a className="break-all py-2 underline underline-offset-4 hover:text-hero-red" href={`mailto:${branding.legal_email}`}>
            {branding.legal_email}
          </a>
        </footer>
      </main>
    </div>
  );
}
