# Media delivery options — 2026-08-04

> Verified against first-party provider documentation on 2026-08-04. This is a
> decision note, not an implementation record. Prices and free allowances can
> change; re-check the linked source before provisioning.

## Conclusion

**Use Cloudflare R2 with a Cloudflare custom domain for immutable rendered-page
images and finalized PDF/CBZ downloads, after the byte-size work.** It is the
best fit for Canary's small launch because it has no Internet-egress charge,
the first 10 GB-month / 1M writes / 10M reads are free, and the repository
already has an optional R2 export helper at
`novel_to_comic/src/novel_to_comic/storage.py`.

This can start at $0 if the project stays within R2's allowance and a domain is
already available. A CDN does **not** make a PDF, CBZ, or image smaller; it
makes repeat delivery faster and avoids serving every byte from the Fly app.
The first request in an edge location is still a cache miss. Generate a smaller
preview derivative for Draw/Book and use efficient page-image encoding before
adding delivery infrastructure.

Do not point a CDN blindly at the authenticated app's current media routes:
they send `Cache-Control: private`. Nor use the R2 `r2.dev` address in
production. The R2 custom-domain solution is public by default, so the design
must separately preserve the existing per-user access contract.

## Provider comparison

| Option | Current free allowance / delivery | Fit and caveats |
| --- | --- | --- |
| **Cloudflare R2 + custom domain** | 10 GB-month Standard storage, 1M Class A (write) operations, and 10M Class B (read) operations each month; Internet egress is free. | **Recommended.** A custom domain puts objects behind Cloudflare Cache. The free allowance excludes Infrequent Access. A custom-domain bucket becomes public; cache only immutable, versioned object keys and enforce author access before release. On Free/Pro/Business, an individual object over 512 MB is not cacheable. |
| **Supabase Storage** | Free: 1 GB file storage and 10 GB total bandwidth (5 GB cached + 5 GB uncached); it includes a Basic CDN. | Good if keeping media with the existing Supabase account matters more than capacity/cost. Its free tier is too small for comic source pages plus exports; Image Transformations are unavailable on Free. Private buckets retain authorization but get poorer cross-user cache hits. |
| **Backblaze B2 + Cloudflare** | B2's first 10 GB is free; direct B2 downloads have 1 GB/day free. Backblaze documents $0 download fees when public B2 content is delivered through Cloudflare, whose Free Website plan can be used. | A credible low-cost alternative, but the documented simple setup is public buckets, needs a Cloudflare rewrite rule, and adds another provider. Not worth replacing the already-prepared R2 seam unless R2's operation billing becomes material. |
| **Cloudinary** | 25 shared credits/month; a credit is 1 GB storage **or** 1 GB image bandwidth **or** 1,000 transformations. | Useful only for a small proof of responsive image derivatives. Its combined quota is unsuitable as primary storage for original pages and PDF/CBZ exports. |

## Cloudflare implementation guardrails

1. Keep source/project artifacts on the app volume initially; upload only
   **approved immutable deliverables** (preview rendition, full page, and
   finalized export) to a separate R2 bucket/key prefix. Existing R2 code only
   uploads exports and currently builds public URLs, so it must not be extended
   to private Draw/Book material unchanged.
2. Use a controlled custom hostname such as `media.scenewright.ink`, with the
   domain in the same Cloudflare account as the bucket. `r2.dev` is rate-limited
   and explicitly development-only; it does not support Cache, WAF, or bot
   controls.
3. Name rendered output by content/revision (for example
   `.../page-003.<render-hash>.webp`) and send long-lived public cache headers.
   Cloudflare does not cache responses marked `private`, `no-store`, `no-cache`,
   or `max-age=0`, nor responses with `Set-Cookie`. PDF, ZIP/CBZ, PNG, JPEG,
   WebP, and AVIF are among Cloudflare's default cacheable extensions, but make
   cache rules explicit and check `cf-cache-status` in a deployment test.
4. Treat access control as a design requirement, not obscurity. R2 custom
   domains expose a public URL. Cloudflare documents WAF token auth/Access for
   restriction; R2 S3 presigned URLs work only on the S3 endpoint, not a custom
   domain. A private, cacheable author-media route therefore needs an explicit
   authenticated edge/proxy design before implementation. Avoid caching a
   response keyed solely by an author cookie or a reusable signed URL.
5. Set a lifecycle/retention rule and a spend alert before enabling uploads.
   R2's free storage is only 10 GB-month. Above it, Standard is $0.015/GB-month,
   $4.50/million Class A, and $0.36/million Class B operations. It has no
   Internet-egress price, but its billing rounds usage up to the listed units.

An authentication Worker is an optional later step, not the launch default:
Workers Free allows 100,000 requests/day with 10 ms CPU per invocation, and
even a cached response that invokes a Worker counts as a Worker request.

## Primary sources

- [Cloudflare R2 pricing and free-tier limits](https://developers.cloudflare.com/r2/pricing/)
- [Cloudflare: cache R2 through a custom domain](https://developers.cloudflare.com/cache/interaction-cloudflare-products/r2/)
- [Cloudflare R2 public-bucket, caching, and access-control guidance](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [Cloudflare default cache behavior and 512 MB free-plan cacheable-object limit](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/)
- [Cloudflare R2 presigned URL limitation](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
- [Cloudflare Workers Free limits and cache accounting](https://developers.cloudflare.com/workers/platform/pricing/)
- [Supabase pricing](https://supabase.com/pricing)
- [Supabase Storage pricing](https://supabase.com/docs/guides/storage/pricing)
- [Supabase Storage CDN behavior and private-bucket cache tradeoff](https://supabase.com/docs/guides/storage/cdn/fundamentals)
- [Supabase Storage bandwidth limits](https://supabase.com/docs/guides/storage/serving/bandwidth)
- [Backblaze B2 pricing](https://help.backblaze.com/hc/en-us/articles/217667478-Understanding-B2-Pricing-Structure)
- [Backblaze: deliver public B2 content through Cloudflare's CDN](https://www.backblaze.com/docs/cloud-storage-deliver-public-backblaze-b2-content-through-cloudflare-cdn)
- [Cloudinary billing and free-credit definitions](https://cloudinary.com/documentation/billing_and_plans)
