# Gemini through Vertex AI

**Status: Current, October 3, 2026.** The gateway route and provider-free
contracts are implemented. A local structured streaming smoke call succeeded
with fresh impersonated credentials for `canary-vertex` in
`project-b9574d1f-6b2c-4762-aff`, returning `{"ok":true}` with 51 input and 5 output
tokens (estimated USD $0.000057 before credits). This verifies that account's
Vertex access; deployed servers still require updated configuration and images.

Select `gemini-3.8-flash` in Account/Project Models (dev), Backoffice stage
models, or Labs. It supports text and vision stages, with Low/Medium/High
reasoning (default Medium). The gateway's built-in `vertex_ai` adapter calls
`aiplatform.googleapis.com` using the configured project and Application Default
Credentials (ADC). It does not use `GEMINI_API_KEY` or the Gemini Developer API.

Gemini now uses the successful medium-reasoning Labs tuning behavior:
Extract, Brief, Adapt, and Plan receive their stage checklists after the source
context, and Plan always uses the reviewed global map plus local detail workflow.
Detail requests use one shared page/panel template and a list of lettering-ID
placements; local validators still enforce exact page count, beat ownership,
lettering ownership/order, and visual authorities. Repairs use the same format.
Every Gemini structured call compiles its schema with `gemini_output_schema`
and sends it as JSON-mode instructions (`schema_instructions`, both in
`ai/gemini_schema.py`, applied by `gemini_tuning.tuned_request`). No stage or
feature has its own Gemini transport rule. The compiled schema requires every
declared property (declared nullable unions stay nullable), drops defaults and
turns fixed integer enums into equal minimum/maximum bounds.
Other providers retain their existing prompts and workflows. This does not force High reasoning:
Medium remains the default and the selected Low/Medium/High setting is preserved.
Checkpoint and paid-request hashes include the effective tuned inputs, so an
older stock response cannot satisfy a tuned request. Historical Labs arms use
a request-local override to retain their original comparison behavior.

Vertex's native constrained decoding (`responseJsonSchema`, which the gateway
passes our schema through unchanged) is not used. Direct REST probes on
2026-10-03 found three failures:

- **Optional properties are often omitted.** Four of six identical Brief
  requests returned only the two required page-range fields, which validated
  as an empty brief.
- **Schemas have an unpredictable grammar budget.** Larger schemas are rejected
  before generation with `400 INVALID_ARGUMENT` and no detail (unbilled). Cost
  grows with properties after `$ref` expansion (one 150-property definition
  used three times fails; 250 flat properties pass, 300 fail), nesting depth
  (14 nested objects pass, 16 fail) and bounded arrays, which unroll their
  items. Property kinds weigh differently, so no count predicts acceptance.
  The whole-source Extract schema exceeds it.
- **Accepted schemas can loop.** The registry-backed Extract section schema was
  accepted, but Gemini repeated known entities until the output cap, with
  fields optional or required.

JSON mode with the compiled schema in the instructions returned complete Brief
responses (3/3) and finished registry-backed section and whole-source Extract
calls. JSON mode does not enforce the schema, so the typed validators and the
bounded structured correction path decide acceptance, as for every provider.
Plan detail keeps its Gemini page template (`generic_detail_schema`); it was
introduced for the budget and is not required by JSON mode.

The project in `VERTEXAI_PROJECT` determines the Google Cloud billing account
that receives usage. Trial credits offset eligible charges on that account;
they do not make provider usage free in Canary's cost records. Verify the
project's billing account and remaining credit in Cloud Console before generation.

## Local credentials and project

Enable `aiplatform.googleapis.com` (shown as **Agent Platform API**, formerly
Vertex AI) in the credited project. Complete any Google Cloud terms/consent
required by the console. Create a dedicated `canary-vertex` service account in
that project with the **Vertex AI User** role (`roles/aiplatform.user`, displayed
as Agent Platform User). For keyless local credentials, enable the IAM Service
Account Credentials API, and give the credited account **Service Account Token
Creator** on this service account only. Then use an isolated, gitignored gcloud
directory to authenticate the credited account and impersonate `canary-vertex`:

```sh
CLOUDSDK_CONFIG="$PWD/.vertex-gcloud" gcloud auth application-default login \
  --project YOUR_CREDITED_PROJECT_ID \
  --impersonate-service-account canary-vertex@YOUR_CREDITED_PROJECT_ID.iam.gserviceaccount.com
```

Restrict the resulting ADC file to its owner (`chmod 600`). It contains a user
refresh credential which obtains short-lived service-account tokens. Do not
reuse credentials from a retired project or commit this file. This preserves
organization policies that disable service-account key creation. Where keys
are permitted, a new JSON key for this project's service account also works.

Set these values in the root `.env`:

```dotenv
VERTEXAI_PROJECT=YOUR_CREDITED_PROJECT_ID
VERTEXAI_LOCATION=global
CANARY_VERTEX_CREDENTIALS_FILE=/absolute/path/to/canary/.vertex-gcloud/application_default_credentials.json
```

`scripts/dev.sh` includes `docker-compose.vertex.yml` when the credential-file
setting is present. The override mounts only the ADC JSON file, read-only, and
sets its quota project explicitly. A missing file fails startup rather than
creating an empty credentials directory. For direct Docker commands, include
both Compose files:

```sh
docker compose -f docker-compose.yml -f docker-compose.vertex.yml build litellm
docker compose -f docker-compose.yml -f docker-compose.vertex.yml up -d litellm
```

The operator owns server restarts. A running gateway needs its updated image,
route configuration, environment and credential mount before the selection can
run; the backend needs the updated model catalog. For a native gateway, set
`GOOGLE_APPLICATION_CREDENTIALS` to the ADC file and
`GOOGLE_CLOUD_QUOTA_PROJECT` to the credited project instead of using the mount.
Hosted gateways need their own credential delivery; credentials are never baked
into either Docker image.

For a single live structured, streaming request without starting or restarting
servers, run the opt-in probe with the gateway's Python environment:

```sh
litellm/.venv/bin/python scripts/vertex_probe.py --call \
  --project YOUR_CREDITED_PROJECT_ID \
  --credentials /absolute/path/to/canary/.vertex-gcloud/application_default_credentials.json
```

The probe rejects credentials from another project, limits output to 2,048
tokens, uses Low reasoning, and never retries. It reports tokens and estimated
USD cost before trial credits; no pipeline artifacts are changed.

## Costs and verification

The request budget adds 16,384 tokens of thinking headroom and clamps the total
to 65,536 output tokens. Pre-call estimates include a 4,096-token thinking
allowance per call; actual output usage includes provider-reported thinking.
The gateway's cost includes cache reads; without a gateway cost, app fallback
pricing uses total input/output tokens. These allowances are estimates, not a
prediction of Gemini's output.

Global introductory prices are USD $0.75 per million input tokens, $0.075 cached
input, and $3.75 output including thinking, through December 31, 2026. Update the
gateway and app pricing overrides before the January 1, 2027 rate change.
The route defaults to `global`; the pinned prices describe that endpoint.
Sources: [model capabilities](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash),
[Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing),
[ADC setup](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).

Gateway contracts verify project/endpoint routing, native JSON schema and image
inputs, all three reasoning levels, buffered/streaming responses, and billable
thinking. Backend tests verify catalog selection, output budgets and usage costs.
Those checks make no paid calls and do not establish live account access.
