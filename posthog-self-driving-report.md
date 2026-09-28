# PostHog Self-driving setup report

## Summary

PostHog Self-driving is configured for this project: Session Replay, Error Tracking, and Support are on; health, error, support, and GitHub Issues signal sources are enabled. The scout troop and two product-specific scouts are active, and two Replay Vision monitors are armed. Findings should begin appearing in the [Self-driving inbox](https://us.posthog.com/project/630262/inbox) within about 30 minutes.

## AI data processing

Approved by the organization-level setup gate.

## GitHub

GitHub Issues was **connected during this run**. The warehouse source `01a0e9c6-f686-0000-6f02-85559abb96e0` syncs the `issues` table for `FelipeBuiles/canary`; its first sync has started.

## Products enabled

| Product | Result | Browser SDK check |
|---|---|---|
| Session Replay | Already enabled | Removed the `disable_session_recording: true` override, so browser recording can follow the server setting. Restored default browser autocapture. |
| Error Tracking | Enabled | Browser exception capture was already enabled. |
| Support / Conversations | Enabled | Tickets will arrive only after an inbound email, inbox, or Slack channel is connected in PostHog. |

## Signal sources

| Source product | Source type | Action |
|---|---|---|
| `health_checks` | `health_issue` | Enabled (`01a0e9c6-33df-775a-966c-10b8bb9224f8`) |
| `error_tracking` | `issue_created` | Enabled (`01a0e9c6-33cd-77bd-8d42-e41dec1b594d`) |
| `error_tracking` | `issue_reopened` | Enabled (`01a0e9c6-33a9-7587-b80d-b6f88081837d`) |
| `error_tracking` | `issue_spiking` | Enabled (`01a0e9c6-33c6-7fd3-8cf3-3baf4a8a9f6a`) |
| `conversations` | `ticket` | Enabled (`01a0e9c6-33e3-720e-bf89-8837b453099a`) |
| `github` | `issue` | Enabled and running (`01a0e9c7-0101-764d-a157-89f833a0a2c7`) |
| `signals_scout` | `cross_source_issue` | On by default; no opt-out row was created. |
| `session_replay` | `session_analysis_cluster` | Deliberately skipped; Replay Vision scanners own replay coverage. |

## Connected tools

| Tool | Status | Notes |
|---|---|---|
| GitHub Issues | Connected by this setup | Only the responder-consumed `issues` table is syncing. Additional GitHub tables can be enabled in the source UI later. |
| Linear, Jira, Sentry, Zendesk and other catalog tools | Not used | Not selected in the connected-tools setup prompt. |

## Scout troop

### Active scouts

| Scout | Why it is active |
|---|---|
| `signals-scout-general` | Cross-product correlations and surfaces without a specialist. |
| `signals-scout-ai-observability` | Canary routes LLM/image-generation activity through its LiteLLM observability path. |
| `signals-scout-revenue-analytics` | Canary sells credit packs and has a checkout flow. |
| `signals-scout-web-analytics` | The browser records canonical page views and acquisition context. |
| `signals-scout-observability-gaps` | Identifies important telemetry lacking insights or alert coverage. |
| `signals-scout-generation-pipeline-health` | Custom: watches ordered pipeline and durable job progression. |
| `signals-scout-credit-purchase-recovery` | Custom: watches credit-block to checkout to purchase recovery. |

The remaining 22 built-in scouts are disabled to keep the troop selective. Error Tracking is covered by the native sources and Session Replay by Replay Vision, so their built-in scouts remain disabled to avoid duplicate findings. Other disabled specialists can be enabled later if the corresponding product becomes active.

**Verified run budget:** 100 runs/day, 0 used today, 100 remaining. The early-access banner states: “Scouts are in early access. Each project gets up to 100 scout runs a day. Contact team-self-driving@posthog.com if you need more.”

## Custom scouts

| Scout | Coverage and discriminator | Why it is separate |
|---|---|---|
| `signals-scout-generation-pipeline-health` | Watches the stage and durable-job lifecycle for broad, sustained failure clusters or stalls across projects/accounts; isolated paid-provider ambiguity, cancellation, and ordinary short queue waits are excluded. | The general and AI scouts do not own Canary’s ordered pipeline handoffs and durable queue outcomes documented in `AGENTS.md` and `docs/reference/job-queue.md`. |
| `signals-scout-credit-purchase-recovery` | Watches whether purchase completion declines while credit blocks or checkout starts remain stable; low-volume noise and entry-volume declines alone are excluded. | Revenue monitoring partially overlaps it, but this scout owns the author-facing recovery flow implemented in `web/src/store/insufficientCredits.ts` and `web/src/api/billing.ts`. |

Considered but not added: generic error/replay coverage is already routed through the native Error Tracking responder and Replay Vision scanners; generic web, revenue, AI, and observability coverage is handled by enabled built-ins. If either custom scout is noisy, set its config `emit` to `false` in PostHog to keep it running in dry-run mode.

## Replay Vision scanners

A scanner is an LLM that watches individual session recordings on a schedule and pushes what it finds to the inbox. These are the only setup components that spend Replay Vision quota; findings arrive at half weight and require independent corroboration before promotion to a report.

| Brief | Scanner | Scope | Sampling | Estimate | Status |
|---|---|---|---:|---:|---|
| Breakage monitor | [Canary book completion breakage](https://us.posthog.com/project/630262/replay-vision/01a0e9c9-c418-7d1a-86e0-dc3321fbbb07) | Recordings visiting `/project/:id/book`, Canary’s final edition-check and export completion flow | 0.5 | 0 observations / 0 credits monthly | Created; emits Self-driving findings |
| Frustration monitor | [Canary author frustration](https://us.posthog.com/project/630262/replay-vision/01a0e9c9-c4b1-7e2d-a718-6e67eb29bb82) | `$rageclick` recordings only; no URL filter | 1.0 | 0 observations / 0 credits monthly | Created; emits Self-driving findings |

No recordings were available during setup. Both monitors are armed and will begin scanning when recordings arrive. The organization has 2,500 Replay Vision credits remaining for the current period, and no existing scanner spend. Rate early observations with thumbs up/down in each scanner to receive a configuration recommendation.

## Follow-ups

- [ ] Connect an inbound Support / Conversations channel (email, inbox, or Slack) in PostHog so ticket signals can begin arriving.
- [ ] Verify real browser traffic produces recordings after deployment; no recordings existed during setup.
- [ ] The Self-driving project profile was not yet built, and schema-read access was unavailable to this MCP connection. The scouts are grounded in the repository’s documented telemetry contract; revisit their baselines after live traffic accumulates.

## Files changed

- `web/src/telemetry.ts` — removed browser overrides that disabled Session Replay and autocapture.
- `posthog-self-driving-report.md` — created this setup record.

## What happens next

The scout coordinator picks up fresh configurations within about 30 minutes. Scout runs draw from the daily budget, cluster corroborated findings into reports, and immediately actionable reports can begin coding tasks. Review findings in the [Self-driving inbox](https://us.posthog.com/project/630262/inbox).
