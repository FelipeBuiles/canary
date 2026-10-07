# Textract runtime permission

`textract-detect-text.json` is the identity policy for the dedicated
`/canary/canary-textract` IAM user. It grants only synchronous text detection in
`us-east-1`. There is no S3, IAM, asynchronous job, or document-analysis access.
Textract does not offer a resource ARN for this operation, so `Resource: "*"`
is required; the action and region are constrained.

The action was generated from the Python adapter with AWS IAM Policy Autopilot
0.3.0, then constrained to the configured region:

```sh
uvx iam-policy-autopilot@latest generate-policies \
  "$PWD/litellm_handlers/textract.py" \
  --region us-east-1 --account 569757033859 --service-hints textract --pretty
```

Credentials belong only in the encrypted production bundle and private local
configuration, never this directory. See [Textract setup](../../docs/reference/textract-ocr.md).
