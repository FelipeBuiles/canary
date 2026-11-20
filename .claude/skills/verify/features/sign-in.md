# Sign in

A returning user signs in with email and password at `/login`. Canary redirects them away from the login page, and authenticated API calls then succeed for their account.

## Sub-features

- `signin-form` accepts email and password and submits.
- `signin-redirect` leaves `/login` for the signed-in destination (the Library by default, or the `?next`/sample destination).
- `signin-session` gives the SPA a Supabase session that authenticates `/api/*` calls.
- `signin-error` shows an error for a wrong password and stays on `/login`.

## How to get to it (user POV)

- Open `http://127.0.0.1:5173/login` directly.
- Open a signed-in route such as `/credits` while signed out, which leads to the login page.
- Google sign-in exists, but this map does not cover it: it needs an interactive OAuth flow.

## Driving it with playwright-cli

Preconditions:

- `doctor.sh` exits 0 and reports no Turnstile key and both test credentials set.

- **Sign in.** Run `.claude/skills/verify/bin/signin.sh "$EV"`. It fills the form named `Sign in` (labels `Email` and `Password`), submits it, and waits for the URL to leave `/login`. It prints the landing path and saves `$EV/after-signin.png`.
- **Session reaches the API.** Run `bin/api.sh canary-verify /api/credits/balance`. It prints HTTP 200 signed_in=True JSON for the test account.
- **Wrong password.** In a fresh session (`$PW -s=canary-verify-neg open http://127.0.0.1:5173/login`), fill `Email` with the test address and `Password` with a wrong value, then submit. An error appears, the URL stays `/login`, and `$EV/signin-error.png` shows it. `bin/cleanup.sh` closes `canary-verify-neg`.

## Gotchas

- When Turnstile is configured (the doctor warns), scripted sign-in fails. Use the headed sign-in and `state-save` path in SKILL.md, and record which path you used.
- This is production Supabase. Repeated wrong-password attempts can rate-limit the test account, so run `signin-error` once per verification at most.
- Never use the `Create account` tab. Sign-up creates a production user and sends email.
