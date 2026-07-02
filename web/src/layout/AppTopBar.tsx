import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { useCreditBalance } from "../api/queries";
import { useAuth } from "../hooks/useAuth";
import { useCountUp } from "../hooks/useCountUp";
import { useTopBarSlotRegister } from "./TopBarSlot";
import { cn } from "../lib/cn";
import { BrandMark } from "../components/BrandMark";

function initials(email?: string | null) {
  if (!email) return "JP";
  const name = email.split("@")[0] || email;
  return name.slice(0, 2).toUpperCase();
}

export function AppTopBar() {
  const location = useLocation();
  const { user } = useAuth();
  const { data: balance } = useCreditBalance();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const registerSlot = useTopBarSlotRegister();

  const credits = balance?.balance_credits ?? 0;
  // Top-ups count up over ~600ms; spends snap instantly (see useCountUp).
  const displayCredits = useCountUp(credits);
  const isLow = credits < 150;
  const inProject = location.pathname.startsWith("/project/");
  const studioName = String(user?.user_metadata?.studio_name || "Inkwell Studio");
  const email = user?.email ?? "hello@scenewright.ink";

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    }
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <header
      className={cn(
        "relative z-40 flex shrink-0 items-stretch border-b-[2px] border-ink-black bg-bristol text-ink-black",
        inProject ? "h-[4.5rem]" : "h-14",
      )}
    >
      {inProject ? (
        // In a project the sidebar owns identity; this row belongs to the
        // room header, which portals its content into the slot below.
        <div
          ref={registerSlot}
          className="flex min-w-0 flex-1 items-stretch"
        />
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-4 px-4">
          <Link to="/" className="flex items-center gap-2.5">
            <BrandMark className="h-7 w-7 shrink-0" />
            <span className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
              Scenewright
            </span>
            <span className="bg-hero-red px-2.5 py-1 font-meta text-[0.54rem] font-bold tracking-[0.16em] text-bristol">
              BETA
            </span>
          </Link>
          <span className="h-5 w-px bg-ink-black/14" />
          <Link
            to="/labs"
            className={cn(
              "font-meta text-[0.62rem] font-bold uppercase tracking-[0.16em] hover:text-hero-red",
              location.pathname.startsWith("/labs") ? "text-ink-black" : "text-ink-black/62",
            )}
          >
            Labs
          </Link>
        </div>
      )}

      <div className="flex shrink-0 items-center gap-3 pl-3 pr-4">
        <Link
          to="/credits"
          className={cn(
            "hidden h-8 items-center gap-2 border px-3 font-meta text-[0.62rem] font-bold tracking-[0.08em] sm:flex",
            isLow
              ? "border-narrator-gold/60 bg-chip-gold text-warn-orange"
              : "border-ink-black/8 bg-surface-container text-ink-black/76",
          )}
          aria-label={isLow ? "Credits low — top up" : `Credits: ${credits}`}
        >
          <span>◆</span>
          <span className="tabular-nums">{displayCredits.toLocaleString()}</span>
          <span className="text-ink-black/42">credits{isLow ? " · top up" : ""}</span>
        </Link>

        <div ref={menuRef} className="relative flex items-center">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label="Account menu"
            className="flex h-9 w-9 items-center justify-center bg-hero-red font-meta text-[0.72rem] font-bold tracking-[0.08em] text-bristol"
          >
            {initials(email)}
          </button>
          {open && (
            <div className="absolute right-0 top-[calc(100%+8px)] w-[290px] border-[3px] border-ink-black bg-bristol shadow-paper-sm">
              <div className="p-5">
                <div className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.04em]">
                  {email.split("@")[0].replace(/[._-]+/g, " ")}
                </div>
                <div className="mt-1 truncate font-body text-[0.82rem] font-semibold text-ink-black/52">
                  {email}
                </div>
                <div className="mt-4 flex items-center gap-2 font-body text-[0.78rem] font-semibold text-ink-black/54">
                  Studio:
                  <span className="bg-ink-black px-3 py-1 font-meta text-[0.56rem] uppercase tracking-[0.16em] text-bristol">
                    {studioName}
                  </span>
                </div>
              </div>
              {[
                ["Account", "/account", "⊙"],
                ["Credits & Billing", "/credits", "◆"],
              ].map(([label, to, mark]) => (
                <Link
                  key={label}
                  to={to}
                  onClick={() => setOpen(false)}
                  className="flex min-h-12 items-center gap-4 border-t border-ink-black/10 px-5 font-body text-[0.88rem] font-bold tracking-[0.04em] hover:bg-surface-container"
                >
                  <span className="font-meta text-[0.62rem] text-ink-black/38">{mark}</span>
                  {label}
                </Link>
              ))}
              <button
                type="button"
                onClick={() => supabase.auth.signOut()}
                className="flex min-h-12 w-full items-center gap-4 border-t border-ink-black/10 px-5 text-left font-body text-[0.88rem] font-bold tracking-[0.04em] text-hero-red hover:bg-chip-red/40"
              >
                <span className="font-meta text-[0.62rem]">→</span>
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
