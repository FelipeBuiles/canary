# Model settings

**Status: Current, September 28, 2026.** Implementation, gateway configuration,
and tests are authoritative.

## Production operator defaults

Open **Backoffice → Stage models** and connect with `CANARY_OPS_TOKEN` to set the
model used for each model-bearing stage. The same settings are available through
`GET` and `PATCH /api/ops/backoffice/models`. PATCH accepts a partial
`{"selections": {"adapt": "gpt-6-sol"}}` mapping. The API validates every
stage/model pair against the production catalog and rejects Codex choices.
Finish packages the book and has no separate model.

Operator defaults are stored atomically in
`<projects_dir>/.operator-model-settings.json`. New job configuration snapshots
for every account and project read them in development and production. A change
does not mutate a running job or rebind an existing Draw edition; a changed Draw
model needs a new edition or project. The operator token is never embedded in
the production browser bundle. Production backoffice settings require the same
operator connection used by its other views.

| Stage setting | Default | Work |
|---|---|---|
| Extract | GPT-6 Luna | Manuscript analysis |
| Brief | GPT-6 Luna | Creative direction |
| Style/Cast text | GPT-6 Luna | Visual briefs and asset instructions |
| Style/Cast images | Sunburst on FAL | Style, cast, and cover art |
| Adapt | GPT-6 Sol | Script and dialogue |
| Plan | GPT-6 Sol | Pages and panels |
| Draw | Sunburst on OpenAI, FAL backup | Complete page art |
| Lettering checks | GPT-6 Luna | OCR and canonical copy checks |
| Visual review | GPT-6 Luna | Visual consistency checks |

Text and vision choices are `gpt-6-sol`, `gpt-6-luna`,
`claude-opus-5-5`, `claude-sonnet-5-5`, `mimo-v2.6-pro`, and
`deepseek-v4.1-flash`.
Image and Draw choices are `image-sunburst` only. The gateway maps the text
choices to OpenAI, Anthropic, OpenRouter/Xiaomi, and Together AI respectively.
`image-sunburst` runs on OpenAI first with one FAL attempt as backup, for
Style/Cast images and Draw pages alike; model pickers label it "OpenAI, FAL
backup". There is no route-priority setting.
New Draw editions render pages at medium quality; Style/Cast images use
`image_quality` (default medium). Set an Admin-scoped `FAL_ADMIN_KEY` on the
gateway so Sunburst images settle at FAL's billed charge; without it they settle
at a labelled request estimate (see [stage contracts](stage-contracts.md)).
`novel_to_comic/src/novel_to_comic/text_models.py` lists the selectable text aliases and the
request fields each accepts; every alias needs a gateway route and a pricing
alias. Reasoning text routes run at low effort: GPT-6 routes set
`reasoning_effort: low` on the gateway, and Claude routes send
`output_config.effort: low` from `text_models.py`. The DeepSeek route turns off Together's default thinking with
`extra_body.reasoning.enabled: false`. The pinned gateway drops a route-level
`reasoning_effort` for this model. The OpenAI model pages publish the
standard text rates per million tokens: [Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)
$2 input / $0.20 cached input / $10 output, and
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
$0.10 input / $0.01 cached input / $0.50 output. Canary records these in its
pricing overrides; provider-reported cost remains authoritative for settlement.
Provider keys belong in the gateway environment.

## Project configuration

`pipeline init` writes `config.yaml` with project-owned choices such as language,
lettering mode, style template, generation concurrency, and pipeline limits. It
does not write provider routes, API credentials, or stage model defaults. The
server overlays operator defaults when it creates a job snapshot. Existing
project files may still contain former model/provider fields; `load_config`
ignores those fields, including legacy gateway credentials and billing policy,
so they cannot override the operator's production route. The next `save_config`
emits the compact project-owned format. Existing editions retain their recorded
capability profile rather than silently switching models.

## Local development controls

When the original server process has `CANARY_ENV=development` on a local runtime,
**Account → Models (dev)** and **Project settings → Models (dev)** expose
account preferences and project overrides. Those controls and their frontend
modules are excluded from production builds. The account API
`GET`/`PATCH /api/account/model-settings` and project model editing require
the same local development gate; project environment files cannot enable it.

Account preferences are stored in
`<projects_dir>/<user_id>/.model-settings.json`. Project overrides are stored
as `dev_model_selections` in the project `config.yaml`. In development, job
configuration resolves operator defaults, then account preferences, then
explicit project overrides. In production, only operator defaults apply.
Project settings remove an override by choosing **Account setting**. Changing
Draw after an edition exists is rejected. Saved choices do not start work.

When an older operator, account, or project setting names a retired API model,
reads ignore that choice and use the next active setting in the operator →
account → project order. The saved choice stays in its original file, so old
projects and their assets remain accessible. The development project selector
labels a retired choice and shows which account setting new work will use.
Editing another stage preserves the retired value; explicitly choosing a new
model replaces it. New selections still have to pass the current catalog.
An existing Draw edition keeps its recorded profile and cannot silently switch
to the fallback model for new pages.

The optional Codex adapter uses explicit `codex-dev/text/<model>` and
`codex-dev/image/<reasoning-model>` choices. The selector offers GPT-6 Luna and
GPT-6 Sol and GPT-6.1 Sol for text, and GPT-5.5 for images. It also requires
`CANARY_CODEX_DEV_ENABLED=1`, a local runtime, and a Codex login. Codex image
choices select the reasoning model driving the built-in image tool; they do not
select Sunburst. Codex usage is subscription-funded and does not settle API
credits. A disabled saved Codex choice fails before generation. The production
image omits the Codex execution modules and Labs router; the operator catalog
never lists Codex models.

The optional Claude Code adapter uses explicit `claude-dev/text/<model>`
choices (text only; default allowlist `claude-opus-5-5` and `claude-sonnet-5-5`, override with
`CANARY_CLAUDE_DEV_MODELS` as a JSON list). It requires
`CANARY_CLAUDE_DEV_ENABLED=1` (`./scripts/dev.sh --claude-code`), a local
runtime, the `claude` CLI, and a claude.ai login; `claude auth status` must
report a claude.ai first-party login before each prompt is sent. Each call runs
`claude --print` in an empty directory with no tools, MCP servers, user or
project settings, CLAUDE.md, or session persistence, and an environment that
never carries `ANTHROPIC_*` credentials. It sends the API route's effort and
output limit from `text_models.py`, and schemas through Claude Code's
`--json-schema`. Usage is `claude_subscription`-funded and does not settle
credits. Usage events record the served model's tokens (including cache reads
and writes), Claude Code's own cost estimate, and `api_equivalent_cost_usd`,
the same tokens priced as an API call, for comparing the two routes. Claude
Code's system prompt and structured-output mechanics differ from the API
route, so comparisons measure the model through Claude Code, not the raw API.

API and subscription routes can be mixed in a development job. API reservations cover
API work only. Request hashes identify input, not provider deduplication, and
ambiguous image submissions are not retried automatically. Automated tests use
mocked providers and do not establish account access or image quality.
