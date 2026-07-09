# Compose lettering guardrails

## Goal

Keep lettering easy to read without allowing it to dominate, clip, or obscure
the panel art. The intended visual reference is the supplied Page 03 example:
short, readable captions that support the image rather than replacing it.

## Approaches considered

1. Reduce the global type size only. This is quick, but preserves the core
   failure: a paragraph still consumes a small panel, merely in smaller type.
2. Use modest panel-aware type scaling and surface layout failures in Compose.
   This keeps a consistent comic-lettering voice while making the editor show
   when content needs editorial intervention.
3. Add an export-time exact renderer preflight as well. This catches all pages,
   including pages the author has not opened in the editor, and prevents an
   exported book from containing clipped lettering.

We will use approaches 2 and 3 together. The planner will also enforce word
budgets, so the issue is addressed before the final lettering pass.

## Typography and layout

The canonical defaults become 48px for speech and thought bubbles, 44px for
narration captions, and 20px for speaker labels. Each panel becomes an inline
CSS size container. Unoverridden lettering uses a bounded scale: 44--48px for
speech/thought and 40--44px for narration, with the smallest grid panels at the
low end. Explicit per-bubble and character-voice sizes remain author choices.

The bubble maximum width remains 52% of a panel. Dense content is flagged for
editing rather than silently widening across the art or shrinking beneath the
minimum readable size.

## Lettering measurements

Measurements use rendered bubble and caption rectangles relative to their
panel, not text length. This correctly accounts for font pair, word length,
line wrapping, and translated output.

- A bubble or caption extending outside its panel is an error.
- Lettering covering more than 32% of a panel area is an error; 25--32% is a
  warning.
- Any automatic caption or speech stack taller than 40% of its panel is an
  error.

The Compose editor measures the active page after it renders and adds those
findings to the existing Issues drawer. The export route runs the same DOM
measurement against every generated page before it decides that an existing
export is reusable or starts a new export. Errors return a clear 422 response;
warnings do not block export.

## Upstream prevention

`max_words_per_bubble` becomes active in the screenplay stage. Overlong speech
or thought beats are split at sentence/clause/word boundaries. The screenplay
prompt asks for short narration captions (20 words maximum) and dialogue that
fits the configured bubble budget.

The layout planner adds a combined speech/thought word cap and a narration word
cap to its existing beat-count caps. When a planned panel exceeds a combined
cap, its beats are deterministically split into consecutive panels. A single
oversized narration beat is shortened only at a word boundary; the original
source text remains preserved in `source_text`.

## Verification

Tests cover the new typography tokens, adaptive CSS contract, DOM measurement
rules, export rejection for a clipped panel, screenplay splitting, and
word-weighted planner splitting. Frontend tests cover rectangle measurement and
its Issues-drawer integration.
