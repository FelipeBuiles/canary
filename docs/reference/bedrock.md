# AWS Bedrock

**Status: Current, October 3, 2026.** Provider-free gateway contracts verify the
request and response mapping. Live inference has not been verified.

Canary offers Claude Opus 5.5 and Sonnet 5.5 through both Anthropic's API and
AWS Bedrock. Choose the provider per stage in **Backoffice → Stage models**, or
in account/project model controls on a development server.

| Picker label | Canary alias | Provider model |
|---|---|---|
| Claude Opus 5.5 | `claude-opus-5-5` | `anthropic/claude-opus-5-5` |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | `anthropic/claude-sonnet-5-5` |
| Claude Opus 5.5 · Bedrock | `bedrock-claude-opus-5-5` | `bedrock/converse/global.anthropic.claude-opus-5-5` |
| Claude Sonnet 5.5 · Bedrock | `bedrock-claude-sonnet-5-5` | `bedrock/converse/global.anthropic.claude-sonnet-5-5` |

The aliases are distinct job selections and retain their billing provider in
usage records. Saving a selection applies to new jobs. Defaults and running
job snapshots retain their current choices. The routes do not fall back between
Anthropic and Bedrock.

## Gateway credentials

Provider credentials belong in the LiteLLM gateway environment, outside project
configuration. Set `AWS_REGION_NAME=us-east-1` (the source region) and use either:

- `AWS_BEARER_TOKEN_BEDROCK`: a Bedrock API key.
- The standard AWS credential chain: an IAM role, or `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY`. Temporary credentials also need `AWS_SESSION_TOKEN`.
  A gateway running outside Docker can use its standard AWS profile files.

[.env.example](../../.env.example) lists these settings. Both gateway services in
`docker-compose.yml` forward the region, Bedrock API key, and AWS environment
credentials. The host's `~/.aws` directory is not mounted into the containers.
Set the same variables as secrets/environment settings in a hosted gateway.
Direct Anthropic choices continue to use `ANTHROPIC_API_KEY`.

### Local AWS console sign-in

The gateway supports the AWS CLI's `aws login` session through Boto3's CRT
dependency. With AWS CLI 2.32.0 or newer, run `aws login --profile default`,
then verify the identity with `aws sts get-caller-identity --profile default`.
Set these non-secret values in the root `.env`, using your actual absolute paths:

```dotenv
AWS_REGION_NAME=us-east-1
AWS_PROFILE=default
CANARY_AWS_CONFIG_FILE=/Users/you/.aws/config
CANARY_AWS_LOGIN_CACHE_DIRECTORY=/Users/you/.aws/login/cache
```

Leave AWS key and Bedrock API-key variables unset when using this session.
The override sets both Boto3's `AWS_PROFILE` and LiteLLM's `AWS_PROFILE_NAME`,
so SigV4 requests explicitly use the login profile rather than empty key
placeholders from the base Compose file. A Bedrock API key still takes
precedence over SigV4. `scripts/dev.sh`
automatically adds `docker-compose.aws-login.yml` when the cache path is set.
For manual Compose commands, add that override alongside any Vertex override:

```bash
docker compose -f docker-compose.yml -f docker-compose.aws-login.yml up -d --build litellm
```

Recreate an existing gateway to apply the environment and mounts. The override
mounts only the config file (read-only) and login cache (writable for refresh),
without copying credentials into `.env` or the image. The SDK refreshes temporary
credentials during the login session; when the session expires, run
`aws login --profile default` again on the host. See AWS's
[console sign-in credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html#login-credentials)
and [CLI sign-in](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html).

The identity needs `bedrock:InvokeModel` for buffered calls and
`bedrock:InvokeModelWithResponseStream` for streaming calls, scoped to the
selected inference profiles and their destination foundation models. Global
profiles can route requests worldwide, outside the configured source region.
See AWS's [cross-region inference permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html)
and [model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html).
Read-only model listing does not establish successful inference. Marketplace
agreement/access requirements must also be satisfied for the gateway identity.

## Request and accounting contracts

Bedrock uses the Converse API through the pinned LiteLLM gateway. It preserves
native JSON schemas, image inputs, adaptive thinking with visible summaries,
and low/medium/high effort. Every request explicitly sets its output token
limit, including thinking headroom, capped at 128,000 tokens. Schemas travel as
Converse `outputConfig`; effort and thinking travel in
`additionalModelRequestFields`. Schema-less JSON uses the existing instruction
and parser. No sampling temperature or forced tool call is added.

Each route's `model_info.id` uses LiteLLM's internal
`bedrock_converse/global.anthropic.<model>` key. This ensures the pinned model
map recognizes native structured output and prices the actual Converse route;
registering only the external `bedrock/converse/…` key loses the schema.

The global profiles use standard base rates: Opus 5.5 is $4 input / $20 output
per million tokens; Sonnet 5.5 is $2 input / $10 output. Both have $0.20 cache
reads per million tokens. Five-minute cache creation is $5 for Opus and $2.50
for Sonnet. These rates are pinned in gateway configuration and the app's
pricing overrides. Provider-reported cost remains authoritative; token-based
fallback calculations retain their existing source label.
See [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
and [LiteLLM's Bedrock profile pricing](https://docs.litellm.ai/blog/claude_sonnet_5_5).

Provider-free tests cover both models, buffered and streamed responses, all
three effort settings, native schemas, vision inputs, Bearer and SigV4 auth,
temporary session tokens, provider attribution, and pricing. They do not
establish live model access or generation quality.
