# Private tester sessions

**Status: Current, October 1, 2026.** Local integration, authenticated API
persistence, and PostgreSQL access checks are verified. Production rollout and
participant data transfer are pending.

The backoffice **Tester sessions** tab integrates the actual Scenewright Tester
Log exported from `https://claude.ai/artifact/BAoddp6wmS7Ga1y4L67pHh` on October 1.
The export was downloaded through the artifact’s **Export → HTML** control in
the user’s existing Chrome session, without a CAPTCHA or authentication change.
Original filename: `Scenewright Tester Log.html` (58,223 bytes). SHA-256:
`81ab91c0935656fbed927bd2723fd4c48d78241f9ed9f5c54a08769e1dbfff01`.
The reference uses a 45-minute guide, three session variants, tagged notes,
assistance counts, debrief scores, findings linked to evidence, and day-7 returns.
The HTML export contains the UI, not the artifact's saved database records.
The three existing participants have not been imported. Obtain their data export
or transfer their card fields explicitly; do not infer booking dates, consent,
credit authorization, grants, or usage from the playbook.

The UI runs in a sandbox inside the existing backoffice. Only the React host
sends API requests using the existing operations token. The sandbox has no
same-origin privileges or credentials. App data requests stay in the host; the
frame permits only the same hosted Google font families as the main app, with
no referrer. Colors and typography tokens come from the host design system.
Credit fields record research evidence; they never write to the credit ledger.

`GET /api/ops/backoffice/tester-tracker` loads active records. `PUT` on
`/api/ops/backoffice/tester-tracker/{collection}/{record_id}` accepts `mode`
(`set`, `update`, `delete`), `data`, and `expected_revision`. Collections are
`people`, `sessions`, `notes`, and `findings`. A service-role-only transaction
serializes each record and rejects stale revisions with HTTP 409. Reload before
editing after a conflict or an unconfirmed save. There is no automatic retry.
Deletes retain the record's data with `deleted=true`; recovery currently requires
an operator to inspect that row and clear its deletion flag while incrementing
its revision. Tester deletion retains sessions and notes.

## Rollout

1. Review and apply `docs/migrations/2026-10-01-tester-tracker.sql` once to the
   intended database. The canonical schema includes the same definitions for
   new databases. No previous release migrations are needed for this feature.
2. Deploy the backend and frontend together after normal release checks pass.
3. Connect the private backoffice and verify create, reload, edit, conflict,
   note capture, and soft deletion in an approved test environment. Verify that
   anonymous and customer credentials cannot read the table or invoke its RPC.
4. Import the actual participant records privately, outside the frontend bundle.

Offline browser QA with simulated records exercises the same component and
transport, but does not establish actual Supabase persistence or RLS behavior.

Local verification: the release database component passed 40 cases, including
the six tracker PostgreSQL cases. These verify committed data across connections,
operator-token enforcement, concurrent revision conflicts, soft deletion,
merged record-size limits, and anonymous/customer denial of table and RPC
access. The standalone migration was also applied twice successfully to that
disposable database. Browser QA used synthetic records in the actual backoffice
component at desktop and narrow widths; it did not contact the production API.
