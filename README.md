# Canary

Canary turns prose fiction into finished comic books. An author uploads a
manuscript (`.txt`, `.epub` or `.pdf`). Canary reads it, proposes a story
brief, a visual style and a cast, adapts the story into a page plan, and
draws complete, lettered comic pages. The author approves each step and then
exports a print-ready PDF or CBZ.

It's for writers, indie authors and small studios who want their story as a
comic without hiring an art team.

> **A personal learning project.** I build Canary on my own to learn how to
> run a real SaaS from start to finish: billing, credit metering, provider
> costs and fallbacks, deployment, secrets, observability, backups and support.
> A live instance runs at [scenewright.ink](https://scenewright.ink) under the
> name *Scenewright*. I use it to try things out, and it may change, break or be
> reset without notice. This repository is the code behind it, shared under the
> [Apache 2.0 license](LICENSE).

## How it works

Every manuscript goes through an eight-stage pipeline. Each stage can be
resumed and keeps its own artifacts on disk:

```
extract → brief → style → cast → adapt → plan → draw → finish
```

| Stage | What it does |
|---|---|
| **extract** | Splits the manuscript into stable source units and scenes |
| **brief** | Summarizes the story, its tone and its key beats *(checkpoint)* |
| **style** | Generates style proofs to choose a visual look from *(checkpoint)* |
| **cast** | Builds model sheets and per-state references for each character *(checkpoint)* |
| **adapt** | Adapts the whole book into a comic script and accounts for every source unit |
| **plan** | Turns the script into page plans: panels, entities, states and lettering |
| **draw** | Generates each complete comic page, consistent with style and cast *(checkpoint)* |
| **finish** | Runs preflight checks, final lettering and PDF/CBZ export |

The web studio shows these stages as four rooms: **Story → Look → Pages →
Book**. The author makes the decisions at the checkpoints. Adapt and Plan run
automatically and stay open for inspection. A project can be a series of
parts that share a style, a cast and a Story Bible.

Every piece of generation is estimated and billed in credits, so the author
sees `~N credits` before spending anything.

## Built with

- **Backend:** Python 3.12, FastAPI, Pydantic, Procrastinate (Postgres job
  queue), Pillow, pypdf/ebooklib, Playwright
- **Frontend:** React 19, TypeScript, Vite, Vitest
- **Model gateway:** [LiteLLM](https://github.com/BerriAI/litellm) with custom
  handlers in `litellm_handlers/`. It routes text and image calls to hosted
  providers (Vertex AI Gemini, OpenAI, FAL, Runware), with model aliases and
  pricing kept in configuration.
- **Platform:** Supabase (auth and data), Stripe (credit top-ups), PostHog
  (product analytics and AI observability), Docker Compose, AWS Lightsail

Canary is an *application* that calls hosted models. It doesn't train,
fine-tune or serve models.

## Repository layout

```
novel_to_comic/    Python package: pipeline stages, FastAPI server, CLI, tests,
                   and the shared lettering layout/SVG engine (lettering/engine.mjs)
web/               React studio (rooms live in web/src/pages/rooms/)
litellm/           Gateway configuration
litellm_handlers/  Custom gateway handlers (multimodal serialization, routing)
scripts/           Dev launcher, checks, deploy and ops tooling
docs/              ADRs, stage contracts, reference docs, plans and proposals
```

To find your way around, start with [CONTEXT.md](CONTEXT.md) (the domain
vocabulary), [docs/README.md](docs/README.md) (the documentation map) and
[docs/adr/](docs/adr/) (the architecture decisions).

## Running it locally

**Prerequisites:** Python 3.12, [uv](https://docs.astral.sh/uv/), Node 24,
and Docker (for the LiteLLM gateway and its Postgres).

```bash
git clone https://github.com/FelipeBuiles/canary.git
cd canary
cp .env.example .env            # fill in your own keys; see comments in the file
cp web/.env.example web/.env

uv sync --project novel_to_comic --locked --extra web --extra dev
uv sync --project litellm --locked
(cd web && npm ci)
```

Start the full stack (backend on :8000, studio on :5173, gateway on :4000):

```bash
./scripts/dev.sh
```

Real generation calls paid model providers and needs your own API keys in
`.env`. To try the studio for free, use the local replay service with a
project you've already finished:

```bash
./scripts/dev.sh --mock --fixture projects/<your-completed-project>
```

Run `./scripts/dev.sh --help` for all options. The CLI itself has only two
commands, `pipeline init` and `pipeline serve`. Everything else (running
stages, approvals, status, corrections, export) goes through the HTTP API
that the studio uses.

## Tests and checks

```bash
python3 scripts/check_release.py backend   # Ruff + provider-free backend suite
(cd web && npm test && npm run lint && npm run build)
./scripts/check_all.sh                     # full local gate (also the pre-push hook)
```

None of the tests call a paid provider.

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## License

[Apache License 2.0](LICENSE) © 2026 Juan Felipe Builes. "Scenewright" is the
name of my hosted instance. The license does not grant any rights to use it as
a trademark (see section 6).
