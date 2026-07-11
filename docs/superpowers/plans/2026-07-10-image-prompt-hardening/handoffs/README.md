# Durable Slice Handoffs

Each implementation session writes exactly one `NN.md` file here before it
finishes. Do not pre-create empty handoffs: absence means the prerequisite slice
has not produced a durable as-built contract.

The next session must treat the handoff as evidence, then verify the named tests
and symbols in the current worktree. A handoff never overrides the master plan,
repository `AGENTS.md`, or user instructions. When implementation deliberately
deviates from the planned contract, record the deviation and rationale here and
update affected future briefs if their assumptions changed.

Do not include secrets, credentials, signed URLs, private provider payload data,
or transient local logs.

Use this template:

```markdown
# Slice NN Implementation Handoff

Date:
Status: COMPLETE | BLOCKED
Branch/commit: only when one exists

## Contract delivered

- Public types, functions, schemas, endpoints, storage paths, and version values.
- Exact ownership/invalidation/fingerprint rules introduced by this slice.

## Files changed

- Repository-relative paths and one-line purpose.

## Behavior and deliberate deviations

- User-visible/operational changes.
- Any deviation from the slice brief, with rationale and affected later slices.

## Tests and verification

- Exact commands and pass/fail counts.
- Paid/model calls: explicitly state none, or authorization/cost/result.

## Independent review

- Verifier result: CONFIRMED | REFUTED | INCONCLUSIVE.
- Security review result when required.
- Findings resolved or still open.

## Remaining risks and next-slice prerequisites

- Unresolved risks, temporary branches/inventories, and cleanup owner.
- Exact symbols/files/tests the next slice must verify before starting.
```

If implementation becomes blocked after work begins, write a `BLOCKED` handoff
with the exact condition and partial changes. If the prior prerequisite is
missing before work begins, do not create the current slice's handoff. In either
case, the next slice must not start until the condition is resolved and the
current handoff says `COMPLETE`.
