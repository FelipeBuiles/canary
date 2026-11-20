# Lettering editor

On an editable (hybrid) edition, the user opens a drawn page's lettering in the Pages room, then moves, resizes and restyles balloons and captions over the base art and saves. Saves are revision-checked and invalidate Finish, not Draw. On integrated or baked editions, the lettering is part of the artwork and cannot be edited.

## Sub-features

- `lettering-open` shows the page on `Lettering page canvas` with `Lettering controls`.
- `lettering-edit` moves (`Move balloon tail`), resizes (`Resize selected lettering`), rotates (`Rotation`) and changes the font (`Font`) of a selected element.
- `lettering-save` bumps the stored lettering revision, and a reload shows the edit.
- `lettering-conflict` rejects a save made against a stale revision instead of overwriting.
- `lettering-integrated` shows "Lettering is part of this artwork" with no editable canvas.

## How to get to it (user POV)

- Open the Pages room, choose a drawn page from the `Page gallery`, and choose `Lettering`.
- Open the Book room and use `Design the book lettering` for the book-wide style.

## Driving it with playwright-cli

Preconditions:

- Signed in as the test account, which owns a hybrid project with at least one drawn page in part `<part>`.
- Only read unless that project is disposable and belongs to the test account. Saving changes that project's real lettering state.

- **Before state.** Run `bin/api.sh canary-verify /api/projects/<id>/parts/<part>/pages/<n>/lettering` and save it to `$EV/lettering-before.json`. Note its revision.
- **Open.** Run `$PW goto http://127.0.0.1:5173/project/<id>/pages`, choose the page in `Page gallery`, then choose `Lettering`. `$PW find "Lettering page canvas"` resolves. Save `$EV/lettering-open.png`.
- **Edit and save** (disposable project only). Select a balloon, change `Font` or `Scale`, and save. Save `$EV/lettering-after.png`.
- **Stored state.** Fetch the lettering again into `$EV/lettering-after.json`. The revision has increased and the changed field holds the new value. Run `$PW reload`, reopen the page, and confirm the edit is still there.
- **Finish invalidation.** Fetch `/api/projects/<id>/parts/<part>/status`. Finish is stale or pending, and Draw is unchanged.
- **Integrated edition.** On an integrated or baked project, the editor shows "Lettering is part of this artwork" and no canvas.

## Gotchas

- A successful export is not visual review (AGENTS.md). Screenshots of the canvas are the visual proof, and they show placement, not image quality.
- Never trigger a redraw from this room to get a drawn page. In paid mode it spends money, and it never applies to a baked edition.
- With no drawn hybrid page on the test account, report `lettering-*` as not verified, with that reason.
