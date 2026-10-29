---
name: product-facts
description: Verify Scenewright product claims against Canary and maintain the claims ledger. Use after a Canary sync, when a draft needs a new fact, or when the audit reports fact, quote, source, or verification issues.
---

Migration layout: the skill is at Canary root in `.agents/skills/`; run its commands from `<Canary root>/marketing`. Treat that directory as `ROOT`, and paths below as relative to it unless explicitly marked Canary-root-relative. Canary is its parent directory and is read-only to marketing workflows.


# Product facts

Work from the marketing repository root. Read `AGENTS.md`, `knowledge/claims-policy.md`, and the `Fact` schema in `src/domain.ts` before changing claims. Read `src/audit.ts` for the current audit rules. Canary is read-only, including when paid-provider evidence is missing.

## Review after a Canary sync

1. Run `npm run sync:canary` unless the task forbids sync or another writer owns its outputs. Never edit `knowledge/canary.lock.json` or `knowledge/canary-changes.md` by hand.
2. Read the changelog and compare affected ledger citations with `knowledge/canary.lock.json`. A sync records upstream state. It never re-verifies facts or refreshes `verifiedSources`.
3. For each affected fact, read every cited source and its surrounding context. Check the document's status and the entire statement, including numbers, conditions, rights, and availability. Follow Canary's hierarchy in `docs/README.md`. Public copy does not outrank implementation.
4. Confirm the quote appears verbatim within at least one cited line span after whitespace normalization. Preserve punctuation and markup from the source. Check every citation's path and inclusive line range.
5. If evidence no longer supports the statement, narrow or remove it. Keep proposals, internal settings, disputed claims, and implemented-but-unverified work `marketable: false`. Do not turn a target into a result.
6. Only after reviewing that fact's meaning and quotes, set its `verifiedSources` entry for every referenced file to the SHA-256 of the whole current raw file bytes. An internal fact still needs review. Its attestation confirms its stated limitation, not that the capability is marketable.
7. Repeat the semantic review for every affected fact before updating its attestations, even when another fact cites the same file. Never bulk attest as a side effect of sync, hash drift, or a successful quote check.
8. Update `knowledge/claims-policy.md` when contradictions or rights restrictions change. Run `npm run check` and inspect every issue before handing back.

Read `CANARY_ROOT` when supplied. Otherwise read `..`. To compute a reviewed file's hash, set its relative path and run from the marketing root:

```sh
CANARY_FILE=PRODUCT.md node --input-type=module -e 'import {readFileSync} from "node:fs"; import {createHash} from "node:crypto"; import {resolve} from "node:path"; console.log(createHash("sha256").update(readFileSync(resolve(process.env.CANARY_ROOT || "..", process.env.CANARY_FILE))).digest("hex"))'
```

Record the result under `verifiedSources` using the file's relative path without a line suffix. Do not normalize bytes before hashing. Do not copy the lock hash without reading the source and checking it against the current file.

## Add a fact for a draft

1. Split the proposed copy into factual claims. Reuse an existing supported fact when it covers the claim without stronger wording.
2. If no fact fits, find current evidence in a file already listed in `knowledge/canary.lock.json`. If the file is absent, request a manifest addition from the manifest owner, then sync before citing it. Do not bypass tracking with an unlisted source.
3. Add an entry matching `Fact`. Use a unique lowercase hyphenated `id`, a precise `statement`, an exact `quote`, inclusive `sources` such as `PRODUCT.md:20-28`, and a `marketable` boolean.
4. Read and review every cited file before adding its `verifiedSources` hash. Cover every clause with evidence, not merely the quoted phrase. Do not use an unrelated exact quote to support a broader statement.
5. Apply the claims policy's channel and asset restrictions. `marketable: true` permits drafting only within those restrictions. It does not approve a draft, clear an image, or permit posting.
6. Put supporting ids in the draft's `facts:` list. Keep the draft at `status: draft`. Never attach internal-only ids or use their contents as public claims.
7. Run `npm run check`. Read the draft again for unsupported claims the automated audit cannot recognize.

## Resolve audit warnings and errors

- For parse errors or duplicate ids, correct the ledger to the current schema. Check draft references before deleting or renaming an id.
- For missing files, untracked sources, or invalid line ranges, locate the authoritative evidence. Request manifest changes when needed. Do not substitute an unrelated path merely to pass.
- For a missing quote, read the source. Correct the span or quote only if the statement is still supported. Otherwise narrow or remove the fact.
- For source drift, missing attestations, or mismatched attestations, repeat the full semantic review above. A sync cannot clear the review obligation. Rehashing alone is not a fix.
- For an unknown or internal-only fact in a draft, replace the claim with supported wording and a marketable fact, or remove it. Never flip `marketable` just to satisfy the audit.
- For an approved draft changed since approval, return it to draft for human review. Agents never approve or publish. Facts or policy changes can also require renewed review.
- Report checks blocked by another writer or missing evidence. Do not edit another writer's files, run paid generation, or claim unreviewed facts are verified.

If outputs are staged in an isolated directory, validate that staged ledger against the main schemas and audit without writing to the main checkout. State which data the command checked. The integrator must run the full workspace check after copying the staged files.
