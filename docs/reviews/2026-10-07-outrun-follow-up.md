# Outrun audit follow-up

Status: Historical — October 7, 2026 production observations and local changes.
Local changes below have not been deployed by this review.

## Implemented locally

- Lightsail Nginx redirects HTTP and the HTTPS `www` alias to the canonical
  HTTPS origin, retaining paths and query strings. ACME handling is preserved.
- All shared brand symbols declare their intrinsic square dimensions; CSS
  continues to determine their displayed size.
- Prerendering and client navigation share public-page snippet/image preview
  directives and English, Spanish, or French Open Graph locale metadata.
  Reader/story content retains its existing preview policy. Utility pages
  retain noindex, and navigation clears the previous marketing locale.

The Nginx file is installed on the host, outside the application image release.
An operator must install the reviewed file, run `nginx -t`, reload Nginx, and
verify `https://www.scenewright.ink/pricing?check=canonical` returns a 308 to
`https://scenewright.ink/pricing?check=canonical`. Verify the bare-host page still
returns 200 and ACME requests still reach their dedicated location.

## Fresh performance evidence

The [mobile PageSpeed report](https://pagespeed.web.dev/analysis/https-scenewright-ink/f96z28eds9?form_factor=mobile)
captured October 7 at 09:15 EDT reports performance 94, accessibility 100,
best practices 92, and SEO 100. Mobile emulates Moto G Power with slow 4G and
Lighthouse 13.5.0. FCP is 2.1 seconds, LCP 2.7 seconds, TBT 0 ms, CLS 0.006,
and Speed Index 2.8 seconds. There is no CrUX field data.

These measurements precede this follow-up's deployment and must not be credited
to its local edits. A previous Outrun snapshot reported performance 73 and LCP
4.1 seconds. Lab variability and intervening releases prevent a causal comparison.

The LCP element is `h1#landing-hero-title`, not the first image. Its diagnostic
breakdown reports 80 ms TTFB and 1,070 ms render delay (trace subparts are not
the simulated headline metric). Two stylesheets block rendering: main CSS
23.3 KiB and homepage CSS 8.6 KiB, with estimated savings of 330 ms. The existing
high-priority poster preload is present. No further hero-priority change is
warranted. CSS splitting/critical CSS is the next measured optimization candidate,
but requires its own visual/hydration verification; this review does not add
an unmeasured asynchronous stylesheet workaround.

The console error behind the best-practices score is a Cloudflare-injected
`static.cloudflareinsights.com/beacon.min.js` blocked by the existing CSP.
Confirm whether Cloudflare Web Analytics injection is intended. If redundant
with the existing PostHog telemetry, disable that injection in Cloudflare;
do not broaden script permissions merely to improve the audit score.

## Mail and security reporting

Public DNS on October 7 routes incoming mail through Cloudflare. SPF includes
Cloudflare and Purelymail. All three documented Purelymail DKIM selectors
(`purelymail1`, `purelymail2`, `purelymail3`) resolve to their corresponding
`keyN.dkimroot.purelymail.com` CNAME targets; selector 1 also resolves to a
nonempty DKIM public key. The scanner's common-selector failure does not
establish missing DKIM. DNS alone does not prove that actual outbound messages
are signed or pass DMARC alignment.

DMARC is `p=none` with aggregate reporting configured. Before enforcement,
review those reports and representative outbound authentication results for
every sender (including auth mail), resolve alignment failures, then stage
quarantine/reject. No DNS policy was changed. There is no `_mta-sts` TXT record;
MTA-STS remains separate mail-provider configuration work, not an SEO fix.
Provider reference: [Purelymail domain setup](https://smtp.purelymail.com/docs/domainDocs).

`/.well-known/security.txt` returned 404 during the production audit. After the
operator confirmed domain mail is monitored, a static file was added locally
with `security@scenewright.ink`, a fixed September 30, 2027 expiry, Canonical,
and Preferred-Languages. Review the contact before renewing that date; expiry
does not advance automatically on builds or requests.
[RFC 9116](https://www.rfc-editor.org/rfc/rfc9116.html) defines the format.

## Other findings

The production homepage has working Last-Modified revalidation (conditional
request returned 304), six visible question/answer disclosures, complete static
content, and a wildcard robots group permitting public marketing URLs. Explicit
training-crawler opt-ins, invented entity/schema properties, removal of legal
pages from the sitemap, and content-detector-driven rewrites are not fixes.
Sitemap modification dates remain omitted until trustworthy content-revision
timestamps are available; do not substitute request time or every build time.

## Local verification

- Full frontend suite: 1,043 tests across 138 files passed, including hydration
  against the newly built public documents and metadata navigation checks.
- Public-site, static-delivery and publication backend checks: 71 passed.
  Four browser-backed cases needed a retry outside the process sandbox; their
  initial failures were Chromium launch failures, and all four then passed.
- Frontend lint and build passed with public test Supabase configuration and
  source-map uploads disabled. Startup JavaScript is 238.2 KB gzip, under the
  existing 300 KB budget.
- Nginx syntax/configuration validation passed in an isolated official Nginx
  container with temporary test certificates and logging/include paths. No
  server was started. This does not replace validation on the production host.
- Changed Python test lint, generated-reference check, documentation reliability,
  and whitespace checks passed.

No development server, production deployment, DNS change, or provider generation
was initiated. The security contact is confirmed; the file awaits deployment
with the other local changes.
