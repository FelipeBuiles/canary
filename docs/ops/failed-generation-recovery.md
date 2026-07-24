# Failed generation recovery

Status: Current

1. Identify the release, user-owned project, stage, job/request ID, and failure
   category without copying creative payloads.
2. Confirm the credit reservation was released or actual usage was settled.
3. Retry only the failed stage/item through its normal API path; do not edit
   stage artifacts to skip lifecycle checks.
4. For a partial draw, retain completed panels and retry failed panels.
5. For provider refusal, adjust the customer-visible request through the
   supported editor and create a new immutable generation request.
6. Stop and investigate if retry would double-debit, overwrite accepted work,
   or require restarting the entire project.
