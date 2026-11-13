# Free-offer pilot: rollout checklist

**Status: Proposed.** Written 2026-11-12. Everything below is built and
passes the provider-free checks, but none of it has run in production,
against a real database, or against live Stripe, Supabase Auth or Cloudflare.
All of it is off until the settings in section 3 are stored. Behavior is
documented in [stage contracts](../reference/stage-contracts.md) ("Cold Open",
"Canary-paid work", "First-chapter grant").

The pilot plan and its reasoning: `marketing/intel/reports/2026-11-10-free-credits-and-first-50.md`.

## 1. What the pilot does

1. A new account with no credits uploads a first chapter. Canary pays for
   Extract and the Brief it chains, then prints the Cold Open: the opening in
   three looks.
2. An author who has a printed opening may verify a card and receive credits
   for a first chapter. One grant per card and per account.
3. A grant holder's first purchase gets bonus credits.

## 2. One-time setup, outside the code

Do these first. Nothing in section 3 works without them.

- [ ] **Database.** Apply `docs/migrations/2026-11-12-card-chapter-grant.sql`
      to the production Supabase project. It has never been run; try it on a
      scratch project or branch first.
- [ ] **Database: live settings.** Apply
      `docs/migrations/2026-11-12-app-settings.sql` the same way. It creates
      `app_settings`, where the pilot settings in section 3 are stored. It has
      never been run either. Without it Backoffice → Environment → Live
      settings is read-only and the pilot settings cannot reach production:
      they are not declared in `deploy/lightsail/config_schema.json` or
      `compose.yaml`, so host environment values for them are not passed to
      the app.
- [ ] **Supabase Auth: email confirmation.** Confirm "Confirm email" is on.
      The free opening treats a signed-in email as verified on that basis.
- [ ] **Cloudflare Turnstile.** Create a site for the app's domain. Keep the
      site key and the secret key.
- [ ] **Supabase Auth: CAPTCHA.** Enable CAPTCHA protection with provider
      Turnstile and the secret key. Store the site key (section 3) first and
      check that the sign-in page shows the bot check: once Supabase's
      protection is on, a page without the key cannot sign anyone in by email.
- [ ] **Stripe webhook.** The existing endpoint already receives
      `checkout.session.completed`, which is the event the card check sends.
      Confirm that event is still selected.
- [ ] **Stripe Radar.** Confirm Radar evaluates card setups (SetupIntents) on
      the account, and review the rules for card testing.
- [ ] **Provider budget alerts.** One on Google Cloud and one on Runware, at
      50% and 80% of each grant. These are the only limits that do not depend
      on Canary's own code.
- [ ] **Projects volume.** The spend ledger and the free-opening claims are
      files on the projects volume (`.sponsored_spend.json`,
      `.free_opening_claims.json`). If more than one server runs, they must
      share that volume. Include both files in backups.

## 3. Settings

Two places. The first table is the host environment, changed as usual
through Backoffice → Environment or `./scripts/prod-env` (an apply restarts the
app). The second is Backoffice → Environment → **Live settings**
(`runtime_settings.py`, stored in `app_settings`): a saved value applies on
that server at once and on any other within a minute, with no restart or
build. A stored value wins over the environment; "Remove" returns to the
environment value or the default. Values are checked against each setting's
bounds before they are stored. If the table cannot be read and never has been
since the server started, the free Extract, the card grant and the purchase
bonus stay off until it can be; after a first read, the last values stay in
force.

Host environment: nothing to change. `PULP_MODEL_COST_MARKUP` is fixed at 2.0 in
`deploy/lightsail/compose.yaml`, so a 1,200-credit grant costs about US$6 of
provider credit.

`RUNWARE_API_KEY` must be in the host secret bundle. The two Runware switches
are still declared in the host configuration (default `false`); the stored
value wins, so leave the host values alone.

`CANARY_SPONSORED_GRANT_ROUTES_ONLY` (on in production) and
`CANARY_RATE_LIMIT_CARD_GRANT` (`3/hour`) are environment-only and need no
change; Live settings shows them read-only.

Live settings:

| Setting | Pilot value | What it does |
| --- | --- | --- |
| `CANARY_RUNWARE_FIRST_ENABLED` | `true` | New image work starts on the Runware grant. Required: without it every free page fails. Store this before anything else. |
| `CANARY_RUNWARE_TEXT_FALLBACK_ENABLED` | `true` | Vertex 429s move to Runware. Both are grant routes. |
| `CANARY_IMAGE_CASH_ROUTES_DISABLED` | `true` | No image, free or paid, falls back to OpenAI or FAL. It fails instead. This is the "fallbacks off" switch for the pilot. |
| `CANARY_FREE_OPENING_MAX_CHARS` | `20000` | Longest first upload read free (about 3,000 words). Unset = no free Extract. |
| `CANARY_COLD_OPEN_PER_ACCOUNT` | unset (1) | One free opening per account. `0` is the kill switch for the free Extract and the Cold Open. |
| `CANARY_SPONSORED_DAILY_USD` | unset (10) | Daily ceiling on free work, all accounts, UTC day. |
| `CANARY_FREE_OPENING_PER_IP_DAILY` | unset (2) | New free openings per visitor address per day. |
| `CANARY_DISPOSABLE_EMAIL_DOMAINS` | optional | Extra throwaway domains, comma-separated. |
| `CANARY_CARD_GRANT_CREDITS` | `1200` | Turns the first-chapter grant on. Needs the migration. |
| `CANARY_CARD_GRANT_SEATS` | unset (100) | Total grants. |
| `CANARY_CARD_GRANT_ENDS` | `2026-12-22` | No claim from this UTC date. A mistyped value closes the offer. |
| `CANARY_CARD_GRANT_EXPIRY_DAYS` | unset (30) | Unspent grant credits are taken back after this. |
| `CANARY_FIRST_PURCHASE_BONUS_PERCENT` | `50` | Bonus on a grant holder's first purchase while the grant is unexpired. Unset = none. |
| `CANARY_TURNSTILE_SITE_KEY` | the Turnstile site key | Shows the bot check on sign-up, sign-in and password reset. The page reads it from `/api/public-config`; no web build is needed. |

## 4. Verify before announcing

Use Stripe test mode and a throwaway account. Write down each cost.

- [ ] Sign up with email: the bot check appears, and the confirmation email arrives.
- [ ] Sign in and reset a password with the bot check on.
- [ ] Upload a chapter under the length limit with zero credits. The Extract
      estimate shows 0 credits, Extract and Brief complete, and three Cold
      Open pages print.
- [ ] Record the provider cost of that run (`.sponsored_spend.json` on the
      volume, and the Cold Open record's `provider_cost_usd`). The plan
      assumed under US$0.50; this is the first measurement.
- [ ] A second account with the same Gmail address plus a `+tag`, and a second
      account with the same chapter, are both asked for credits.
- [ ] The credits page shows "Your first chapter is on us". Verify with
      Stripe's test card: 1,200 credits arrive and the ledger shows the grant.
- [ ] The same test card on a second account is refused.
- [ ] Buy a pack on the granted account: the bonus row appears once.
- [ ] Stop Runware (or use a bad key in staging): an image fails with a clear
      error and nothing is submitted to OpenAI or FAL.
- [ ] In PostHog, find `free_opening_granted`, `cold_open_printed`,
      `card_grant_started`, `card_grant_claimed` and
      `first_purchase_bonus_granted`.
- [ ] When a first upload is quoted a price, `free_opening_refused` says why:
      `reason` is `too_long`, `no_text`, `daily_budget`, `account_used`,
      `email_unverified`, `email_disposable`, `email_already_used`,
      `opening_already_drawn`, `address_limit` or `error`; `at` says whether
      the estimate or the run was refused. One event per project and reason
      per server process.

## 5. Decisions and copy that need the owner

- [x] **Claims policy.** Updated 2026-11-12: `marketing/knowledge/claims-policy.md`
      ("Free offer") and `showcase/marketing/copy-kit.md` now allow the offer
      to be named with its conditions, once it is on and verified.
- [ ] **Privacy policy.** `web/src/pages/legal/PrivacyPage.tsx` now describes
      the free-offer fingerprints, card verification and the bot check. Read
      it and adjust the wording; it has not had a legal review.
- [x] **Terms.** Section 6 now says purchased credits do not expire and
      promotional credits are one per person and card, expire, and can be
      withdrawn. Not legally reviewed.
- [x] **Expiry wording.** Sign-up, credits page and landing copy (English,
      Spanish, French) now say "purchased credits" never expire.
- [ ] **Marketing facts.** `marketing/knowledge/facts.yaml` has no fact for
      the free offer yet; add one through the `product-facts` workflow before
      a draft cites it.

## 6. During the pilot

- Kill switches, in Live settings, effective within a minute and without a
  restart: `CANARY_COLD_OPEN_PER_ACCOUNT=0` stops free openings;
  `CANARY_CARD_GRANT_SEATS=0` stops new grants.
- A refused free opening is silent: the author sees the normal credit prompt.
  The reason is in the server log (`Free opening refused ... reason=`).
- The daily ceiling is checked when work is admitted. One day can exceed it
  by the job that was running when it was reached.
- Grant expiry runs when an account's balance is read, not on a timer.

## 7. When the pilot ends

- [ ] Leave `CANARY_CARD_GRANT_CREDITS` set until 30 days after the last
      claim, or set `CANARY_CARD_GRANT_EXPIRE` to `true`. Otherwise issued grants are
      never taken back.
- [ ] Unset `CANARY_IMAGE_CASH_ROUTES_DISABLED` only if paid work should fall
      back to OpenAI and FAL again.
- [ ] Remove the Turnstile site key only together with Supabase's CAPTCHA
      setting.

## 8. Known gaps

- The SQL functions, the `app_settings` table and the Stripe setup flow are
  covered only by tests with fakes. That includes how a missing table is
  recognized (PostgREST `PGRST205`).
- Live settings are protected by the operator token alone. Each setting has a
  fixed upper bound (for example 10,000 grant credits, US$200 a day) that a
  stored value cannot exceed.
- The throwaway-email list is about 55 domains.
- Google sign-in is not covered by the bot check.
- First-purchase bonus credits do not expire.
- No operator screen shows the day's free spend or the claims; they are files
  and log lines.
