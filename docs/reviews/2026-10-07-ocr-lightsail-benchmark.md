# Crop OCR on Lightsail — October 7, 2026

**Status: Historical hardware test evidence.** The optional experiment remains
production-disabled. This records tests on the existing production host, using
isolated containers and saved pixels; it is not evidence of production enablement
or general OCR accuracy.

## Environment and isolation

- Existing `canary-prod`, `us-east-1a`, Lightsail `medium_3_0`: 2 vCPUs,
  4 GB advertised RAM (3.742 GiB visible), 80 GB disk, no swap.
- Intel Xeon Platinum 8259CL, Ubuntu 24.04 host, Linux 7.0.0-1012-aws.
- Running production image
  `sha256:1218b754eed4f6c612425e38a8d83b3874427613521902b94ebc81aa8fd6e339`,
  source `ef506a57ec72396e2ce91ab580ace71e5b04c765`, Debian Bookworm/Python 3.12.15.
  The benchmark loaded OCR application source from merged `a9bea996`, with
  the operator replay argument repaired and a new offline load harness.
- Independent optional environment: PaddleOCR 3.7.0, PaddlePaddle 3.3.1,
  PaddleX 3.7.2, Pillow 12.3.0, Pydantic 2.13.5. Full resolved package versions
  are retained with the raw evidence. English PP-OCRv5 mobile detector and
  recognizer are the already-downloaded pilot models (12,960,736 bytes).
- Containers override the app entrypoint with the replay script, have no
  credentials, production project/database mounts or published ports, and use
  `--network none`, a read-only root and model/runtime mounts, dropped
  capabilities, `no-new-privileges`, no swap, and a 1,536 MiB memory ceiling.
  The writable cache is in a 1 GiB `/tmp` tmpfs; reports use a separate test mount.
- CPU quotas compare one full vCPU with a 0.4-vCPU cap. The latter approximates
  the entire VM's sustainable CPU entitlement: AWS lists a 20% baseline per
  vCPU for this two-vCPU plan. It does **not** simulate actual credit depletion
  or reserve CPU for concurrent production generation. See
  [AWS's baseline documentation](https://docs.aws.amazon.com/lightsail/latest/userguide/baseline-cpu-performance.html).
- A separate host driver samples the production version endpoint and available
  memory every second. It stops only the test container on two consecutive
  health failures, less than 512 MiB available memory, or a 600-second run limit.

## Startup blocker

The unchanged production image cannot import Paddle's native library:

```text
ImportError: libgomp.so.1: cannot open shared object file: No such file or directory
```

`ldd` confirmed the missing library. Native errors correctly became retryable,
inconclusive crop evidence rather than successful reads. The initial failing
load run was manually stopped; its exit 137 is **not** evidence of an OOM.
The benchmark now stops after an unsuccessful initial pilot instead of
repeatedly attempting native initialization during load phases.

For the successful native startup, Debian `libgomp1` version
`12.2.0-14+deb12u1` was downloaded and extracted only into the temporary test
directory. `LD_LIBRARY_PATH` supplied that directory to the isolated worker.
The worker then emitted `{"ready": true}` with networking disabled and all
runtime/model paths read-only. No production image or host package was changed.
A future Linux OCR image must provision `libgomp1` along with the optional wheels.

## Workload and scoring

The same three labelled caption reads from the Mac pilot were replayed: the
reported Robbons/Robbins first-pass misread, a synthetic actual spelling error,
and a synthetic correct-caption control. The fourth fixture has matching
primary/canonical copy and requests no native read. Expected/actual labels
remain offline scoring inputs; the worker receives cropped pixels only.

Load phases use fresh artifact directories, ten serial warm reads, and 1, 4,
or 16 simultaneous pages with one or six disputed observations each. Six-crop
pages deliberately repeat the same known region: this measures the real crop
work budget and lock contention, not six independent accuracy examples.
Each CPU configuration also runs at least 90 seconds of repeated uncached reads.
The source images are 932×1242 and 820×280; these measurements do not establish
headroom for sixteen simultaneous 24-million-pixel source pages.

The matching-cold case verifies lazy startup. A repeated pilot in the same output
locations verifies persisted report reuse; those cached reads are excluded from
uncached latency and throughput comparisons. The harness preserves incomplete
reports and worker/resource metrics; incomplete evidence is not counted as a
success even when an earlier crop disagreed with the first read.

## Measurements

The original worker uses one CPU inference thread and `enable_mkldnn=False`.
All three uncached pilot transcriptions were correct at both CPU quotas. Both
the cold matching case and the matching pilot case skipped inference. Reused
reports took about 1–5 ms, excluded from the following uncached results.

| Original worker workload | 1.0 vCPU | 0.4 vCPU |
| --- | --- | --- |
| First reported-caption read, including cold startup | 14.34 s | 36.81 s |
| Warm single crop, median of ten fresh reads | 4.20 s | 10.89 s |
| Four simultaneous pages, one crop each | 4/4 complete; 17.95 s batch | 2/4 complete; 30.20 s batch |
| Sixteen simultaneous pages, one crop each | 7/16 complete; 47.44 s batch | 1/16 complete; 41.13 s batch |
| One page, six crops | 1/1 complete; 25.98 s | 0/1 complete; 30.17 s |
| Four simultaneous pages, six crops each | 0/4 complete; 30.06 s batch | 0/4 complete; 37.32 s batch |
| Sixteen simultaneous pages, six crops each | 0/16 complete; 43.94 s batch | 0/16 complete; 65.21 s batch |
| Sustained uncached reads | 22 reads / 94.35 s | 9 reads / 96.79 s |
| Peak native child RSS | 645.2 MiB | 620.8 MiB |
| Peak sampled parent RSS | 249.8 MiB | 248.7 MiB |
| Peak aggregate cgroup memory | 680.8 MiB | 619.5 MiB |
| Child CPU, entire run | 313.640 s | 181.449 s |
| Run duration | 330.33 s | 483.74 s |

Both bounded runs exited successfully and recorded zero cgroup OOM events.
Successful script exit means the benchmark finished; it does **not** mean its
contention cases passed. Incomplete pages contain unavailable/over-budget crops
and remain retryable. A partial page can still have status `disagrees`; counting
that status as a completed check would misstate the result.

The AWS five-minute CPU aggregates reached 53.80% during the test window, and
reported burst capacity remained around 38%. Credits were available throughout;
the 0.4-vCPU run is a quota-based capacity approximation, not a claim of testing
the VM after actual credit exhaustion.

Warm one-crop throughput at the cap is insufficient even for four concurrent
pages. Cold restarts after timeouts also produced wall latencies above 30
seconds because startup has a separate allowance and resets the request clock.
Raising the timeout or simply relying on burst credits would conceal the queue
pressure; the original settings should remain production-disabled.

## CPU acceleration comparison

A temporary shadow worker changes only `enable_mkldnn=False` to `True`, keeping
one inference thread, the same pinned models, budgets and pixel-only protocol.
Its different source is included in the reader fingerprint. This tests the CPU
acceleration option documented by
[PaddleOCR](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html).
It does not change the application's worker or enable the production experiment.

The accelerated worker initialized successfully, but its first prediction failed
inside Paddle's oneDNN executor:

```text
NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]
```

The native traceback points to `onednn_instruction.cc:116`. All three requested
pilot reads became unavailable/inconclusive; no crop was accepted. The harness
exited 1 after its pilot and did not start contention, sustained or 0.4-vCPU
tests for this failing candidate. A separate one-crop diagnostic captured the
actual prediction traceback, using a temporary worker with exception logging.
This distinguishes an inference compatibility failure from startup, memory
exhaustion or the time budget. Peak child RSS was 491.6 MiB with zero cgroup OOM
events. Merely switching on MKL-DNN is not a working optimization for the tested
pins and models; no optimized-throughput result is claimed.

## Production impact and disposition

The two completed stock-worker runs sampled production's version endpoint 807
times, with **zero errors**. These are liveness probes, not authenticated user
flows or checks of a production-enabled OCR integration.

| Production measurement during isolated load | 1.0 vCPU test | 0.4 vCPU test |
| --- | --- | --- |
| Version endpoint median / p95 / maximum | 8.18 / 14.03 / 71.41 ms | 6.03 / 9.51 / 156.81 ms |
| Minimum host available memory | 1,475.7 MiB | 1,522.9 MiB |

Production's container ID, image ID and reported source SHA remained unchanged
through every run. No app restart, deployment, admission change, provider call
or production project write occurred. The isolated Linux environment occupied
1,157 MiB on disk, with 13 MiB of model files and about 1 MiB for the extracted
native library. Disk footprint is separate from resident/charged memory; parent
and child peak RSS need not occur together, so their peaks should not be added.

**Keep the current experiment disabled in production.** Before enablement:

1. Package an immutable optional Linux runtime, models and `libgomp1`, with its
   writable cache confined to `/tmp`; retain the exact resolved package/model
   provenance rather than treating six top-level pins as a complete lock.
2. Establish a compatible, faster CPU execution path and repeat this same
   budget/contention matrix. Include queued pages and cold restarts; a larger
   timeout alone does not establish capacity for sixteen operations.
3. Evaluate independent labelled real comic lettering, stylized balloons and
   intended languages. The three English captions and repeated load crops do
   not calibrate the 0.95 threshold or measure first-pass false negatives.
4. Verify memory/latency with real generation/export activity and intended page
   dimensions. Idle-production probes and these small source images do not
   establish the maximum-image or mixed-workload envelope.

## Reproduction and retained evidence

The repaired [replay](../../scripts/ocr_crop_experiment.py) passes the validator's
own unmatched observations to `verify_mismatches`. The shared fixture builder is
also used by [the load harness](../../scripts/ocr_crop_benchmark.py). Focused
tests cover correct mismatch selection, cache reuse, source preservation, six
reader calls, and stopping after an unavailable native pilot.

Run the load harness as documented in the
[experiment reference](../reference/crop-ocr-experiment.md). For this host, the
two stock runs used `--sustained-seconds 90`; the shadow attempt was configured
for 45 seconds but stopped at its failing pilot. Each run used a fresh output
directory and the same four saved fixtures. The external host driver and its
resource/health traces are retained with the local operator evidence.

Raw reports, package versions, library setup/startup/prediction logs, hashes,
per-phase results, process/cgroup samples and production traces are retained in
the ignored `work/ocr-lightsail-benchmark/` directory. This report is the
repository's durable summary; private images and generated evidence are not
committed. The final 182,906-byte diagnostic archive was retrieved and its
SHA-256 verified as
`a3b907c01ab997e1c8c579f5d61444ce51a3ec74b81ae2be7a16caa7e2e2922a`.
The temporary remote directory, optional runtime, fixtures, models, outputs and
upload archive were then removed. No test container remains. The final check
confirmed the original production container/image still running, with the
same source SHA and a successful version response.

Verification: **43 focused backend tests passed**, changed Python files passed
Ruff, documentation reliability passed, and the diff whitespace check passed.
Those tests verify software contracts; the real hardware measurements above
provide the runtime evidence.
