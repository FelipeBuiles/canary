# Security incident

Status: Current

1. Contain suspected access or credential exposure; stop customer generation
   if isolation or billing integrity is uncertain.
2. Preserve release SHA, request IDs, timestamps, affected accounts, and
   sanitized logs. Do not copy creative content into the incident record.
3. Rotate affected secrets and revoke sessions/keys using provider procedures.
4. Determine scope, customer impact, notification obligations, and recovery.
5. Verify account isolation, billing reconciliation, Sentry scrubbing, and
   readiness before reopening.
6. Record the timeline, owner, decisions, and follow-up work.
