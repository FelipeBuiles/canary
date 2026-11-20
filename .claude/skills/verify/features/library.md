# Library

The signed-in home at `/` lists the account's productions, lets the user filter them, and leads into each project's rooms. A new account sees the first-comic onboarding instead.

## Sub-features

- `library-list` shows one entry for each project that `GET /api/projects` returns.
- `library-filter` narrows the list with the `Show` button group.
- `library-open` opens a project into its default room under `/project/:id/`.
- `library-empty` shows the "Your first comic starts here" onboarding to an account with no projects.

## How to get to it (user POV)

- Sign in, which lands on `/`.
- Choose the Canary logo or "Back to home" from any room.

## Driving it with playwright-cli

Preconditions:

- Signed in as the test account ([Sign in](./sign-in.md)).

- **List.** Run `$PW goto http://127.0.0.1:5173/` and then `$PW snapshot`. Heading `#library-title` is visible. Save `$PW screenshot --filename="$EV/library.png"`.
- **Cross-check.** Run `bin/api.sh canary-verify /api/projects` and save its output to `$EV/projects.json`. Each project's display name in the JSON appears in the snapshot, and nothing else does.
- **Filter.** Find the group `Show` (`$PW find "Show"`) and choose each option. The visible entries change to match, and a screenshot is saved for each option.
- **Open.** Choose a project entry. The URL becomes `/project/<id>/<room>`, and the `<id>` is in `projects.json`.

## Gotchas

- An account with no projects shows onboarding, not the list. That proves `library-empty` only. Report `library-list` as not verified until the test account owns a project.
- `New production` starts the wizard, and finishing it creates a project in production Supabase. Do not finish it unless the journey needs a project, and record any project you create.
