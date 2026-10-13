# Argon and Gemini 3.8 Flash schema comparison

**Status: Historical evidence, October 13, 2026.** These bounded probes support
current route settings, not a general quality or reliability benchmark.

Twelve direct Vertex REST calls used ADC in the configured project
`project-b9574d1f-6b2c-4762-aff`, location `global`, on synthetic story text.
Each case ran once per model, without retries. Small cases capped output at
1,024 tokens; Brief and Extract at 4,096. Gemini 3.8 used verified Low thinking;
Argon used provider defaults with no explicit thinking or sampling controls.
Those different controls and one sample per case limit timing comparisons.

| Case | Argon | Gemini 3.8 Flash | Argon / Flash seconds |
| --- | --- | --- | --- |
| Native `responseJsonSchema`, boolean + fixed integer + bounded 2-item array | 200, valid | 200, valid | 2.04 / 1.63 |
| Native `responseSchema`, boolean | 200, valid | 200, valid | 2.67 / 1.54 |
| JSON mode with small schema in prompt | 200, valid | 200, valid | 3.31 / 1.16 |
| Native compiled Brief schema (1,631 bytes) | 200, valid | 200, valid | 4.25 / 3.38 |
| Native compiled Extract schema (28,015 bytes) | 400 INVALID_ARGUMENT | 400 INVALID_ARGUMENT | 1.43 / 1.00 |
| JSON mode with full Extract schema in prompt | 200, valid | 200, valid | 7.09 / 6.11 |

All ten HTTP 200 replies ended with `STOP`, parsed as JSON and passed the
corresponding JSON Schema locally using `Draft202012Validator`. Small replies
also matched the expected content exactly. There was no output truncation and
no reported thinking-token usage. This verifies observed response conformance;
it does not prove enforcement of every JSON Schema keyword. The native Extract
errors were generic and establish rejection of this schema, not its precise
cause or a numeric grammar limit. Byte sizes are serialized schema sizes,
not context or decoder-budget limits.

The synthetic source was: “Mara opens a red door in a quiet room. She sees a blue
bird outside, smiles, and closes the door.” The JSON-mode Extract outputs
contained Mara, the bird, room, scene, sequence, participation records and every
compiled field. Both invented some unspecified visual details; these probes
measure schema behavior, not source fidelity or adaptation quality. Full stage
semantic validators and a real manuscript were not exercised.

| Model | Input tokens | Output tokens | Estimated provider USD |
| --- | --- | --- | --- |
| `gemini-4-argon` | 8,889 | 1,346 | $0.031238 |
| `gemini-3.8-flash` | 8,413 | 990 | $0.010022 |

Cost estimates use Argon's operator-approved provisional launch rates and
Flash's pinned global rates, before billing credits; they are not receipts.
The two 400 responses reported no token usage. No caching was requested.

Argon now enables verified JSON mode and registers native schema support for
small callers. Stage requests retain schema instructions plus local validation,
matching Flash, because full native Extract failed on both models. Streaming,
vision, tools, caching operations, reasoning controls and model token limits
remain unverified for Argon and unchanged in configuration. Existing defaults
remain unchanged. See [Vertex integration](../reference/vertex-ai.md).

Raw requests, responses, the probe script and machine-readable report are saved
locally under `work/argon-schema-comparison-20261013/` and
`work/argon-schema-probe.py`. These ignored artifacts contain synthetic text and
no credentials or authorization headers.

Google's [structured-output documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/control-generated-output)
and [Gemini 3.8 model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash)
document Flash support. No public Argon-specific Vertex schema contract was
found; Argon capability claims here rely on the recorded live calls.


## Subsequent reasoning verification

Later on October 13, direct Vertex probes also accepted Low, Medium and High
thinking levels. High reported 427 thinking tokens; an invalid level was rejected
at the enum field. See [current integration controls](../reference/vertex-ai.md#gemini-4-argon-optional-text-route).
The earlier schema comparison above still used provider-default Argon thinking.
