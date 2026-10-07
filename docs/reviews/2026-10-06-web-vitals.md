# Scenewright Web Vitals review — October 6, 2026

**Status: Historical — dated production baseline and local implementation evidence.**
Production measurements below precede these changes. The optimizations are in
the shared checkout; their production Web Vitals impact requires deployment
and another audit. Source baseline: `5163e8e9`.

## Production baseline

Google PageSpeed Insights audited the anonymous homepage at
`https://scenewright.ink/` on October 6, 2026 at 11:27 PM EDT, with Lighthouse
13.5.0. Mobile used a simulated Moto G Power and slow 4G; desktop used the
desktop Lighthouse configuration. These are individual lab runs.

| Measurement | Mobile | Desktop |
| --- | ---: | ---: |
| Performance score | 65 / 100 | 94 / 100 |
| First Contentful Paint | 4.3 s | 0.9 s |
| Largest Contentful Paint | 6.3 s | 1.4 s |
| Total Blocking Time | 10 ms | 0 ms |
| Cumulative Layout Shift | 0.063 | 0.039 |
| Speed Index | 4.7 s | 1.2 s |

Sources: [mobile report](https://pagespeed.web.dev/analysis/https-scenewright-ink/gs14f2k3rp?form_factor=mobile)
and [desktop report](https://pagespeed.web.dev/analysis/https-scenewright-ink/gs14f2k3rp?form_factor=desktop).
The reports have no Chrome UX Report field data. Low lab Total Blocking Time
does not establish real-user Interaction to Next Paint.

The mobile LCP element was the main headline, `h1#landing-hero-title`. Its
reported render delay was about two seconds. The audit flagged:

- Render-blocking requests, including the Google Fonts stylesheet; estimated
  potential savings of 390 ms.
- Ineffective cache lifetimes; estimated cache savings of 2,699 KiB.
- Oversized images; estimated image delivery savings of 636 KiB.
- Unused JavaScript; estimated savings of 174 KiB.
- A total network payload of 4,139 KiB.

These estimates overlap and should not be added together or treated as a
prediction of the optimized score.

A PostHog query for homepage-host LCP p75 over the preceding seven days returned
empty good/needs-improvement/poor bands in project 630262. Its event catalog
had no `$web_vitals` event, and the application scrubber rejected that event.
There was no usable field measurement stream to validate production LCP, INP,
or CLS against user traffic.

## Implemented optimizations

| Gap | Change | Expected effect |
| --- | --- | --- |
| Every language shipped at startup, including a second import through replay privacy | Spanish and French catalogs load on demand; language transitions retain the current screen. Replay indexes only trusted catalogs already loaded by the UI. | Less initial download, parsing, and evaluation while retaining localized controls and content masking. |
| Public pages waited for authentication restoration; homepage code loaded afterward | Public auth/legal/reader routes render during restoration. The homepage chunk loads alongside restoration; root and protected-route gates remain. | Removes an avoidable public-page delay and homepage request waterfall. |
| Google Fonts CSS required an external request before layout | Self-hosted WOFF2 subsets with `font-display: swap`; critical Latin display/body fonts preload. Existing families and licenses are retained. | Earlier text paint, fewer origins, and reusable fingerprinted font caching. |
| A roughly 2.4 MB hero video started fetching immediately | Poster preloads at high priority. Autoplay media becomes eligible after page load and an idle slot; explicit Play starts immediately. Reduced-motion visitors retain the poster. | Initial network capacity serves the page before optional motion. |
| Marketing images were delivered at full source resolution | Added 480/800-pixel WebP variants, responsive `srcset`, lazy-image automatic sizing with fallback, and source-derived dimensions. Full-size inspection links remain. | Smaller transfers where the browser selects previews and stable reserved image space. |
| Static responses lacked explicit freshness policies | Fingerprinted build assets cache immutably for one year. Public marketing files cache for one hour. HTML revalidates. Policies include 304 and video range responses. | Faster repeat visits without trapping users on an old HTML shell. |
| Telemetry competed with startup | SDK, replay, error, and Web Vitals modules load together after page load in an idle slot. | Removes optional telemetry from the critical startup path. |
| No field Web Vitals collection | Enabled LCP/INP/CLS/FCP capture; scrubber permits only finite nonnegative metric values, device context, and canonical routes. Metric entries, selectors, and attribution remain excluded. | Makes p75 measurement possible without recording private manuscript/art attribution. |
| Gallery loaded the full lettering editor | Editor is imported when the lettering tab opens. | Less JavaScript required to open the page gallery. |
| Pointer events repeatedly regenerated SVG and wrote browser storage | Coalesce previews to animation frames, flush the last position before commit, memoize the overlay, and persist drafts after gesture completion. | Less main-thread work while dragging; undo/cancel and final placement remain intact. |

## Local size evidence

Both production builds used the same dummy telemetry and authentication
configuration, Vite minification, and Node 24. No production credentials or
image generation were involved.

| Artifact measure | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| HTML entry and module-preloaded JavaScript, raw | 1,425.5 KB | 862.2 KB | 39.5% |
| Same JavaScript, gzip | 426.0 KB | 237.8 KB | 44.2% |
| Nine original marketing images versus their 800-pixel variants | 2,630,230 B | 1,654,126 B | 37.1% |

KB in the JavaScript measurements means 1,000 bytes. The JavaScript comparison
counts scripts and module preloads referenced by built HTML, not every
demand-loaded route or the entire application. Gzip sizes were computed
locally; actual wire compression depends on the deployment. Image savings
depend on viewport width and pixel density; high-density screens may still
select originals. One comic preview was visually inspected for readable art
and lettering.

`npm run perf:check` now enforces a 300 KB gzip budget on the HTML startup set
and rejects Spanish, French, or telemetry chunks in that set. Production
builds run this check automatically. The deferred
PostHog chunk remains large; it is an opportunity for later investigation if
field interaction measurements identify it as a problem.

## Verification and maintenance

Final verification results:

- `npm test` in `web/`: 132 files, 1,006 tests passed, no unhandled errors.
- `npm run build` in `web/`: localization check, TypeScript, Vite, and startup
  budget passed; 237.8 KB gzip against the 300 KB limit.
- `npm run lint` in `web/`: passed.
- `novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_spa_static.py -q`:
  14 passed, with two existing Starlette test-client deprecation warnings.
- `python3 scripts/check_docs_reliability.py` and `git diff --check`: passed.

No development server was started or restarted.

Meaningful regressions cover cold locale loading, public/protected auth
gating, video deferral and explicit playback, idle-work cancellation, private
Web Vitals attribution stripping, final drag coordinates, cancelled gestures,
existing editor/account behavior, cache revalidation, range requests, and
missing assets returning 404.

When marketing originals change, run `node scripts/build-marketing-images.mjs`
in `web/` and commit the previews and dimension manifest. Font refreshes use
`node scripts/self-host-fonts.mjs` and retain the bundled OFL licenses. Font
downloads are a maintenance operation; builds use checked-in files.

The image design checks were resolved by preserving explicit `src` attributes
on responsive images. No image checks were suppressed.

A subsequent design-hook review confirmed the lettering check list's red/amber
edge as a pre-existing severity indicator, introduced on September 24 in
`3dd7afb27`. A `side-tab` exception is scoped to
`web/src/components/lettering/lettering.css` in `.impeccable/config.json`;
other design rules remain active. The stylesheet was not changed by this audit.

## Remaining measurement gaps

After deployment, repeat mobile/desktop PageSpeed runs against the same URL
and confirm actual cache/font/image responses. Check that PostHog receives
numeric `$web_vitals` events, then compare mobile and desktop p75 over a
meaningful traffic window. Targets are LCP ≤ 2.5 seconds, INP ≤ 200 ms, and
CLS ≤ 0.1 at the 75th percentile, as defined by
[Google's Core Web Vitals guidance](https://web.dev/articles/vitals).

PostHog's standard Web Vitals capture measures document visits. It does not
prove soft-navigation speed between studio rooms, editor frame times, or
provider job latency. Those need representative authenticated interaction
measurements if field evidence warrants further work. No measured post-change
production score or p75 improvement is claimed here.

Measurement implementation references:
[PostHog Web Vitals](https://posthog.com/docs/web-analytics/web-vitals),
[JavaScript configuration](https://posthog.com/docs/libraries/js/config), and
[LCP optimization](https://web.dev/articles/optimize-lcp).
