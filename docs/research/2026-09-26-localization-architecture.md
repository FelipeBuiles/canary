# Localization architecture research

Status: Proposed. Research date: 2026-09-26. These recommendations describe a target design, not evidence that the migration is complete.

## Recommendation

Use an established ICU MessageFormat implementation for UI messages, extraction/checking during development, and independent versioned locale variants for editable lettering. Share the supported-language registry, but never couple the user's interface preference to a project's display language. No UI library solves project translation provenance, paid-job concurrency, or visual review.

For a new source-first React API, **Lingui is the strongest fit for reducing verbosity**: macros keep English copy beside the component, extraction maintains catalogs, and compilation provides ICU formatting. FormatJS is equally credible when retaining a small `t(message, values)` facade and migrating the existing source-string catalogs makes the change less risky. Choosing a library alone does not address missing coverage, fragmented sentences, or stale project translations.

## Current implementation evidence

At inspection, `web/src/i18n.tsx` was a large hand-maintained dictionary plus several separate translation dictionaries. `t` accepted any string and silently fell back to that string; it did not own interpolation or plurals. The provider directly accessed localStorage, which can throw when storage is unavailable.

`lettering/translation.py` preserved any existing target string without checking whether its source changed. Missing variants were translated from the currently selected page locale, falling back to `source`, so changing display language could change the source of later translation. Its snapshot admission, exact output-identity validation, no-automatic-retry behavior, complete-book publication, and placement-review invalidation are valuable contracts to preserve. `models/lettering.py` uses `source` as an internal variant key: it is not a real language tag.

## Primary-source comparison

| Approach | Relevant capability | Canary tradeoff |
| --- | --- | --- |
| Lingui | Source-first React macros, generated or explicit IDs, standard catalogs, extraction, compilation, rich text and ICU formatting. [Introduction](https://lingui.dev/introduction), [macros](https://lingui.dev/ref/macro) | Best concise authoring model. Requires build integration and conversion of existing call sites; current official documentation is for 6.0, so do not combine it blindly with older package APIs. |
| FormatJS / React Intl | Message descriptors and TypeScript/JSX extraction, compiled catalogs, hooks and framework-independent formatting. [Extraction](https://formatjs.github.io/docs/getting-started/message-extraction/), [CLI](https://formatjs.github.io/docs/tooling/cli/), [API](https://formatjs.github.io/docs/react-intl/api/) | Strong migration option through a thin facade. The standard descriptor API is more verbose; custom wrappers need explicit extraction support. |
| i18next | Typed selectors and `enableSelector: "optimize"` avoid enumerating huge key unions; interpolation inference requires literal resource types or generated declarations. [TypeScript guide](https://www.i18next.com/overview/typescript) | Good for semantic-key/namespace workflows, but replacing existing inline English with named keys adds indirection. It is not necessary merely to gain reliable interpolation. |

ICU messages provide locale-aware plural/select and number/date formatting. Complete sentences should be single messages, with values supplied once, instead of concatenated fragments or chained `.replace()` calls. The `other` plural branch is required. Treat message syntax and placeholder compatibility as build errors. [FormatJS ICU syntax](https://formatjs.github.io/docs/core-concepts/icu-syntax/)

Lingui exposes a typed-message-ID registration mechanism, but choosing a TypeScript-compatible library does not automatically make arbitrary dynamic strings safe. [Typed IDs](https://lingui.dev/guides/typed-message-ids) Lingui's current `compile --strict` permits configured fallback translations; therefore strict compilation alone does not establish complete Spanish/French coverage. Add an explicit completeness check when fallback remains enabled. [CLI](https://lingui.dev/ref/cli)

## Project lettering design

Use `source` as the stable editable source variant and record its actual language separately when known. Translate new variants from that source, regardless of the active display language. Preserve Adapt's canonical text boundary; editable source copy remains a Pages-owned value.

For each translated element, retain text, source fingerprint, and origin (generated or user-edited). Freshness follows the exact source copy that produced or was reviewed against that variant. When source copy changes, retain target text but mark it stale; do not silently present it as a current translation or erase manual edits. This is a design recommendation derived from established translation workflows: Weblate retains translations and their history while marking them for editing after source changes. [Weblate source editing](https://docs.weblate.org/en/latest/user/translating.html#editing-source-strings-and-keys)

Expose missing/current/stale separately in estimates and editor state. Applying a locale with all usable variants is a local operation; generating missing variants is an explicit estimated job. Stale manually edited copy needs an explicit refresh or confirmation of current wording. Changing only selection must not modify source copy or recursively translate from another target.

Retain optimistic snapshot checks before paid work and publication, validate exactly one output per requested entity, publish complete books atomically, and reset placement review after actual text/locale/layout changes. A same-locale no-op must not reset review. Translation freshness and visual placement review are separate facts. No successful translation or SVG render establishes visual quality.

Use BCP 47 language tags for actual locales and canonicalize them at boundaries. Keep the supported product set explicit; accepting arbitrary tags does not establish font, shaping, or layout support. Language, script, and region subtags have distinct meanings, so avoid implementing recognition with prefix checks. [W3C language-tag guidance](https://www.w3.org/International/questions/qa-choosing-language-tags)

## Migration acceptance criteria

1. One UI catalog workflow; every static message is extracted or checked, translated placeholders match, and dynamic backend text is handled deliberately.
2. All currently supported UI locales preserve existing translations and work with unavailable localStorage; number/plural examples exercise non-English rules.
3. UI locale switching never mutates project language, and project translation never changes interface language.
4. Project tests cover stable source selection, edited-source staleness, retained manual variants, empty copy, same-locale no-op, concurrent changes, malformed provider identities, and source-locale restoration.
5. Lettering changes invalidate Finish while preserving Draw and canonical Adapt content; generated text cannot silently mark placement reviewed.

Research does not prove translation quality or layout correctness. Those still require native-language and visual review on representative pages.
