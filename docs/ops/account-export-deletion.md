# Account export and deletion

Status: Current

For an export request, verify identity and ownership, then provide existing
project exports and the bounded account/ledger information required by policy.
Do not expose internal notes or another user's cohort/usage records.

For deletion:

1. Verify the request and list the user's projects.
2. Reconcile open reservations, refunds, and support cases.
3. Delete owned project records/files through the documented application and
   Supabase procedures.
4. Confirm product events and feedback follow the published retention policy.
5. Record when scheduled volume snapshots containing deleted files will age
   out; snapshots are not selectively editable.
6. Verify a second user's projects remain available.
