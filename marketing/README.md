# Scenewright marketing workspace

An agent-first marketing workspace for [Scenewright](https://github.com/FelipeBuiles/canary). Agents research and draft. You approve every draft and post it yourself.

## Set up the workspace

This workspace is designed to live at `<canary-root>/marketing`. Its skills are discoverable from `<canary-root>/.agents/skills/`. Run workspace commands from this directory:

```sh
npm ci
npm run sync:canary
npm run check
```

The application reads Canary from its parent directory by default. Set `CANARY_ROOT` to override it. Sync reads Canary and records its revision and file hashes under this workspace. It does not change Canary or verify marketing claims by itself.

Open pi from the Canary root to discover the marketing skills, then run marketing tasks with `marketing/` as the working directory. The workspace-specific instructions are in `marketing/AGENTS.md`. The PostHog and Agentgrown endpoints are registered in Canary root `.pi/mcp.json`; authenticate them from the Canary root if needed.

Authenticate the optional live data sources from the Canary root:

```sh
pi mcp login posthog
pi mcp login agentgrown
pi mcp list
```

Endpoint registration does not prove a data query works. Until you sign in, analytics workflows report a blocker instead of producing guessed metrics.

## Run a marketing workflow

If you are new to marketing, start here and repeat weekly:

```text
Use marketing-plan to build this week's plan.
```

`marketing-plan` runs the other skills as it needs them. It writes a plain-language plan to `intel/reports/<date>-marketing-plan.md`. The plan covers where to post what, whether ads are ready, promos to showcase, pricing, coupons, and missing features. It also drafts up to three of this week's posts or ads. Read the plan in the desk under **Plans & reports**.

To run one piece on its own, ask pi to use one of these skills:

| Skill | What it produces |
| --- | --- |
| `marketing-plan` | A weekly plan with recommendations and up to three drafts |
| `community-scan` | Scored discussions in `intel/opportunities/` and up to three founder-disclosed reply drafts |
| `competitor-intel` | Sourced profiles in `intel/competitors/` and a positioning report |
| `ai-visibility` | Captured answer-engine responses and sample-labeled mention measurements in `intel/reports/` |
| `content-seo` | Articles, release copy, and manual landing-copy proposals in `drafts/` |
| `ad-creative` | Google and Meta copy plus separate briefs for rights-reviewed comic assets |
| `growth-analytics` | Read-only PostHog and Agentgrown reports, or explicit connection blockers |
| `product-facts` | Reviewed claims and source attestations in `knowledge/facts.yaml` |

For example, ask pi to use `content-seo` to draft an evergreen article about choosing PDF or CBZ. It should cite the current ledger facts, save only public copy in the draft body, put editorial notes in a separate report, and run `npm run check`.

## Review drafts

Open `/backoffice` on the existing local Canary frontend. Connect to the local API with your operations token, then select **Marketing**. The UI uses Canary's existing development servers. There is no separate React project or marketing server.

The backend must run with `serve --dev` in a non-production environment. Marketing requests require the operations token, a loopback client and host, and no forwarding headers. The Marketing navigation item appears only in local frontend development builds connected to a local API. Production builds omit the desk, production APIs do not register its routes, and Docker continues to exclude `marketing/`.

Install this workspace's dependencies with `npm ci` before opening the desk. FastAPI invokes its TypeScript rules through a short-lived Node process. Research commands and the backoffice share the same audit and approval implementation. Requests serialize through a local `.desk.lock`; no persistent Node service is needed.

Review the copy and its facts before approving. Approval binds to the copy, its metadata, the cited fact records and their verification hashes, and the current claims policy. Stale browser views and later evidence changes require another review. Approvals imported from the standalone desk also require renewed human review; they are never silently upgraded. Approval does not post anything. Copy the text and post it yourself, then mark it **I posted it**. Published records remain history.

**Plans & reports** shows `intel/reports/` read-only, newest first. The desk displays raw draft text. Blog and community bodies contain only public copy. Ad JSON and landing proposals need manual transfer into the destination editor. Editorial notes and asset-clearance evidence belong in `intel/reports/`.

## Keep claims tied to the product

Every product claim in a draft needs a fact id. Each fact includes a verbatim quote, canary line citations, and a hash of each file reviewed for meaning. A sync never renews those attestations. If canary changes, the `product-facts` workflow must inspect the claim again before renewing them.

`npm run verify` validates types, behavior tests, the community scorer, and skill files. The repository check gate runs it without treating pending editorial work as a code failure. `npm run check` also audits the workspace artifacts and may fail until a human renews an outdated approval. It checks source quotes and hashes, rejects unknown or internal-only fact references, and detects changed approvals. It cannot determine whether every sentence in free-form prose cites the right fact. Human semantic review remains required.

Read `knowledge/claims-policy.md` before public drafting. Numerical station counts are unresolved in canary. Social and ad copy omit prices and credits. Creative assets need per-book rights and page checks. Never reuse manuscripts or output from canary's `samples/`, `projects/`, or `showcase/video/`.

`AGENTS.md` contains the agent rules. `THIRD_PARTY_NOTICES.md` records Falbor attribution and licensing considerations.
