import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useCreditBalance } from "../api/queries";
import { signOut, useAuth } from "../hooks/useAuth";
import { useCountUp } from "../hooks/useCountUp";
import { useTopBarSlotRegister } from "./TopBarSlot";
import { cn } from "../lib/cn";
import { CreditAmount, CreditMark } from "../components/ui/CreditAmount";
import { BrandIdentity } from "../components/BrandIdentity";

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
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const menuRef = useRef<HTMLDivElement | null>(null);
  const registerSlot = useTopBarSlotRegister();

  const credits = balance?.balance_credits ?? 0;
  // Top-ups count up over ~600ms; spends snap instantly (see useCountUp).
  const displayCredits = useCountUp(credits);
  const isLow = credits < 150;
  const inProject = location.pathname.startsWith("/project/");
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
        "relative z-40 shrink-0 items-stretch border-b border-ink-black/12 bg-bristol text-ink-black",
        // Phones share one compact project/navigation/account row.
        // Desktop keeps the full room masthead beside the project sidebar.
        inProject ? "flex h-14 studio-desktop:h-shell-top" : "flex h-14",
      )}
    >
      {inProject ? (
        // Phone navigation and desktop room headers share this shell slot.
        <div
          ref={registerSlot}
          className="flex min-w-0 flex-1 items-stretch"
        />
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-4 px-4">
          <Link to="/" className="flex items-center gap-2.5">
            <BrandIdentity />
          </Link>
        </div>
      )}

      <div className="flex shrink-0 items-center gap-2 pl-3 pr-4 studio-desktop:pr-5">
        <Link
          to="/credits"
          className={cn(
            "hidden h-8 items-center gap-2 border px-2.5 font-meta text-xs font-semibold transition-colors sm:flex",
            isLow
              ? "border-ink-black bg-narrator-gold text-ink-black"
              : "border-ink-black/12 text-ink-black hover:border-ink-black/55 hover:bg-sidebar-tint",
          )}
          aria-label={isLow ? "Credits low — top up" : `Credits: ${credits}`}
        >
          <CreditAmount value={displayCredits} showMark showLabel={false} className="tabular-nums" />
          {isLow && <span className="text-ink-muted">· top up</span>}
        </Link>

        <div ref={menuRef} className="relative flex items-center">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label="Account menu"
            className="flex size-8 items-center justify-center bg-ink-black font-meta text-[0.6875rem] font-semibold tracking-[0.04em] text-pulp-paper transition-colors duration-150 hover:bg-hero-red"
          >
            {initials(email)}
          </button>
          {open && (
            <div className="absolute right-0 top-[calc(100%+8px)] w-[272px] border border-ink-black/12 bg-bristol shadow-float">
              <div className="p-5">
                <div className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.04em]">
                  {email.split("@")[0].replace(/[._-]+/g, " ")}
                </div>
                <div className="mt-1 truncate font-body text-[0.82rem] font-semibold text-ink-black/52">
                  {email}
                </div>
              </div>
              {[
                ["Account", "/account", "account"],
                ["Credits & Billing", "/credits", "credits"],
              ].map(([label, to, mark]) => (
                <Link
                  key={label}
                  to={to}
                  onClick={() => setOpen(false)}
                  className="flex min-h-12 items-center gap-4 border-t border-ink-black/10 px-5 font-body text-[0.88rem] font-bold tracking-[0.04em] hover:bg-surface-container"
                >
                  <span className="font-meta text-[0.62rem] text-ink-black/38">
                    {mark === "credits" ? <CreditMark /> : "⊙"}
                  </span>
                  {label}
                </Link>
              ))}
              <button
                type="button"
                disabled={signingOut}
                onClick={() => {
                  setSigningOut(true);
                  setSignOutError("");
                  void signOut().then(result => {
                    if (result.error) setSignOutError(result.error.message);
                  }).catch(error => setSignOutError(error instanceof Error ? error.message : "Sign out could not be completed. Try again."))
                    .finally(() => setSigningOut(false));
                }}
                className="flex min-h-12 w-full items-center gap-4 border-t border-ink-black/10 px-5 text-left font-body text-[0.88rem] font-bold tracking-[0.04em] text-hero-red hover:bg-chip-red/40"
              >
                <span className="font-meta text-[0.62rem]">→</span>
                {signingOut ? "Signing Out…" : "Sign Out"}
              </button>
              {signOutError && <p role="alert" className="px-5 pb-4 font-body text-sm text-hero-red">{signOutError}</p>}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
