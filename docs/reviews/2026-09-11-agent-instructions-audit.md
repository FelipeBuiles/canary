# Agent instructions and documentation audit

**Status: Review, September 11, 2026. Recommendations are proposed, not active instructions.**

**Follow-up implemented September 11:** corrected the glossary, repaired optional
CLAUDE.md handling in the checker, updated plan navigation/status, consolidated
task-specific reading and verification in AGENTS.md, and replaced the malformed
global AGENTS.md with concise working preferences. The debugging skill remains
unchanged at the user's request. The docs checker, three focused link-check
scenarios, and diff whitespace checks passed. Session benchmarking, generated
reference freshness checks, and broader skill routing changes remain unimplemented.
The findings below describe the pre-cleanup snapshot.

The strongest explanation for unnecessary debugging steps is an overly broad,
prescriptive global debugging skill combined with repeated context-loading rules.
There is also confirmed documentation drift. Removing friction at its source is
preferable to adding another layer of instructions telling agents to ignore it.

This review examined the root and global AGENTS files, the available skill
catalog, the full diagnosing-bugs skill, documentation navigation, glossary,
agent context, selected contracts and historical plans, and documentation check
implementation. It checked Markdown links across 67 files. It did not audit every
runtime claim or inspect prior session transcripts. Behavioral causes below are
inferences from instructions, not measured attribution of past sessions.
Existing checkout edits were preserved during review and subsequent cleanup.

## Findings, in priority order

### 1. High: a hard-bug workflow automatically applies to ordinary bugs

`/Users/jbuiles/.agents/skills/diagnosing-bugs/SKILL.md:3` triggers on essentially
any report of something broken, failing, throwing, or slow. Its body then:

- Forbids forming a theory from code before a runnable reproduction exists (line 66).
- Stops and requests more access/evidence if it cannot build that loop (line 55).
- Requires minimization until every remaining element is necessary (lines 80–86).
- Requires 3–5 hypotheses before testing any (line 90).
- Suggests 100 repetitions for nondeterministic bugs (line 51).

These are useful techniques for difficult investigations, but making them gates
can turn a simple traceback or configuration fix into harness construction,
repeated runs, and a long hypothesis report. For this project's paid generation
paths, stress repetitions also need explicit separation from provider-free replay.
The project already forbids ambiguous paid retries; preserve that constraint.

**Recommendation:** make the existing heavy workflow explicitly invoked, or narrow
its description to difficult, unresolved or intermittent bugs. Allow code/log
inspection to locate a useful reproduction seam. Reuse supplied failures and
existing tests; minimize or enumerate alternatives only when uncertainty warrants
it. Stop testing when the symptom and affected contracts have sufficient evidence.

### 2. High: the required documentation check crashes

`scripts/check_docs_reliability.py:90` unconditionally reads root `CLAUDE.md`.
That file is absent. Running the documented command produced `FileNotFoundError`,
so a docs task following AGENTS encounters an unrelated verification failure.

**Recommendation:** distinguish required files from optional instruction files;
skip an absent optional CLAUDE file and report missing required files as structured
failures. Do not recreate a duplicate instruction file just to satisfy this check.
The checker also only verifies generator markers, not generated-reference
freshness. Add a non-mutating freshness check if stale generated docs recur.

### 3. High: the glossary contains obsolete runtime behavior and a stop rule

`CONTEXT.md:62` says Finish verifies/corrects renders and coordinates Draw
corrections. `stages/s8_finish.py:1` describes the active provider-free stage;
its `run()` invokes `finish_book`, and `docs/reference/stage-contracts.md:16`
defines provider-free preflight and PDF/CBZ packaging. The glossary also gives
panel regeneration as a Generation job example at line 179.

Compounding this, `CONTEXT.md:7` says to stop and resolve vocabulary conflicts
before changing code/docs, despite the document describing itself as
implementation-free and subordinate to executable evidence.

**Recommendation:** correct these definitions, remove runtime orchestration from
the glossary, and reserve a pause for ambiguity that affects the requested result.
An obvious stale term should be corrected locally without a separate decision gate.

### 4. Medium: context navigation behaves like repeated onboarding

`AGENTS.md:3`, `docs/agents/domain.md:5`, and the debugging skill each direct
CONTEXT/ADR reading. Agent context points back to the documentation policy and
glossary. The root instructions, glossary, agent context, and stage contracts
span roughly 880 lines; the whole set is not explicitly mandatory, but there is
no clear instruction to retrieve just the relevant section and reuse loaded facts.

**Recommendation:** keep AGENTS as the short entry point and route by symptom.
Read the glossary for an unfamiliar term, an ADR for a relevant architectural
decision, and a contract for the touched boundary. Avoid a routine full-document
onboarding sequence. Separate code navigation from the long list of recent
implementation details in agent-context.

### 5. Medium: stale plan paths escape the checker

`docs/README.md:55` still directs agents to `docs/superpowers/`, including a
full-page implementation plan path that no longer exists. The actual plan is
under `docs/plans/2026-07-25-full-page-generation/README.md`. That plan still
instructs implementation on `render-full-pages` and test-first changes.
The default status policy names `docs/superpowers/` but omits actual `docs/plans/`.

**Recommendation:** update the map and explicitly classify dated plans as
historical unless individually designated active. Reassess the remaining
acceptance work before deleting any plan. Convert navigation paths into Markdown
links so the existing link check can see them.

The supplemental scan found zero missing Markdown link targets across 67 files.
This does not validate backtick paths, anchors, or semantic claims; it explains
why the obsolete plan pointer can survive link validation.

### 6. Medium: the global instruction file is malformed and apparently obsolete

`/Users/jbuiles/.codex/AGENTS.md:1` begins an HTML comment with no closing marker;
its final shell fence is also unclosed. It contains delegation commands such as
`./ask-ai` while claiming the tools are in PATH. Those spellings search the current
directory, not PATH. The same text is visibly present in this session's supplied
instruction context, so treating the comment as disabled guidance is unreliable.

**Recommendation:** remove retired instructions from active instruction files, or
rewrite them as valid, narrowly scoped guidance if still wanted. Keep personal
working preferences here and repository facts in the project's AGENTS. This
review did not invoke or validate those external delegation tools.

### 7. Medium: verification commands lack a clear scope selector

`AGENTS.md:53` and agent-context list the entire backend suite and frontend
test/build/lint commands. The final AGENTS verification paragraph asks for
proportionate checks, but leaves selection implicit.

**Recommendation:** show targeted test commands as the debugging default; require
broader suites for shared contracts, integration changes, or release requirements.
Run the docs checker for docs-only changes. Preserve required checks, but do not
repeat a passing suite without changed code or new evidence.

### 8. Lower priority: overlapping policy sources need clearer ownership

AGENTS line 40 forbids routine worktrees; line 66 broadly endorses authorized
local worktrees. These can be reconciled, but one precise rule is easier to apply.
The documentation hierarchy ranks code over AGENTS without separating evidence
of behavior from instructions governing actions. Existing buggy code must not
be mistaken for authority to disregard a requested fix or a guardrail.

The skill catalog also offers overlapping frontend workflows: impeccable,
ui-ux-pro-max, frontend-design, design critique, and web-design-guidelines.
This is a routing risk for UI debugging, not proof that all their bodies load.

**Recommendation:** separate behavioral evidence from agent policy; remove
duplicate working-style rules and select one primary UI workflow per task.
Keep specialized audits available through explicit invocation.

## Current OpenAI guidance and its application

OpenAI recommends practical, concise AGENTS files with durable project facts,
verification commands, and links to specialized guidance. Add rules in response
to observed mistakes. Here, retain the valuable stage, artifact, identity, and
paid-retry guardrails while reducing repeated workflow instructions.
Source: [Codex best practices](https://learn.chatgpt.com/guides/best-practices).

The documented instruction chain includes global and project guidance, with
more local instructions overriding earlier guidance. Auditing only this repo
misses the global file. The documented default combined size cap is 32 KiB;
there is no evidence that this cap caused the problems observed here.
Source: [AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Skills initially expose metadata and load their full instructions on selection.
Descriptions govern implicit matching, so narrow triggers matter more than
simply reducing the installed skill count. Codex supports explicit-only invocation
through `policy.allow_implicit_invocation: false` in a skill's `agents/openai.yaml`.
Avoid adding a same-name local copy as an override: duplicate names do not merge.
Source: [Build skills](https://learn.chatgpt.com/docs/build-skills).

Current model guidance explicitly identifies sensitivity to conflicting skills
and excessive testing on smaller tasks. This supports auditing the existing
instruction stack and calibrating verification, rather than adding more rigid
process gates. It does not establish which rule caused a particular past run.
Source: [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model).

## Proposed compact debugging policy

This is proposed replacement wording, not an additional mandatory workflow:

> Start from the reported symptom and available evidence. Inspect the relevant
> code, logs, and existing tests to choose the smallest useful check. Reuse an
> existing reproduction; build a new harness only when it resolves uncertainty.
> Read domain references only for the touched concepts or boundaries. Apply a
> focused fix and verify the original symptom plus affected contracts. Expand
> hypotheses, instrumentation, and test scope only when results require it.
> Preserve paid-operation and artifact guardrails. Ask only for missing evidence
> or authorization that blocks meaningful progress; state any unverified claim.

## Suggested implementation order and evaluation

1. Repair the documentation checker, glossary definitions, and stale navigation.
2. Narrow the global debugging skill or make it explicit-only; clean the global
   AGENTS file at its source.
3. Consolidate project onboarding and add targeted verification examples.
4. Evaluate fresh sessions on a simple traceback, a UI state bug, a difficult
   intermittent bug, a docs-only change, and an ambiguous paid-generation failure.

Compare correct outcomes, time to the first useful diagnostic, irrelevant reads,
unnecessary tool calls, repeated passing tests, and avoidable user questions.
Use the same model/settings and comparable checkout states; repeat examples to
account for run variability. A reduction in steps is useful only if correctness
and the paid-operation safeguards hold. No session benchmark was run in this review.
