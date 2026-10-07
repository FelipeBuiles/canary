# Localization

Status: Current. Implementation and provider-free tests are authoritative.

## UI messages

`web/src/locales/{en,es,fr}.json` are the only UI translation catalogs, including
landing-page copy. The React provider owns UI preference only. Storage failure
keeps the preference in memory; regional browser preferences are matched with
`Intl.Locale`, and storage events synchronize open tabs. UI preference never
writes project settings or translates book content. Project generation language
uses the same supported set; unsupported configuration values fail validation
instead of silently generating English.

Use `t("Jump to page {number}", { number })` for interpolation. Use one complete
ICU message for plurals, with numeric values, for example
`t("{count, plural, one {# activity} other {# activities}}", { count })`.
Do not concatenate grammatical fragments or call `.replace()` on translated text.
FormatJS `intl-messageformat` owns ICU parsing, plural rules, and formatting.
Formatters are cached per provider/locale; there is no global active language.
Unknown dynamic server/user text remains literal data, not an ICU program.

Run `npm run i18n:extract` in `web/` after adding source-first messages. It adds
literal `t()`/`msg()` calls and literal conditional branches to English, creates empty
Spanish/French entries, and leaves existing translations intact. Complete those
entries, then run `npm run i18n:check`. The build runs the same check: missing
messages, incomplete target catalogs, malformed ICU, mismatched placeholders, and
missing statically visible values fail. Named IDs such as `landing.hero.title`
and stage/status labels have explicit English catalog entries. Deferred labels
and server-provided strings cannot all be statically extracted; add their known
UI labels with `msg("Caption")` when declaring maps/arrays. This marker checks
message keys at compile time and makes deferred labels extractable without
translating at module load. Extraction never deletes such entries.

This migration uses FormatJS through the existing small `useI18n()` facade.
Lingui is also a sound source-first macro/extraction approach, but migrating all
React expressions and deferred labels to compiler macros would add a second
migration without improving the book-content contract. See the
[primary-source research](../research/2026-09-26-localization-architecture.md).
Catalog validation establishes structural completeness, not native-language
editorial quality; new translations still benefit from that review.

English is in the startup bundle. Spanish and French catalogs load on demand,
with cached promises and a provider loading boundary for a stored non-English
preference. Language changes use a React transition so the current screen stays
usable during the download. Replay's safe-label allowlist indexes only trusted
catalogs already loaded by the UI; it never fetches another language for recording.

## Editable book lettering

`source` is the stable Pages-owned display wording. Adapt's canonical copy stays
immutable. A project selection (`source`, `en`, `es`, `fr`) is separate from both
UI preference and translation provenance. Integrated/baked art is not translated
by these APIs.

- `GET /lettering/languages` reads the book once and returns stored locale choices,
  stale counts, and optimistic selection snapshots. It does not consult model
  admission, pricing, credits, or providers.
- `POST /lettering/locale` accepts a selection snapshot and switches saved copy,
  including restoring `source`. Stale variants can be selected for review.
  A same-locale no-op preserves revision and placement-review evidence.
- `GET /lettering/translation-estimate` quotes missing target variants from
  **source display copy**, never from the selected translated language.
- `POST /lettering/translate` retains reserved credits, request receipts, exact
  snapshot checks, disabled automatic retries, and complete-book publication.
  Existing target text is retained even when stale; generation fills missing
  variants only. The UI directs already-stored languages to the free selection.

Each element's `translation_sources` stores the exact source wording against
which its target variants were generated or explicitly reviewed. Source edits
keep target wording but mark it stale. Editing a target or explicitly confirming
that it matches source records new provenance. This does not confirm visual
placement. Both the browser and server renderer expose `stale_translation`;
Finish/publication reject stale visible copy and incomplete published languages.
Hidden variants also participate in book-language completeness.

The new element schema changes artifact hashes. Incompatible older saved
lettering artifacts are rejected with a rerun instruction; there are no hash
exceptions, implicit migrations, or paid regeneration during reads. Rebuild in a
new editable project and retain the old project's revisions. Existing integrated
and baked editions retain their own rendering contracts.
