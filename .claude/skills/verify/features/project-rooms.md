# Project rooms

A project opens into rooms: Story (Extract and Brief), Styles, Cast, Pages, Book, and Settings. Each room shows its stage's state and gates actions on that state. For example, nothing after Style can generate until a style is selected.

## Sub-features

- `rooms-nav` moves between rooms, and each room route renders.
- `rooms-status` makes room contents agree with `GET /api/projects/:id/status` and `GET /api/projects/:id/parts/:part/status`.
- `rooms-style-gate` blocks post-style generation in the UI while the status reports `style_selected: false`.
- `rooms-fallback` sends an unknown room path (`/project/:id/whatever`) to a valid room.

## How to get to it (user POV)

- Open a project from the Library.
- Go directly to `/project/<id>/{story,styles,cast,pages,book,settings}`.

## Driving it with playwright-cli

Preconditions:

- Signed in as the test account, which owns at least one project. Use its id from `projects.json` ([Library](./library.md)).

- **Status.** Run `bin/api.sh canary-verify /api/projects/<id>/status` and save it to `$EV/status.json`. Note `style_selected` and each stage's state.
- **Each room.** For each room in `story styles cast pages book settings`, run `$PW goto http://127.0.0.1:5173/project/<id>/<room>` and `$PW snapshot`, then save `$PW screenshot --filename="$EV/room-<room>.png"`. Every room renders without an error boundary or 404, and the snapshot's room content matches the stage states in `status.json`.
- **Style gate.** When `style_selected` is false, open `cast` and `pages`. Their generate actions are disabled or point the user to Styles.
- **Fallback.** Run `$PW goto http://127.0.0.1:5173/project/<id>/nope`. The browser lands on a real room route.
- **Pages room handles.** On `pages`, `$PW find "Page gallery"` and `$PW find "Drawing progress"` resolve when the part has pages.

## Gotchas

- Do not choose Run, Approve, Draw, Redraw or any button that shows a `~N credits` estimate, unless the doctor reports `model_mode=mock` and the project's `config.yaml` has `mock_mode: true`. Server orchestration auto-chains from there, so one click can spend across several stages.
- A project is a series of parts. Story, Pages and Book are per part, while Styles and Cast belong to the series. Read the part id from the status before calling part routes.
- A `pipeline_contract` other than `eight-stage-v2` in the doctor means the backend is stale. Ask the user to restart it instead of debugging the rooms.
