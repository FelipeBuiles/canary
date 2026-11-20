# Canary verification map

The maintained source for proving Canary's user-facing behavior in the real app. Read this index first, then use the matching feature file as the recipe.

## Baseline preconditions

- The user has started the stack, ideally with `./scripts/dev.sh --mock`. This skill never starts it.
- `.claude/skills/verify/bin/doctor.sh` exits 0. Note its `model_mode`.
- `CANARY_VERIFY_EMAIL` / `CANARY_VERIFY_PASSWORD` name a dedicated test account in the production Supabase project.
- The browser session is `canary-verify` (`export PLAYWRIGHT_CLI_SESSION=canary-verify`), and commands run from the repo root with `PW=node_modules/.bin/playwright-cli`.

## Driving conventions

- Navigate by route path, and find elements by accessible name with `$PW find` / `$PW snapshot`. Never use coordinates.
- Outside `model_mode=mock`, only read. Never confirm a credit estimate, run a stage, draw, redraw, translate, publish, or buy credits.
- Mutations run only on a project owned by the test account. Generation also needs that project to have `mock_mode: true`.
- Save evidence under `tmp/verify/<UTC timestamp>-<feature>/`.

## Proof and skip reporting

- Capture the action and the resulting state: a screenshot before, a screenshot after, and the API JSON showing the stored result.
- Pair each UI claim with an API read (status, pages, lettering revision) that confirms it.
- When a precondition is missing, for example the test account has no project or no drawn page, report the journey as **not verified** with the reason. Never weaken the journey to pass.
- Do not report an entry point as verified because a different path to the same feature worked.

## Features

- [Sign in](./sign-in.md): the email and password form, the redirect, and the session reaching the API.
- [Library](./library.md): the signed-in home that lists the account's productions.
- [Project rooms](./project-rooms.md): Story, Styles, Cast, Pages, Book and Settings for one project, checked against the status API.
- [Public reading](./public-reading.md): the samples page and the `/read/:id` reader, without signing in.
- [Lettering editor](./lettering-editor.md): editable lettering on a drawn page, with revision-checked saves.
